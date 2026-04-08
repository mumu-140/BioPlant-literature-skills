#!/usr/bin/env python3
from __future__ import annotations

import argparse
import plistlib
from pathlib import Path

try:
    from project_layout import DEFAULT_RUNTIME_CONFIG_PATH, canonical_paths, load_runtime_config
except ModuleNotFoundError:
    from scripts.project_layout import DEFAULT_RUNTIME_CONFIG_PATH, canonical_paths, load_runtime_config


CANONICAL_PATHS = canonical_paths()


def parse_delivery_time(value: str) -> tuple[int, int]:
    raw = str(value or "").strip()
    if not raw:
        raise SystemExit("delivery_time is empty in runtime config")
    parts = raw.split(":")
    if len(parts) != 2:
        raise SystemExit(f"delivery_time must be HH:MM, got: {raw}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SystemExit(f"delivery_time out of range: {raw}")
    return hour, minute


def render_launchd_plist(runtime_config_path: str | Path | None = None, template_path: str | Path | None = None) -> str:
    runtime = load_runtime_config(runtime_config_path or DEFAULT_RUNTIME_CONFIG_PATH)
    delivery = runtime.get("delivery", {})
    scheduler = runtime.get("scheduler", {})
    launchd = scheduler.get("launchd", {})

    hour, minute = parse_delivery_time(str(delivery.get("delivery_time", "") or "08:00"))
    replacements = {
        "__LABEL__": str(launchd.get("label", "") or "org.example.bio-digest-daily"),
        "__WRAPPER_SCRIPT__": str(launchd.get("wrapper_script", "")),
        "__WORKING_DIRECTORY__": str(launchd.get("working_directory", "")),
        "__STDOUT_LOG__": str(launchd.get("stdout_log", "")),
        "__STDERR_LOG__": str(launchd.get("stderr_log", "")),
        "__HOUR__": str(hour),
        "__MINUTE__": str(minute),
    }

    missing = [key for key, value in replacements.items() if not value]
    if missing:
        raise SystemExit(f"Missing launchd scheduler settings in runtime config: {', '.join(missing)}")

    template_file = Path(template_path).resolve() if template_path else CANONICAL_PATHS["launchd_plist_template"]
    content = template_file.read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    plistlib.loads(content.encode("utf-8"))
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a launchd plist from runtime config and template.")
    parser.add_argument("--runtime-config", default=str(DEFAULT_RUNTIME_CONFIG_PATH))
    parser.add_argument("--template", default=str(CANONICAL_PATHS["launchd_plist_template"]))
    parser.add_argument("--output", default=str(CANONICAL_PATHS["launchd_plist"]))
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    content = render_launchd_plist(args.runtime_config, args.template)
    output.write_text(content, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
