#!/usr/bin/env python3
"""Verify the Phase 7 private-network boundary.

Without ``--live`` this command is safe to run on a development machine: it
checks the tracked deployment contract and the default transport settings. On
the Pi, ``--live --strict`` additionally probes the AP interface and loads the
FastAPI health, landing, and network-status endpoints.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import AppSettings
from botanika.network import AccessPointConfig, NetworkStatusProbe


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


DEPLOYMENT_FILES = (
    "config/environments/phase7-native-packages.txt",
    "config/environments/phase7-network.env.example",
    "deploy/network/hostapd.conf.example",
    "deploy/network/dnsmasq.conf.example",
    "deploy/network/nftables.conf.example",
    "deploy/systemd/botanika-access-point.service",
    "deploy/systemd/botanika-hostapd.service",
    "deploy/systemd/botanika-dnsmasq.service",
    "deploy/systemd/botanika-firewall.service",
    "deploy/systemd/botanika-backend.service",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="probe the configured AP and HTTP endpoints in addition to static checks",
    )
    parser.add_argument(
        "--url",
        default="http://192.168.50.1:8000",
        help="AP FastAPI base URL for live HTTP checks",
    )
    parser.add_argument(
        "--loopback-url",
        default="http://127.0.0.1:8000",
        help="loopback FastAPI base URL for live HTTP checks",
    )
    parser.add_argument(
        "--hostname-url",
        default="http://botanika.home.arpa:8000",
        help="local DNS FastAPI base URL for live hostname checks",
    )
    parser.add_argument("--interface", default="wlan0", help="AP interface for live probing")
    parser.add_argument("--address", default="192.168.50.1", help="AP address for live probing")
    parser.add_argument("--port", type=int, default=8000, help="FastAPI port for live probing")
    parser.add_argument("--json", action="store_true", help="render machine-readable output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return failure when any requested check is unavailable",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = _static_checks()
    if args.live:
        try:
            config = AccessPointConfig(
                interface=args.interface,
                address=args.address,
                api_port=args.port,
                enabled=True,
            )
            status = NetworkStatusProbe(config).status()
            checks.append(
                Check(
                    "access-point-state",
                    status.available,
                    status.detail,
                )
            )
            checks.extend(_http_checks(args.url, "AP"))
            checks.extend(_http_checks(args.loopback_url, "loopback"))
            checks.extend(
                _http_checks(
                    args.hostname_url,
                    "hostname",
                    paths=(("/connect", "Botanika"),),
                )
            )
        except ValueError as exc:
            checks.append(Check("live-configuration", False, str(exc)))
    else:
        checks.append(
            Check(
                "physical-pi-checks",
                True,
                "deferred: run with --live on the configured Pi; no AP state was claimed here",
            )
        )

    payload = {"phase": 7, "checks": [check.to_dict() for check in checks]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Botanika Phase 7 network verification")
        for check in checks:
            marker = "PASS" if check.passed else "FAIL"
            print(f"[{marker}] {check.name}: {check.detail}")
    if args.strict and any(not check.passed for check in checks):
        return 1
    return 0


def _static_checks() -> list[Check]:
    checks: list[Check] = []
    for relative in DEPLOYMENT_FILES:
        path = PROJECT_ROOT / relative
        checks.append(Check(f"file:{relative}", path.is_file(), "present" if path.is_file() else "missing"))

    try:
        settings = AppSettings()
        checks.append(
            Check(
                "solo-default",
                settings.loopback_only and not settings.network_enabled and settings.host == "127.0.0.1",
                "AppSettings defaults to loopback-only SOLO",
            )
        )
        network_settings = AppSettings(network_enabled=True, loopback_only=False, host="0.0.0.0")
        checks.append(
            Check(
                "network-settings",
                network_settings.access_point_address == "192.168.50.1"
                and network_settings.local_hostname == "botanika.home.arpa",
                "network mode validates the stable private AP address and hostname",
            )
        )
    except Exception as exc:
        checks.append(Check("settings-validation", False, str(exc)))

    env_text = (PROJECT_ROOT / "config/environments/phase7-network.env.example").read_text(
        encoding="utf-8"
    )
    checks.append(
        Check(
            "secret-placeholder",
            "REPLACE_WITH_A_RANDOM_PRIVATE_PASSPHRASE" in env_text,
            "tracked environment file contains a placeholder, not a real WPA secret",
        )
    )
    firewall_text = (PROJECT_ROOT / "deploy/network/nftables.conf.example").read_text(encoding="utf-8")
    checks.append(
        Check(
            "firewall-boundary",
            "iifname != $botanika_ap_if" in firewall_text
            and "chain forward" in firewall_text
            and 'iifname "lo" tcp dport $botanika_api_port accept' in firewall_text
            and "iifname $botanika_ap_if drop" in firewall_text,
            "loopback and the AP are allowed; unrelated interfaces cannot reach the API port and AP forwarding is dropped",
        )
    )
    manager_text = (PROJECT_ROOT / "backend/src/botanika/network/manager.py").read_text(
        encoding="utf-8"
    )
    backend_unit = (PROJECT_ROOT / "deploy/systemd/botanika-backend.service").read_text(
        encoding="utf-8"
    )
    ap_unit = (PROJECT_ROOT / "deploy/systemd/botanika-access-point.service").read_text(
        encoding="utf-8"
    )
    checks.append(
        Check(
            "safe-solo-recovery",
            "remove the Botanika AP firewall table" not in manager_text
            and "Requires=botanika-access-point.service" not in backend_unit
            and "PartOf=botanika-backend.service" not in ap_unit
            and "run_api.py --network" not in backend_unit,
            "AP failure cannot block SOLO startup and AP stop/recovery retains the firewall boundary",
        )
    )
    hostapd_text = (PROJECT_ROOT / "deploy/network/hostapd.conf.example").read_text(encoding="utf-8")
    checks.append(
        Check(
            "wifi-security",
            "wpa=2" in hostapd_text
            and "wpa_key_mgmt=WPA-PSK SAE" in hostapd_text
            and "BOTANIKA_AP_PASSPHRASE" in env_text,
            "hostapd fallback supports WPA2/WPA3 transition mode and reads its secret from machine-local state",
        )
    )
    dns_text = (PROJECT_ROOT / "deploy/network/dnsmasq.conf.example").read_text(encoding="utf-8")
    checks.append(
        Check(
            "local-dhcp-dns",
            "dhcp-range=" in dns_text
            and "address=/botanika.home.arpa/192.168.50.1" in dns_text
            and "no-resolv" in dns_text,
            "DHCP and local hostname DNS are configured without an upstream resolver",
        )
    )
    return checks


def _http_checks(
    base_url: str,
    label: str,
    *,
    paths: tuple[tuple[str, str], ...] | None = None,
) -> list[Check]:
    base = base_url.rstrip("/")
    checks: list[Check] = []
    requested_paths = paths or (
        ("/api/v1/health/live", "botanika-api"),
        ("/connect", "Botanika"),
        ("/api/v1/network/status", "private-access-point"),
        ("/api/v1/scan/state", '"state"'),
        ("/api/v1/library", '"records"'),
    )
    for path, expected in requested_paths:
        url = f"{base}{path}"
        try:
            request = Request(url, headers={"Accept": "application/json,text/html"})
            with urlopen(request, timeout=4.0) as response:
                body = response.read(256 * 1024).decode("utf-8", errors="replace")
            passed = expected in body
            detail = f"{url} responded and contained {expected!r}" if passed else f"{url} response lacked {expected!r}"
        except (OSError, URLError, TimeoutError) as exc:
            passed = False
            detail = f"{url} unavailable: {exc}"
        checks.append(Check(f"http:{label}:{path}", passed, detail))
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
