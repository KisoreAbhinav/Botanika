#!/usr/bin/env python3
"""Prepare and run Botanika, then open it full-screen on the Pi display."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Mapping
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
PYTHON_REQUIREMENTS = (
    PROJECT_ROOT / "config" / "environments" / "phase0-python-requirements.txt",
    PROJECT_ROOT / "config" / "environments" / "phase5-python-requirements.txt",
)
MANAGED_BACKEND_SERVICE = "botanika-backend.service"
BACKEND_ENTRYPOINT = PROJECT_ROOT / "tools" / "run_api.py"


def run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> None:
    print(f"[Botanika] Running: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def file_digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_marker(path: Path, value: str) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")


def marker_matches(path: Path, value: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").strip() == value
    except OSError:
        return False


def ensure_python_environment(*, skip_install: bool) -> Path:
    if skip_install:
        if not PROJECT_PYTHON.is_file():
            raise SystemExit(
                "[Botanika] .venv is missing. Run once without --skip-install."
            )
        return PROJECT_PYTHON

    if not PROJECT_PYTHON.is_file():
        print("[Botanika] Creating the Python environment...", flush=True)
        try:
            run(
                [
                    sys.executable,
                    "-m",
                    "venv",
                    "--system-site-packages",
                    str(PROJECT_ROOT / ".venv"),
                ]
            )
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                "[Botanika] Could not create .venv. Install python3-venv, "
                "then run this launcher again."
            ) from exc

    requirements_hash = file_digest(PYTHON_REQUIREMENTS)
    marker = PROJECT_ROOT / ".venv" / ".botanika-requirements.sha256"
    if not marker_matches(marker, requirements_hash):
        print(
            "[Botanika] Installing Python dependencies "
            "(first run or requirements changed)...",
            flush=True,
        )
        for requirements in PYTHON_REQUIREMENTS:
            run(
                [
                    str(PROJECT_PYTHON),
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements),
                ]
            )
        write_marker(marker, requirements_hash)
    else:
        print("[Botanika] Python dependencies are ready.", flush=True)
    return PROJECT_PYTHON


def ensure_frontend(*, skip_install: bool, skip_build: bool) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit(
            "[Botanika] npm is required. Install Node.js/npm, then run this launcher again."
        )

    node_modules = FRONTEND_ROOT / "node_modules"
    package_files = (
        FRONTEND_ROOT / "package.json",
        FRONTEND_ROOT / "package-lock.json",
    )
    package_hash = file_digest(package_files)
    marker = node_modules / ".botanika-packages.sha256"
    needs_install = not node_modules.is_dir() or not marker_matches(marker, package_hash)

    # Existing checkouts predate the marker. Validate their dependency tree so
    # the first launcher run does not reinstall an already-correct node_modules.
    if node_modules.is_dir() and not marker.exists():
        dependency_check = subprocess.run(
            [npm, "ls", "--depth=0"],
            cwd=FRONTEND_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if dependency_check.returncode == 0:
            write_marker(marker, package_hash)
            needs_install = False

    if needs_install and skip_install:
        raise SystemExit(
            "[Botanika] Frontend dependencies are missing or changed. "
            "Run once without --skip-install."
        )
    if needs_install:
        print("[Botanika] Installing frontend dependencies...", flush=True)
        run([npm, "ci"], cwd=FRONTEND_ROOT)
        write_marker(marker, package_hash)
    else:
        print("[Botanika] Frontend dependencies are ready.", flush=True)

    if skip_build:
        if not (FRONTEND_ROOT / "dist" / "index.html").is_file():
            raise SystemExit(
                "[Botanika] The frontend has not been built. "
                "Run once without --skip-build."
            )
    else:
        print("[Botanika] Building the latest interface...", flush=True)
        run([npm, "run", "build"], cwd=FRONTEND_ROOT)


def backend_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the fresh backend environment with Quick Tunnel QR enabled."""

    environment = dict(os.environ if environ is None else environ)
    configured_path = environment.get("BOTANIKA_CLOUDFLARED_PATH", "").strip()
    cloudflared = configured_path if configured_path and Path(configured_path).is_file() else None
    cloudflared = cloudflared or shutil.which(
        "cloudflared",
        path=environment.get("PATH"),
    )
    if cloudflared is None:
        raise SystemExit(
            "[Botanika] cloudflared is required for the phone QR code but was not found."
        )

    environment["BOTANIKA_TUNNEL_ENABLED"] = "true"
    environment["BOTANIKA_CLOUDFLARED_PATH"] = cloudflared
    environment.setdefault("BOTANIKA_NETWORK_ENABLED", "false")
    environment.setdefault("BOTANIKA_HOST", "127.0.0.1")
    environment.setdefault("BOTANIKA_LOOPBACK_ONLY", "true")
    print(
        f"[Botanika] Phone QR enabled through Quick Tunnel ({cloudflared}).",
        flush=True,
    )
    return environment


