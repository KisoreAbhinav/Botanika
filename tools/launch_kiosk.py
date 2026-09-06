#!/usr/bin/env python3
"""Wait for the local Botanika readiness endpoint, then launch Chromium at 800×480."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-url", default="http://127.0.0.1:8000/api/v1/health/ready")
    parser.add_argument("--app-url", default="http://127.0.0.1:8000/")
    parser.add_argument("--browser", default=shutil.which("chromium") or shutil.which("chromium-browser") or "chromium")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def readiness(url: str) -> tuple[bool, str]:
    try:
        with urlopen(url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        status = str(payload.get("status", "unknown"))
        # The API returns 200 for degraded hardware so the local typed/fallback
        # surfaces can still be used. Reachability is the launch gate; the
        # browser displays the individual capability details.
        return True, status
    except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
        return False, str(exc)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    deadline = time.monotonic() + max(0.1, args.timeout)
    last_detail = "not checked"
    while time.monotonic() < deadline:
        ready, detail = readiness(args.ready_url)
        last_detail = detail
        if ready:
            profile_dir = Path(tempfile.mkdtemp(prefix="botanika-chromium-"))
            try:
                command = [
                    args.browser,
                    "--kiosk",
                    "--window-size=800,480",
                    "--force-device-scale-factor=1",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--noerrdialogs",
                    "--disable-infobars",
                    "--disable-session-crashed-bubble",
                    f"--user-data-dir={profile_dir}",
                    args.app_url,
                ]
                print(json.dumps({"status": "ready", "readiness": detail, "command": command}))
                if args.dry_run:
                    return 0
                try:
                    return subprocess.call(command)
                except OSError as exc:
                    print(json.dumps({"status": "error", "detail": str(exc)}))
                    return 1
            finally:
                shutil.rmtree(profile_dir, ignore_errors=True)
        time.sleep(max(0.05, args.interval))
    print(json.dumps({"status": "timeout", "detail": last_detail, "ready_url": args.ready_url}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
