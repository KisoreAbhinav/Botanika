#!/usr/bin/env python3
"""Verify the hardware-independent Phase 8 pairing and handoff contract.

This verifier never claims a real Pi, GPIO board, phone camera, or Wi-Fi
session. It checks the tracked implementation and deterministic mode/GPIO
behaviour. The physical Phase 8 journey remains an operator gate.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import AppSettings
from botanika.hardware.gpio import GPIOPinConfig, MemoryGPIO, ModeGPIOAdapter
from botanika.mode import Mode, ModeStateMachine


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


FILES = (
    "backend/src/botanika/api/auth.py",
    "backend/src/botanika/mode/state.py",
    "backend/src/botanika/hardware/gpio.py",
    "backend/src/botanika/api/routes/mode.py",
    "frontend/src/features/mode/ModeScreens.jsx",
    "frontend/src/features/networked/NetworkedScanPage.jsx",
    "frontend/src/features/mode/modeState.test.js",
    "tests/unit/test_phase8_mode.py",
    "tools/verify_phase8_ui.py",
)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="render machine-readable output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return failure when any deterministic contract check fails",
    )
    args = parser.parse_args(argv)
    checks = _static_checks()
    checks.extend(_deterministic_checks())
    payload = {"phase": 8, "checks": [check.to_dict() for check in checks]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Botanika Phase 8 pairing verification")
        for check in checks:
            marker = "PASS" if check.passed else "FAIL"
            print(f"[{marker}] {check.name}: {check.detail}")
    if args.strict and any(not check.passed for check in checks):
        return 1
    return 0


def _static_checks() -> list[Check]:
    checks: list[Check] = []
    for relative in FILES:
        path = PROJECT_ROOT / relative
        checks.append(
            Check(
                f"file:{relative}",
                path.is_file(),
                "present" if path.is_file() else "missing",
            )
        )

    mode_source = (PROJECT_ROOT / "backend/src/botanika/mode/state.py").read_text(
        encoding="utf-8"
    )
    checks.append(
        Check(
            "mode-values",
            all(
                value in mode_source
                for value in ("SOLO", "NETWORKED_UNPAIRED", "NETWORKED_PAIRED")
            ),
            "the explicit three-state mode contract is present",
        )
    )
    route_source = (PROJECT_ROOT / "backend/src/botanika/api/routes/mode.py").read_text(
        encoding="utf-8"
    )
    checks.append(
        Check(
            "crop-only-route",
            "/controller/crop" in route_source
            and "sha256" in route_source
            and "UploadFile" in route_source
            and "commit_for_lease" in route_source,
            "the controller accepts a bounded hash-checked crop and commits it under its lease",
        )
    )
    auth_source = (PROJECT_ROOT / "backend/src/botanika/api/auth.py").read_text(
        encoding="utf-8"
    )
    checks.append(
        Check(
            "operator-controller-boundary",
            "is_loopback" in auth_source
            and "require_local_operator" in auth_source
            and "require_local_or_controller" in auth_source
            and 'pairing.pop("code"' in auth_source,
            "operator-only actions stay on loopback and remote status redacts the pairing code",
        )
    )
    browser_source = (
        PROJECT_ROOT / "frontend/src/features/networked/NetworkedScanPage.jsx"
    ).read_text(encoding="utf-8")
    checks.append(
        Check(
            "browser-camera-boundary",
            "getUserMedia" in browser_source
            and 'capture="environment"' in browser_source
            and "classifyControllerCrop" in browser_source
            and "Live video stays on this phone." in browser_source
            and "REQUIRED_STABLE_SAMPLES" in browser_source
            and "PREVIEW_URL" not in browser_source
            and "EventSource" not in browser_source,
            "camera ownership and stability-gated crop handoff stay in the paired browser",
        )
    )
    checks.append(
        Check(
            "local-quality-and-save-boundary",
            "measureQuality" in browser_source
            and "manual-crop-control" in browser_source
            and "requestPosition" in browser_source
            and "geolocation" in browser_source
            and "requestSerial" in browser_source,
            "quality/crop decisions, save-time location, and stale-request guards remain local",
        )
    )
    library_source = (
        PROJECT_ROOT / "backend/src/botanika/api/routes/library.py"
    ).read_text(encoding="utf-8")
    checks.append(
        Check(
            "lease-bound-save",
            "controller_lease_id" in library_source
            and "body.request_id" in library_source
            and "body.crop_hash" in library_source
            and "commit_for_lease" in library_source,
            "remote saves are bound to the active lease, request ID, and crop hash",
        )
    )
    app_source = (PROJECT_ROOT / "frontend/src/app/App.jsx").read_text(encoding="utf-8")
    theme_source = (PROJECT_ROOT / "frontend/src/theme/theme.css").read_text(encoding="utf-8")
    checks.append(
        Check(
            "split-layout-contract",
            "responsive-shell" in app_source
            and ".shell {" in theme_source
            and "width: 800px" in theme_source
            and "height: 480px" in theme_source,
            "the Pi canvas and responsive browser layouts are separate",
        )
    )
    return checks


def _deterministic_checks() -> list[Check]:
    checks: list[Check] = []
    clock = Clock()
    service = ModeStateMachine(
        AppSettings(pairing_ttl_seconds=10),
        clock=clock,
        token_factory=lambda: "phase8-token-" + "x" * 24,
        code_factory=lambda length: "23456789",
    )
    service.set_mode(Mode.NETWORKED_UNPAIRED)
    code = service.status()["pairing"]["code"]
    pair = service.pair(code, device_name="Verifier")
    one_controller = service.status()["controller_count"] == 1
    checks.append(
        Check(
            "pairing-flow",
            pair["mode"] == Mode.NETWORKED_PAIRED.value and one_controller,
            "SOLO to unpaired to paired creates exactly one active lease",
        )
    )
    clock.value += 11
    expired = service.status()
    checks.append(
        Check(
            "lease-expiry",
            expired["mode"] == Mode.NETWORKED_UNPAIRED.value
            and expired["controller_count"] == 0
            and isinstance(expired["pairing"], dict),
            "expiry revokes the lease and exposes a fresh invitation",
        )
    )

    backend = MemoryGPIO()
    selected = {"mode": Mode.SOLO}

    def toggle():
        selected["mode"] = (
            Mode.NETWORKED_UNPAIRED
            if selected["mode"] is Mode.SOLO
            else Mode.SOLO
        )
        return selected["mode"]

    adapter = ModeGPIOAdapter(
        GPIOPinConfig(
            mode_button_pin=4,
            solo_led_pin=17,
            networked_led_pin=18,
            paired_led_pin=27,
            debounce_ms=250,
        ),
        on_toggle=toggle,
        backend=backend,
    )
    adapter.start()
    first = adapter.button_pressed(now=1.0)
    bounced = not adapter.button_pressed(now=1.1)
    adapter.cleanup()
    checks.append(
        Check(
            "gpio-contract",
            first
            and bounced
            and backend.cleaned
            and not any(adapter.led_state.values()),
            "boot mapping, debounce, and cleanup are deterministic",
        )
    )
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