def backend_port(
    arguments: list[str],
    environment: Mapping[str, str] | None = None,
) -> int:
    values = os.environ if environment is None else environment
    raw_port = values.get("BOTANIKA_PORT", "8000")
    for index, argument in enumerate(arguments):
        if argument == "--port" and index + 1 < len(arguments):
            raw_port = arguments[index + 1]
        elif argument.startswith("--port="):
            raw_port = argument.split("=", 1)[1]
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise SystemExit(f"[Botanika] Invalid API port: {raw_port!r}") from exc
    if not 1 <= port <= 65535:
        raise SystemExit(
            "[Botanika] The kiosk launcher needs a fixed port from 1 to 65535."
        )
    return port


def existing_botanika(ready_url: str) -> bool:
    """Return true only when the target port already serves Botanika readiness."""

    try:
        with urlopen(ready_url, timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False
    capabilities = payload.get("capabilities")
    return (
        payload.get("status") in {"ready", "degraded"}
        and isinstance(capabilities, dict)
        and "storage" in capabilities
        and "camera" in capabilities
    )


def managed_backend_is_installed() -> bool:
    """Return whether this Pi has the production service configuration."""

    if shutil.which("systemctl") is None:
        return False
    result = subprocess.run(
        ["systemctl", "show", MANAGED_BACKEND_SERVICE, "--property=LoadState", "--value"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "loaded"


def wait_for_backend_to_stop(ready_url: str, *, timeout: float = 10.0) -> None:
    """Wait until the old readiness endpoint is no longer answering."""

    deadline = time.monotonic() + max(0.1, timeout)
    while time.monotonic() < deadline:
        if not existing_botanika(ready_url):
            return
        time.sleep(0.2)
    raise SystemExit(
        "[Botanika] The old backend is still answering on the requested port; "
        "refusing to start a second copy."
    )


def stop_managed_backend(ready_url: str) -> None:
    """Stop the installed service before running the current checkout."""

    if not managed_backend_is_active():
        return
    print(
        f"[Botanika] Stopping managed service {MANAGED_BACKEND_SERVICE}...",
        flush=True,
    )
    result = subprocess.run(
        ["sudo", "-n", "systemctl", "stop", MANAGED_BACKEND_SERVICE],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"[Botanika] Could not stop {MANAGED_BACKEND_SERVICE}. "
            f"Run `sudo systemctl stop {MANAGED_BACKEND_SERVICE}` once, then retry."
        )
    wait_for_backend_to_stop(ready_url)


def managed_backend_is_active() -> bool:
    """Return whether systemd currently has the production backend active."""

    if shutil.which("systemctl") is None:
        return False
    result = subprocess.run(
        ["systemctl", "is-active", MANAGED_BACKEND_SERVICE],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "active"


def _process_arguments(pid: int) -> list[str] | None:
    """Read a Linux process command line without trusting a broad name match."""

    try:
        raw_arguments = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return [item.decode("utf-8", errors="replace") for item in raw_arguments.split(b"\0") if item]


def _process_environment(pid: int) -> dict[str, str]:
    try:
        raw_environment = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    environment: dict[str, str] = {}
    for item in raw_environment.split(b"\0"):
        key, separator, value = item.partition(b"=")
        if separator:
            environment[key.decode("utf-8", errors="replace")] = value.decode(
                "utf-8", errors="replace"
            )
    return environment


def _process_backend_port(arguments: list[str], environment: dict[str, str]) -> int | None:
    raw_port = environment.get("BOTANIKA_PORT", "8000")
    for index, argument in enumerate(arguments):
        if argument == "--port":
            if index + 1 >= len(arguments):
                return None
            raw_port = arguments[index + 1]
        elif argument.startswith("--port="):
            raw_port = argument.split("=", 1)[1]
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def local_backend_pids(port: int) -> list[int]:
    """Find only run_api.py processes belonging to this checkout and port."""

    pids: list[int] = []
    entrypoint = BACKEND_ENTRYPOINT.resolve()
    for process_dir in Path("/proc").glob("[0-9]*"):
        try:
            pid = int(process_dir.name)
        except ValueError:
            continue
        arguments = _process_arguments(pid)
        if not arguments:
            continue
        process_cwd: Path | None = None
        try:
            process_cwd = Path(os.readlink(process_dir / "cwd"))
        except OSError:
            pass
        entrypoint_matches = False
        for argument in arguments[1:]:
            candidate = Path(argument)
            if not candidate.is_absolute() and process_cwd is not None:
                candidate = process_cwd / candidate
            try:
                if candidate.resolve() == entrypoint:
                    entrypoint_matches = True
                    break
            except OSError:
                continue
        if entrypoint_matches and _process_backend_port(arguments, _process_environment(pid)) == port:
            pids.append(pid)
    return pids


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def stop_local_backends(port: int, *, timeout: float = 8.0) -> None:
    """Gracefully stop old local backends owned by this checkout."""

    pids = local_backend_pids(port)
    if not pids:
        return
    print(
        f"[Botanika] Stopping old local backend process(es): {', '.join(map(str, pids))}",
        flush=True,
    )
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue

    deadline = time.monotonic() + max(0.1, timeout)
    remaining = [pid for pid in pids if process_is_alive(pid)]
    while remaining and time.monotonic() < deadline:
        time.sleep(0.2)
        remaining = [pid for pid in remaining if process_is_alive(pid)]
    if not remaining:
        return

    print(
        f"[Botanika] Old backend did not stop cleanly; terminating: {', '.join(map(str, remaining))}",
        file=sys.stderr,
        flush=True,
    )
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    still_alive = [pid for pid in remaining if process_is_alive(pid)]
    if still_alive:
        raise SystemExit(
            "[Botanika] Could not stop the old local backend process(es): "
            + ", ".join(map(str, still_alive))
        )


def frontend_build_token(index_path: Path) -> str:
    """Return a short identity for the exact Vite shell built by this launcher."""

    return hashlib.sha256(index_path.read_bytes()).hexdigest()[:16]


def cache_busted_url(app_url: str, build_token: str) -> str:
    """Give every built interface a distinct kiosk navigation URL."""

    separator = "&" if "?" in app_url else "?"
    return f"{app_url}{separator}build={build_token}"


def configure_pi_display() -> None:
    """Find the logged-in Pi desktop when launched from an IDE or SSH shell."""

    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return
    runtime_dir = Path(f"/run/user/{os.getuid()}")
    wayland_socket = runtime_dir / "wayland-0"
    if wayland_socket.exists():
        os.environ.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
        os.environ["WAYLAND_DISPLAY"] = wayland_socket.name
        print(f"[Botanika] Using Pi Wayland display {wayland_socket}.", flush=True)
        return
    if Path("/tmp/.X11-unix/X0").exists():
        os.environ["DISPLAY"] = ":0"
        xauthority = Path.home() / ".Xauthority"
        if xauthority.exists():
            os.environ.setdefault("XAUTHORITY", str(xauthority))
        print("[Botanika] Using Pi X11 display :0.", flush=True)
        return
    raise SystemExit(
        "[Botanika] No Pi desktop display was found. Log in to the graphical "
        "desktop, then run this launcher from its terminal."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Unknown options are passed to tools/run_api.py "
            "(for example: --port 8001)."
        ),
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="do not create .venv or install changed Python/npm dependencies",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="reuse the existing frontend build",
    )
    parser.add_argument(
        "--no-kiosk",
        action="store_true",
        help="start the API without opening Chromium",
    )
    parser.add_argument(
        "--dry-run-kiosk",
        action="store_true",
        help="verify startup and print the Chromium command without opening it",
    )
    return parser


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_kiosk(command: list[str], api: subprocess.Popen[bytes]) -> int:
    """Keep the browser and API together, and fail fast if the API exits."""

    kiosk = subprocess.Popen(command, cwd=PROJECT_ROOT, start_new_session=True)
    try:
        while True:
            kiosk_status = kiosk.poll()
            if kiosk_status is not None:
                return kiosk_status
            api_status = api.poll()
            if api_status is not None:
                print(
                    f"[Botanika] The backend stopped with exit code {api_status}; "
                    "closing the kiosk launcher.",
                    file=sys.stderr,
                    flush=True,
                )
                return api_status or 1
            time.sleep(0.2)
    finally:
        if kiosk.poll() is None:
            os.killpg(kiosk.pid, signal.SIGTERM)
            try:
                kiosk.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(kiosk.pid, signal.SIGKILL)
                kiosk.wait()


def main(argv: list[str] | None = None) -> int:
    launcher_args, backend_args = build_parser().parse_known_args(argv)
    runtime_python = ensure_python_environment(skip_install=launcher_args.skip_install)
    ensure_frontend(
        skip_install=launcher_args.skip_install,
        skip_build=launcher_args.skip_build,
    )
    api_environment = backend_environment()
    port = backend_port(backend_args, api_environment)
    app_url = f"http://127.0.0.1:{port}/"
    ready_url = f"{app_url}api/v1/health/ready"
    index_path = FRONTEND_ROOT / "dist" / "index.html"
    build_token = frontend_build_token(index_path)
    kiosk_app_url = cache_busted_url(app_url, build_token)

    if not launcher_args.no_kiosk and not launcher_args.dry_run_kiosk:
        configure_pi_display()
        if shutil.which("chromium") is None and shutil.which("chromium-browser") is None:
            raise SystemExit(
                "[Botanika] Chromium is required. Install it, then run this launcher again."
            )

    kiosk_command = [
        str(runtime_python),
        str(PROJECT_ROOT / "tools" / "launch_kiosk.py"),
        "--ready-url",
        ready_url,
        "--app-url",
        kiosk_app_url,
    ]
    if launcher_args.dry_run_kiosk:
        kiosk_command.append("--dry-run")

    managed_backend = port == 8000 and managed_backend_is_installed()
    if managed_backend:
        stop_managed_backend(ready_url)
    stop_local_backends(port)

    wait_for_backend_to_stop(ready_url)

    api = subprocess.Popen(
        [str(runtime_python), str(BACKEND_ENTRYPOINT), *backend_args],
        cwd=PROJECT_ROOT,
        env=api_environment,
    )
    try:
        print(f"[Botanika] Starting at {app_url}", flush=True)
        if launcher_args.no_kiosk:
            return api.wait()

        return run_kiosk(kiosk_command, api)
    except KeyboardInterrupt:
        return 130
    finally:
        stop_process(api)


def raise_keyboard_interrupt() -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda _signum, _frame: raise_keyboard_interrupt())
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(
            f"[Botanika] Setup command failed with exit code {exc.returncode}. "
            "Fix the message above, then run the launcher again.",
            file=sys.stderr,
        )
        raise SystemExit(exc.returncode) from None
