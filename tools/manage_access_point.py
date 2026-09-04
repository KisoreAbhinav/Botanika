#!/usr/bin/env python3
"""Enable, disable, inspect, or recover Botanika's private Wi-Fi AP.

Examples (run the mutating commands as root on the Pi):

    python tools/manage_access_point.py plan enable
    sudo -E python tools/manage_access_point.py enable
    sudo -E python tools/manage_access_point.py recover
    python tools/manage_access_point.py status --json

The default operation is read-only.  The passphrase is read from the machine
environment or the optional environment file and is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.network import AccessPointConfig, AccessPointError, AccessPointManager


DEFAULT_ENV_FILE = Path("/etc/botanika/botanika.env")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "status",
            "plan",
            "enable",
            "disable",
            "recover",
            "render-hostapd",
            "mark-firewall",
        ),
        help="read status, print a plan, change AP state, or render a root-only hostapd file",
    )
    parser.add_argument(
        "operation",
        nargs="?",
        choices=("enable", "disable", "recover"),
        help="operation used with the plan action",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"machine-local environment file (default: {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--stack",
        choices=("auto", "networkmanager", "hostapd"),
        default=None,
        help="override AP stack selection",
    )
    parser.add_argument("--interface", default=None, help="override the AP interface")
    parser.add_argument("--address", default=None, help="override the AP IPv4 address")
    parser.add_argument("--hostname", default=None, help="override the local DNS hostname")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/run/botanika/hostapd.conf"),
        help="hostapd output path for render-hostapd",
    )
    parser.add_argument(
        "--firewall-config",
        type=Path,
        default=Path("/etc/botanika/nftables.conf"),
        help="installed nftables rules checked before publishing firewall readiness",
    )
    parser.add_argument("--dry-run", action="store_true", help="print mutation commands without executing them")
    parser.add_argument("--json", action="store_true", help="render status/plan as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        try:
            environment = _read_env_file(args.env_file)
        except PermissionError as exc:
            if args.action in {"status", "plan"}:
                print(
                    f"Warning: cannot read {args.env_file}; using defaults for this read-only check.",
                    file=sys.stderr,
                )
                environment = {}
            else:
                raise ValueError(f"cannot read environment file {args.env_file}: {exc}") from exc
        environment = {**environment, **os.environ}
        overrides: dict[str, object] = {"enabled": True}
        if args.stack is not None:
            overrides["stack"] = args.stack
        if args.interface is not None:
            overrides["interface"] = args.interface
        if args.address is not None:
            overrides["address"] = args.address
        if args.hostname is not None:
            overrides["hostname"] = args.hostname
        config = AccessPointConfig.from_environment(environment, **overrides)
        manager = AccessPointManager(config)

        if args.action == "status":
            _print_status(config, manager, as_json=args.json)
            return 0
        if args.action == "plan":
            if args.operation is None:
                raise AccessPointError("plan requires one of enable, disable, or recover")
            commands = manager.plan(args.operation, stack=args.stack)
            _print_plan(commands, as_json=args.json)
            return 0
        if args.action == "render-hostapd":
            output = manager.render_hostapd_config(args.output)
            print(f"Rendered hostapd configuration at {output}")
            return 0
        if args.action == "mark-firewall":
            output = manager.write_firewall_ready_marker(args.output, args.firewall_config)
            print(f"Published firewall readiness at {output}")
            return 0

        commands = getattr(manager, args.action)(dry_run=args.dry_run)
        _print_plan(commands, as_json=args.json)
        return 0
    except (AccessPointError, ValueError, OSError) as exc:
        print(f"Botanika access-point operation unavailable: {exc}", file=sys.stderr)
        return 2


def _print_status(config: AccessPointConfig, manager: AccessPointManager, *, as_json: bool) -> None:
    status = manager.status()
    payload = {"status": status, "configuration": config.to_dict()}
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"State: {status['state']}")
    print(f"Available: {'yes' if status['available'] else 'no'}")
    print(f"Interface: {status['interface']} ({status['address']})")
    print(f"Hostname: {status['hostname']}")
    print(f"URL: {status['url']}")
    print(f"Detail: {status['detail']}")
    print("Checks:")
    for name, passed in status["checks"].items():
        print(f"  {name}: {'ok' if passed else 'failed'}")


def _print_plan(commands, *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                [
                    {"command": item.display(), "description": item.description}
                    for item in commands
                ],
                indent=2,
            )
        )
        return
    for index, item in enumerate(commands, start=1):
        print(f"{index}. {item.description}: {item.display()}")


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid environment line {path}:{line_number}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            raise ValueError(f"invalid environment key {path}:{line_number}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


if __name__ == "__main__":
    raise SystemExit(main())
