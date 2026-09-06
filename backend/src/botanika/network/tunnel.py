"""Cloudflare Quick Tunnel lifecycle management.

The tunnel is an optional transport owned by the application runtime.  A
Quick Tunnel is intentionally short lived: cloudflared creates a random
``trycloudflare.com`` URL for the current process and forwards it to the Pi's
loopback-only FastAPI listener.  This module owns the subprocess and exposes a
small, thread-safe snapshot for the API and kiosk.

There is no shell involved.  Output is drained for the entire lifetime of the
child, including after the URL is discovered, so cloudflared cannot block on a
full pipe.  A generation number makes an old worker harmless when an operator
retries or changes mode while the previous process is still shutting down.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import io
import math
import re
import select
import subprocess
import threading
import time
from typing import Any, Callable, Deque
from urllib.parse import urlsplit


# Cloudflare Quick Tunnel hostnames are a single DNS label followed by this
# fixed suffix.  Keep this deliberately narrower than a generic URL parser so
# arbitrary URLs printed by a compromised/misconfigured child are never shown
# as an invitation URL.
_QUICK_TUNNEL_URL_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<url>https://[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.trycloudflare\.com)"
    r"(?![A-Za-z0-9_-])",
)
_LABEL_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.trycloudflare\.com$"
)
_CONNECTION_READY_MARKER = "Registered tunnel connection"


def extract_quick_tunnel_url(line: str) -> str | None:
    """Return one strict Quick Tunnel URL from a cloudflared output line.

    Only HTTPS URLs whose host is exactly ``<valid-label>.trycloudflare.com``
    are accepted.  Paths, query strings, fragments, ports, nested hosts, and
    look-alike domains are rejected.  Human log punctuation after the host is
    tolerated because cloudflared may print a trailing period or comma.
    """

    if not isinstance(line, str):
        return None
    for match in _QUICK_TUNNEL_URL_RE.finditer(line):
        candidate = match.group("url")
        suffix = line[match.end() :]
        # A strict origin cannot be followed by URL syntax.  Punctuation such
        # as ')' or ',' is ordinary log prose and is safe to ignore.
        if suffix.startswith(("/", "?", "#", ":", "%", "@", "\\")):
            continue
        # A period can be prose punctuation (``...com.``), but a period
        # followed by a label is an untrusted longer hostname.
        if suffix.startswith(".") and (
            len(suffix) > 1 and suffix[1] not in " \t\r\n,;!?)]}"
        ):
            continue
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.hostname is None
            or not _LABEL_RE.fullmatch(parsed.hostname)
        ):
            continue
        # Return the exact matched origin, not a value supplied by a URL
        # parser that might normalize a future malformed input unexpectedly.
        return candidate
    return None


# Descriptive aliases make the parser easy to discover for callers/tests.
parse_quick_tunnel_url = extract_quick_tunnel_url
parse_tunnel_url = extract_quick_tunnel_url
extract_tunnel_url = extract_quick_tunnel_url
extract_cloudflared_url = extract_quick_tunnel_url


@dataclass(frozen=True, slots=True)
class QuickTunnelStatus:
    """Immutable public snapshot of one Quick Tunnel worker generation."""

    enabled: bool
    state: str
    url: str | None
    detail: str
    error: str | None = None
    diagnostics: tuple[str, ...] = ()
    generation: int = 0
    started_at: float | None = None

    @property
    def ready(self) -> bool:
        return self.state == "ready" and bool(self.url)

    @property
    def connect_url(self) -> str | None:
        return self.url if self.ready else None

    def to_dict(self) -> dict[str, object]:
        """Serialize only bounded, non-secret transport metadata."""

        return {
            "enabled": self.enabled,
            "state": self.state,
            "transport": "cloudflare-quick-tunnel",
            "url": self.url,
            "connect_url": self.connect_url,
            "detail": self.detail,
            "error": self.error,
            "diagnostics": list(self.diagnostics),
            "generation": self.generation,
            "started_at": self.started_at,
        }

    # ``public_dict`` mirrors the AP status API and helps embedders that use a
    # common status protocol.
    public_dict = to_dict


TunnelStatus = QuickTunnelStatus


class QuickTunnelService:
    """Thread-safe, long-lived owner for an optional cloudflared process.

    ``settings`` is duck typed so focused unit tests can supply a tiny object.
    ``popen``/``process_factory`` are injectable and intentionally receive the
    same argument shape as :class:`subprocess.Popen`.
    """

    _DIAGNOSTIC_LINE_LIMIT = 512
    _DEFAULT_DIAGNOSTIC_LINES = 12

    def __init__(
        self,
        settings: object | None = None,
        *,
        port: int | None = None,
        enabled: bool | None = None,
        cloudflared_path: str | None = None,
        startup_timeout_seconds: float | None = None,
        popen: Callable[..., Any] | None = None,
        process_factory: Callable[..., Any] | None = None,
        popen_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        diagnostic_limit: int = _DEFAULT_DIAGNOSTIC_LINES,
    ) -> None:
        self.settings = settings
        self.enabled = (
            bool(enabled)
            if enabled is not None
            else bool(getattr(settings, "tunnel_enabled", False))
        )
        self.port = int(port if port is not None else getattr(settings, "port", 8000))
        self.cloudflared_path = str(
            cloudflared_path
            or getattr(settings, "cloudflared_name", None)
            or getattr(settings, "cloudflared_path", None)
            or "cloudflared"
        )
        self.startup_timeout_seconds = float(
            startup_timeout_seconds
            if startup_timeout_seconds is not None
            else getattr(settings, "tunnel_startup_timeout_seconds", 15.0)
        )
        # AppSettings permits port 0 for loopback-only ephemeral test servers.
        # A disabled transport never consumes that value, while an enabled
        # Quick Tunnel must have a concrete origin port to forward to.
        if self.port < 0 or self.port > 65535 or (self.enabled and self.port == 0):
            raise ValueError("tunnel port must be between 1 and 65535")
        if not math.isfinite(self.startup_timeout_seconds) or self.startup_timeout_seconds <= 0:
            raise ValueError("tunnel startup timeout must be positive")
        if diagnostic_limit <= 0:
            raise ValueError("diagnostic_limit must be positive")
        self._popen = popen or process_factory or popen_factory or subprocess.Popen
        self._clock = clock
        self._diagnostic_limit = diagnostic_limit
        self._lock = threading.RLock()
        self._generation = 0
        self._stop_event: threading.Event | None = None
        self._process: Any | None = None
        self._worker: threading.Thread | None = None
        self._diagnostics: Deque[str] = deque(maxlen=diagnostic_limit)
        self._status = QuickTunnelStatus(
            enabled=self.enabled,
            state="idle",
            url=None,
            detail=(
                "Cloudflare Quick Tunnel is disabled."
                if not self.enabled
                else "Cloudflare Quick Tunnel is idle."
            ),
        )

    @property
    def process(self) -> Any | None:
        """Current child for diagnostics/tests; never expose it in API data."""

        with self._lock:
            return self._process

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return self._status.ready

    def status(self) -> QuickTunnelStatus:
        with self._lock:
            return self._status

    def to_dict(self) -> dict[str, object]:
        return self.status().to_dict()

    def start(self, port: int | None = None) -> QuickTunnelStatus:
        """Start/restart the tunnel and return immediately with ``starting``."""

        if port is not None:
            try:
                candidate_port = int(port)
            except (TypeError, ValueError) as exc:
                raise ValueError("tunnel port must be between 1 and 65535") from exc
            if candidate_port <= 0 or candidate_port > 65535:
                raise ValueError("tunnel port must be between 1 and 65535")
            with self._lock:
                self.port = candidate_port

        with self._lock:
            if not self.enabled:
                self._status = QuickTunnelStatus(
                    enabled=False,
                    state="idle",
                    url=None,
                    detail="Cloudflare Quick Tunnel is disabled.",
                    generation=self._generation,
                )
                return self._status
            previous_event = self._stop_event
            previous_process = self._process
            self._generation += 1
            generation = self._generation
            if previous_event is not None:
                previous_event.set()
            self._stop_event = threading.Event()
            self._process = None
            self._worker = None
            self._diagnostics.clear()
            self._status = QuickTunnelStatus(
                enabled=True,
                state="starting",
                url=None,
                detail="Setting up secure connection…",
                generation=generation,
                started_at=self._clock(),
            )
            event = self._stop_event

        # Do not wait for an old worker from the API/mode transition path.
        # Signal it now, then let the replacement worker finish reaping it
        # before spawning the next child. This keeps retry non-blocking while
        # ensuring two cloudflared processes are never intentionally live at
        # the same time.
        self._signal_process(previous_process)
        worker = threading.Thread(
            target=self._run_generation,
            args=(generation, event, previous_process),
            name=f"botanika-cloudflared-{generation}",
            daemon=True,
        )
        with self._lock:
            if generation != self._generation or event.is_set():
                return self._status
            self._worker = worker
            worker.start()
            return self._status

    def retry(self) -> QuickTunnelStatus:
        """Restart a failed/stale child without accumulating processes."""

        return self.start()

    # Explicit transport verbs are convenient for lifecycle listeners and
    # retain the concise aliases used by focused callers.
    start_tunnel = start
    retry_tunnel = retry

    def stop(self) -> QuickTunnelStatus:
        """Stop exactly the active child and return to the idle state."""

        with self._lock:
            self._generation += 1
            event = self._stop_event
            process = self._process
            worker = self._worker
            if event is not None:
                event.set()
            self._stop_event = None
            self._process = None
            self._worker = None
            self._diagnostics.clear()
            self._status = QuickTunnelStatus(
                enabled=self.enabled,
                state="idle",
                url=None,
                detail=(
                    "Cloudflare Quick Tunnel is disabled."
                    if not self.enabled
                    else "Cloudflare Quick Tunnel stopped."
                ),
                generation=self._generation,
            )
        self._terminate_process(process)
        self._join_worker(worker)
        return self.status()

    stop_tunnel = stop

    def _run_generation(
        self,
        generation: int,
        stop_event: threading.Event,
        previous_process: Any | None = None,
    ) -> None:
        if previous_process is not None:
            self._terminate_process(previous_process)
        with self._lock:
            if generation != self._generation or stop_event.is_set():
                return
        argv = (
            self.cloudflared_path,
            "tunnel",
            "--config",
            "/dev/null",
            "--no-autoupdate",
            "--url",
            f"http://127.0.0.1:{self.port}",
        )
        try:
            process = self._popen(
                list(argv),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._fail(generation, "start_failed", f"Could not start cloudflared: {exc}")
            return

        with self._lock:
            stale = generation != self._generation or stop_event.is_set()
            if not stale:
                self._process = process
        if stale:
            self._terminate_process(process)
            return

        deadline = self._clock() + self.startup_timeout_seconds
        candidate_url: str | None = None
        connection_registered = False
        published_ready = False
        try:
            while True:
                if stop_event.is_set():
                    self._terminate_process(process)
                    return
                returncode = self._poll(process)
                if returncode is not None:
                    discovered, registered = self._drain_available(generation, process)
                    candidate_url = candidate_url or discovered
                    connection_registered = connection_registered or registered
                    if not published_ready and candidate_url and connection_registered:
                        published_ready = True
                        self._ready(generation, candidate_url)
                    if not published_ready:
                        self._fail(
                            generation,
                            "process_exit",
                            self._exit_detail(returncode, before_connection=True),
                        )
                    else:
                        self._fail(
                            generation,
                            "process_exit",
                            self._exit_detail(returncode, after_url=True),
                        )
                    return

                if not published_ready and self._clock() >= deadline:
                    self._fail(
                        generation,
                        "startup_timeout",
                        "cloudflared did not register a reachable Quick Tunnel "
                        f"within {self.startup_timeout_seconds:g} seconds.",
                    )
                    self._terminate_process(process)
                    return

                line = self._read_line(process, self._read_wait(published_ready, deadline))
                if line is _EOF:
                    # The process may still be alive while a wrapper closes its
                    # stream.  Keep polling for exit/timeout without blocking.
                    stop_event.wait(0.05)
                    continue
                if line is None:
                    continue
                self._remember_line(generation, line)
                if candidate_url is None:
                    candidate_url = extract_quick_tunnel_url(line)
                if _CONNECTION_READY_MARKER in line:
                    connection_registered = True
                if not published_ready and candidate_url and connection_registered:
                    published_ready = True
                    self._ready(generation, candidate_url)
        except Exception as exc:
            # A malformed stream or an unusual process wrapper must not leave
            # a live child behind.  The generation guard inside ``_fail``
            # keeps this diagnostic from replacing a newer retry's state.
            self._fail(generation, "worker_error", f"cloudflared output worker stopped: {exc}")
            self._terminate_process(process)
        finally:
            with self._lock:
                if generation == self._generation and self._process is process:
                    self._process = None
                    self._worker = None

    def _read_wait(self, ready: bool, deadline: float) -> float:
        if ready:
            return 0.25
        return max(0.01, min(0.25, deadline - self._clock()))

    @staticmethod
    def _poll(process: Any) -> int | None:
        try:
            return process.poll()
        except Exception:
            return None

    def _read_line(self, process: Any, wait: float) -> str | None | object:
        stream = getattr(process, "stdout", None)
        if stream is None:
            return _EOF
        try:
            readable, _, _ = select.select([stream], [], [], wait)
        except (AttributeError, OSError, ValueError, TypeError, io.UnsupportedOperation):
            # StringIO and small fake processes used by tests do not have a
            # selectable file descriptor.  Their reads are already finite.
            try:
                value = stream.readline()
            except (AttributeError, OSError, ValueError):
                return _EOF
        else:
            if not readable:
                return None
            try:
                value = stream.readline()
            except (AttributeError, OSError, ValueError):
                return _EOF
        if value == "" or value is None:
            return _EOF
        return str(value).rstrip("\r\n")

    def _drain_available(
        self,
        generation: int,
        process: Any,
    ) -> tuple[str | None, bool]:
        stream = getattr(process, "stdout", None)
        if stream is None:
            return None, False
        discovered: str | None = None
        registered = False
        while True:
            try:
                readable, _, _ = select.select([stream], [], [], 0)
            except (AttributeError, OSError, ValueError, TypeError, io.UnsupportedOperation):
                # ``StringIO``/``BytesIO`` are finite, immediately readable
                # streams used by embedders and tests.  Drain those fully;
                # never make an arbitrary non-selectable stream block here.
                if not isinstance(stream, (io.StringIO, io.BytesIO)):
                    return discovered, registered
                try:
                    value = stream.readline()
                except (AttributeError, OSError, ValueError):
                    return discovered, registered
                if not value:
                    return discovered, registered
                line = str(value).rstrip("\r\n")
                self._remember_line(generation, line)
                if discovered is None:
                    discovered = extract_quick_tunnel_url(line)
                if _CONNECTION_READY_MARKER in line:
                    registered = True
                continue
            if not readable:
                return discovered, registered
            try:
                value = stream.readline()
            except (AttributeError, OSError, ValueError):
                return discovered, registered
            if not value:
                return discovered, registered
            line = str(value).rstrip("\r\n")
            self._remember_line(generation, line)
            if discovered is None:
                discovered = extract_quick_tunnel_url(line)
            if _CONNECTION_READY_MARKER in line:
                registered = True

    def _remember_line(self, generation: int, line: str) -> None:
        bounded = _bound_diagnostic(line)
        with self._lock:
            if generation == self._generation:
                self._diagnostics.append(bounded)
                if self._status.generation == generation:
                    self._status = replace(
                        self._status,
                        diagnostics=tuple(self._diagnostics),
                    )

    def _ready(self, generation: int, url: str) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._status = QuickTunnelStatus(
                enabled=True,
                state="ready",
                url=url,
                detail="Secure connection is ready. Waiting for device…",
                diagnostics=tuple(self._diagnostics),
                generation=generation,
                started_at=self._status.started_at,
            )

    def _fail(self, generation: int, error: str, detail: str) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._status = QuickTunnelStatus(
                enabled=True,
                state="failed",
                url=None,
                detail=_bound_diagnostic(detail),
                error=error,
                diagnostics=tuple(self._diagnostics),
                generation=generation,
                started_at=self._status.started_at,
            )

    def _exit_detail(
        self,
        returncode: int,
        *,
        after_url: bool = False,
        before_connection: bool = False,
    ) -> str:
        if after_url:
            suffix = " after publishing a tunnel URL"
        elif before_connection:
            suffix = " before registering a reachable tunnel connection"
        else:
            suffix = " before publishing a tunnel URL"
        return f"cloudflared exited unexpectedly with status {returncode}{suffix}."

    @staticmethod
    def _signal_process(process: Any | None) -> None:
        if process is None:
            return
        try:
            if process.poll() is not None:
                return
        except Exception:
            pass
        try:
            process.terminate()
        except Exception:
            pass

    @staticmethod
    def _terminate_process(process: Any | None) -> None:
        if process is None:
            return
        QuickTunnelService._signal_process(process)
        try:
            process.wait(timeout=2.0)
            return
        except (subprocess.TimeoutExpired, TypeError, TimeoutError):
            pass
        except (AttributeError, OSError, ValueError):
            return
        try:
            process.kill()
        except Exception:
            return
        try:
            process.wait(timeout=2.0)
        except (subprocess.TimeoutExpired, AttributeError, OSError, ValueError, TypeError, TimeoutError):
            pass

    @staticmethod
    def _join_worker(worker: threading.Thread | None) -> None:
        if worker is None or worker is threading.current_thread():
            return
        if worker.is_alive():
            worker.join(timeout=2.5)


_EOF = object()


def _bound_diagnostic(value: str) -> str:
    value = " ".join(value.split())
    if len(value) > QuickTunnelService._DIAGNOSTIC_LINE_LIMIT:
        return value[: QuickTunnelService._DIAGNOSTIC_LINE_LIMIT - 1] + "…"
    return value


__all__ = [
    "QuickTunnelService",
    "CloudflareTunnelService",
    "CloudflaredTunnelService",
    "QuickTunnelStatus",
    "TunnelStatus",
    "extract_cloudflared_url",
    "extract_quick_tunnel_url",
    "extract_tunnel_url",
    "parse_quick_tunnel_url",
    "parse_tunnel_url",
]


CloudflareTunnelService = QuickTunnelService
CloudflaredTunnelService = QuickTunnelService
