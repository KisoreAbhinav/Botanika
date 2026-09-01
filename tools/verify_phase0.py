#!/usr/bin/env python3
"""Collect and validate the Phase 0 Botanika host readiness baseline.

The verifier deliberately has no third-party dependencies. It can therefore be
run before the project environment is provisioned:

    python3 tools/verify_phase0.py
    python3 tools/verify_phase0.py --strict

Use ``--probe-capture`` only when a temporary native still is wanted. The
probe removes its temporary output after checking it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_IMPORTS = {
    "numpy": "NumPy",
    "cv2": "OpenCV",
    "picamera2": "Picamera2",
    "libcamera": "Python libcamera",
    "onnxruntime": "ONNX Runtime (YOLO-compatible runtime)",
}
NATIVE_PACKAGES = (
    "rpicam-apps",
    "libcamera0.7",
    "python3-libcamera",
    "python3-picamera2",
)


def run_command(args: list[str], timeout: float = 10.0) -> dict[str, Any]:
    """Run a read-only probe and keep its output bounded and serializable."""

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {"returncode": None, "stdout": "", "stderr": "command not found"}
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "stdout": (exc.stdout or "")[-4000:],
            "stderr": "probe timed out",
        }

    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def command_version(command: str, args: list[str] | None = None) -> str | None:
    if shutil.which(command) is None:
        return None
    result = run_command([command, *(args or ["--version"])])
    output = "\n".join(part for part in (result["stdout"], result["stderr"]) if part).strip()
    return output.splitlines()[0] if output else None


def read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def read_device_tree_value(path: str) -> str | None:
    try:
        return Path(path).read_bytes().rstrip(b"\0").decode("utf-8", "replace")
    except OSError:
        return None


def package_versions() -> dict[str, str | None]:
    if shutil.which("dpkg-query") is None:
        return {package: None for package in NATIVE_PACKAGES}

    versions: dict[str, str | None] = {}
    for package in NATIVE_PACKAGES:
        result = run_command(
            ["dpkg-query", "-W", "-f=${Version}", package],
            timeout=5,
        )
        version = result["stdout"].strip()
        versions[package] = version if result["returncode"] == 0 and version else None
    return versions


def import_versions() -> dict[str, dict[str, str | None]]:
    versions: dict[str, dict[str, str | None]] = {}
    for module_name, label in REQUIRED_IMPORTS.items():
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # Import errors can come from native bindings.
            versions[label] = {
                "module": module_name,
                "version": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
            continue
        version = getattr(module, "__version__", None)
        versions[label] = {
            "module": module_name,
            "version": str(version) if version is not None else "available",
            "error": None,
        }
    return versions


def read_temperature_celsius() -> float | None:
    candidates = (
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/class/thermal/thermal_zone1/temp"),
    )
    for path in candidates:
        try:
            return int(path.read_text(encoding="ascii").strip()) / 1000
        except (OSError, ValueError):
            continue
    return None


def format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def check(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "detail": detail, **extra}


def probe_camera(probe_capture: bool) -> dict[str, Any]:
    if shutil.which("rpicam-hello") is None:
        return check("BLOCKED", "rpicam-hello is not installed")

    enumeration = run_command(["rpicam-hello", "--list-cameras"], timeout=15)
    output = "\n".join(
        part for part in (enumeration["stdout"], enumeration["stderr"]) if part
    ).strip()
    available = enumeration["returncode"] == 0 and "No cameras available" not in output
    result: dict[str, Any] = {
        "status": "PASS" if available else "BLOCKED",
        "detail": (
            "native camera enumeration returned at least one camera"
            if available
            else "native camera enumeration did not find an accessible camera"
        ),
        "enumeration": output,
    }

    if not probe_capture:
        return result

    if shutil.which("rpicam-still") is None:
        result["capture"] = check("BLOCKED", "rpicam-still is not installed")
        return result

    capture_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="botanika-stage0-",
            suffix=".jpg",
            dir="/tmp",
            delete=False,
        ) as temp_file:
            capture_path = Path(temp_file.name)
        capture_path.unlink(missing_ok=True)
        capture = run_command(
            [
                "rpicam-still",
                "--nopreview",
                "--timeout",
                "1000",
                "--output",
                str(capture_path),
            ],
            timeout=20,
        )
        if capture_path.exists():
            image_bytes = capture_path.read_bytes()
            valid_jpeg = (
                capture["returncode"] == 0
                and len(image_bytes) > 4
                and image_bytes.startswith(b"\xff\xd8")
                and image_bytes.endswith(b"\xff\xd9")
            )
            digest = hashlib.sha256(image_bytes).hexdigest()
            result["capture"] = check(
                "PASS" if valid_jpeg else "BLOCKED",
                "native temporary still was created and has valid JPEG markers"
                if valid_jpeg
                else "native still output is not a valid JPEG",
                path=str(capture_path),
                bytes=capture_path.stat().st_size,
                sha256=digest,
                returncode=capture["returncode"],
            )
        else:
            result["capture"] = check(
                "BLOCKED",
                "native still command completed without creating an image",
                returncode=capture["returncode"],
                output="\n".join(
                    part for part in (capture["stdout"], capture["stderr"]) if part
                ).strip(),
            )
        if result["capture"]["status"] != "PASS":
            result["status"] = "BLOCKED"
            result["detail"] = "native camera capture did not produce a valid still"
    finally:
        if capture_path is not None:
            capture_path.unlink(missing_ok=True)
    return result


def probe_display() -> dict[str, Any]:
    display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    if not display:
        return check(
            "BLOCKED",
            "no active X11/Wayland display session is available to this process",
        )
    if shutil.which("xrandr") is None:
        return check("UNKNOWN", "xrandr is not installed", display=display)

    result = run_command(["xrandr", "--current"], timeout=5)
    output = result["stdout"]
    connected = re.findall(r"^\S+ connected(?: primary)?(?: [^\n]*)?", output, re.MULTILINE)
    current_modes = re.findall(r"(\d+)x(\d+)\+[-\d]+\+[-\d]+", output)
    exact = any(width == "800" and height == "480" for width, height in current_modes)
    return check(
        "PASS" if result["returncode"] == 0 and exact else "BLOCKED",
        "active display reports the required 800x480 mode"
        if result["returncode"] == 0 and exact
        else "display is available but an exact 800x480 mode was not verified",
        display=display,
        connected=connected,
        current_modes=[f"{width}x{height}" for width, height in current_modes],
        output=output[-4000:],
    )


def probe_audio(command: str, kind: str) -> dict[str, Any]:
    if shutil.which(command) is None:
        return check("BLOCKED", f"{command} is not installed")
    result = run_command([command, "-l"], timeout=5)
    output = "\n".join(
        part for part in (result["stdout"], result["stderr"]) if part
    ).strip()
    unavailable = "no soundcards found" in output.lower()
    return check(
        "PASS" if result["returncode"] == 0 and not unavailable else "BLOCKED",
        f"{kind} device enumeration returned at least one device"
        if result["returncode"] == 0 and not unavailable
        else f"no usable {kind} device was enumerated",
        output=output,
    )


def collect(probe_capture: bool) -> dict[str, Any]:
    os_release = read_os_release()
    usage = shutil.disk_usage(PROJECT_ROOT)
    native_package_versions = package_versions()
    python_imports = import_versions()
    meminfo: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            match = re.match(r"^(MemTotal|MemAvailable|SwapTotal|SwapFree):\s+(\d+)", line)
            if match:
                meminfo[match.group(1)] = int(match.group(2)) * 1024
    except OSError:
        pass

    model = read_device_tree_value("/proc/device-tree/model")
    throttle = run_command(["vcgencmd", "get_throttled"], timeout=5) \
        if shutil.which("vcgencmd") else {"returncode": None, "stdout": "", "stderr": "not installed"}
    throttle_output = "\n".join(
        part for part in (throttle["stdout"], throttle["stderr"]) if part
    ).strip()
    throttle_status = (
        "PASS" if throttle["returncode"] == 0 and "0x0" in throttle_output else "UNKNOWN"
    )

    writable = os.access(PROJECT_ROOT, os.W_OK)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "host": {
            "model": model,
            "os": os_release,
            "kernel": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "node": command_version("node"),
        },
        "storage": {
            "path": str(PROJECT_ROOT),
            "filesystem": {
                "total": usage.total,
                "used": usage.total - usage.free,
                "free": usage.free,
            },
            "writable": writable,
            "status": "PASS" if writable else "BLOCKED",
        },
        "memory": meminfo,
        "temperature_celsius": read_temperature_celsius(),
        "throttling": {
            "status": throttle_status,
            "output": throttle_output,
        },
        "software": {
            "native_packages": native_package_versions,
            "imports": python_imports,
            "commands": {
                name: shutil.which(name)
                for name in (
                    "rpicam-hello",
                    "rpicam-still",
                    "xrandr",
                    "arecord",
                    "aplay",
                    "chromium",
                    "vcgencmd",
                )
            },
            "camera_stack": {
                "rpicam": command_version("rpicam-hello"),
                "libcamera": native_package_versions.get("libcamera0.7"),
            },
        },
        "checks": {
            "camera": probe_camera(probe_capture),
            "display": probe_display(),
            "microphone": probe_audio("arecord", "microphone capture"),
            "speaker": probe_audio("aplay", "speaker playback"),
            "storage": check(
                "PASS" if writable else "BLOCKED",
                "project path is writable" if writable else "project path is not writable",
                free_bytes=usage.free,
            ),
            "python_dependencies": check(
                "PASS"
                if all(entry["error"] is None for entry in python_imports.values())
                else "BLOCKED",
                "all Phase 1/2 Python imports are available"
                if all(entry["error"] is None for entry in python_imports.values())
                else "one or more Phase 1/2 Python imports are unavailable",
            ),
        },
    }


def print_human(report: dict[str, Any]) -> None:
    host = report["host"]
    storage = report["storage"]
    print("Botanika Phase 0 environment verification")
    print(f"  Timestamp (UTC): {report['timestamp_utc']}")
    print(f"  Host: {host.get('model') or 'unknown'} / {host['machine']}")
    print(f"  OS: {host['os'].get('PRETTY_NAME', 'unknown')}")
    print(f"  Kernel: {host['kernel']}")
    print(f"  Project storage: {format_bytes(storage['free_bytes'] if 'free_bytes' in storage else storage['filesystem']['free'])} free")
    print(f"  Temperature: {report['temperature_celsius']} C")
    print()
    for name, result in report["checks"].items():
        print(f"[{result['status']}] {name}: {result['detail']}")
    print()
    print("Phase 1/2 imports:")
    for label, entry in report["software"]["imports"].items():
        version = entry["version"] or entry["error"]
        print(f"  - {label}: {version}")
    print()
    print("Use --strict for a non-zero exit when a required hardware check is blocked.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    parser.add_argument(
        "--probe-capture",
        action="store_true",
        help="attempt one temporary rpicam-still capture and delete its output",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return 1 unless camera, display, audio, storage, and imports pass",
    )
    args = parser.parse_args()
    report = collect(args.probe_capture)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)

    if not args.strict:
        return 0
    required = ("camera", "display", "microphone", "speaker", "storage", "python_dependencies")
    return 0 if all(report["checks"][name]["status"] == "PASS" for name in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
