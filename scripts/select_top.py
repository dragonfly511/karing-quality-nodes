
import json
import os
import sys
from pathlib import Path

import yaml

MIN_DOWNLOAD_BYTES_PER_SECOND = 3 * 1024 * 1024
MAX_NODES = 100

results_path = Path("output/speedtest-results.json")
passing_path = Path("output/passing.yaml")
final_path = Path("output/karing.yaml")
report_path = Path("output/summary.txt")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_results(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Cannot read valid JSON results: {exc}")

    if isinstance(data, dict):
        data = data.get("results", data.get("proxies", []))

    if not isinstance(data, list):
        fail("Unexpected JSON results format; expected a list.")

    return data


def main():
    for path in (results_path, passing_path):
        if not path.exists():
            fail(f"Missing required file: {path}")

    results = load_results(results_path)

    # The documented JSON field download_speed is in bytes per second.
    # Keep only successful measurements at or above 3 MiB/s.
    speed_by_name = {}

    for item in results:
        if not isinstance(item, dict):
            continue

        name = item.get("proxy_name") or item.get("name")
        speed = item.get("download_speed")

        if not name or item.get("error") not in (None, ""):
            continue

        try:
            speed = float(speed)
        except (TypeError, ValueError):
            continue

        if speed < MIN_DOWNLOAD_BYTES_PER_SECOND:
            continue

        speed_by_name[name] = max(speed_by_name.get(name, 0), speed)

    try:
        config = yaml.safe_load(
            passing_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        fail(f"Cannot parse passing YAML: {exc}")

    if not isinstance(config, dict):
        fail("The passing YAML must contain a configuration object.")

    proxies = config.get("proxies")
    if not isinstance(proxies, list):
        fail("The passing YAML has no valid 'proxies' list.")

    # Match the measured names to the exported proxy configurations.
    # Keep the fastest occurrence for each proxy name.
    proxy_by_name = {}

    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue

        name = proxy.get("name")
        if name not in speed_by_name:
            continue

        existing = proxy_by_name.get(name)
        if existing is None:
            proxy_by_name[name] = proxy

    ranked = sorted(
        proxy_by_name.items(),
        key=lambda pair: speed_by_name[pair[0]],
        reverse=True,
    )[:MAX_NODES]

    if not ranked:
        fail(
            "No nodes passed the 3 MiB/s threshold. "
            "The final subscription was not overwritten."
        )

    selected_proxies = [proxy for _, proxy in ranked]
    selected_names = [name for name, _ in ranked]

    # Create a minimal Clash-compatible configuration for Karing.
    final_config = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "proxies": selected_proxies,
        "proxy-groups": [
            {
                "name": "AUTO",
                "type": "select",
                "proxies": selected_names,
            }
        ],
        "rules": ["MATCH,AUTO"],
    }

    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(
        yaml.safe_dump(
            final_config,
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    lines = [
        "Karing Quality Nodes - Summary",
        f"Successful JSON records: {len(results)}",
        f"Nodes meeting 3 MiB/s: {len(speed_by_name)}",
        f"Nodes exported: {len(selected_proxies)}",
        "",
        "Rank | Download MiB/s | Node",
    ]

    for rank, (name, _) in enumerate(ranked, start=1):
        speed_mib = speed_by_name[name] / (1024 * 1024)
        safe_name = name.replace("\n", " ").replace("\r", " ")
        lines.append(f"{rank} | {speed_mib:.2f} | {safe_name}")

    report_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(f"Final nodes: {len(selected_proxies)}")
    print(f"Minimum download speed: 3 MiB/s")
    print(f"Final config: {final_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
