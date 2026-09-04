"""SOLO/NETWORKED handoff and single-controller pairing state.

The Pi remains the only authority in Phase 8.  This module deliberately keeps
pairing in memory: a restart revokes every browser lease and returns the
appliance to SOLO, which is the safest recovery state for a kiosk.  The short
code is only an invitation; the longer random bearer token returned after a
successful pair is what authorizes controller requests.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import math
import secrets
import threading
import time
from typing import Any, Callable, Mapping, TypeVar
import uuid
from urllib.parse import quote


T = TypeVar("T")


class Mode(str, Enum):
    """The three externally visible application modes."""

    SOLO = "SOLO"
    NETWORKED_UNPAIRED = "NETWORKED_UNPAIRED"
    NETWORKED_PAIRED = "NETWORKED_PAIRED"


class ModeError(ValueError):
    """Base error for an invalid mode transition or pairing operation."""


class PairingError(ModeError):
    """An invitation or lease operation could not be completed."""


class PairingAuthenticationError(PairingError):
    """A controller token is missing, invalid, or no longer active."""


@dataclass(frozen=True, slots=True)
class PairingLease:
    """The private lease held by exactly one active browser controller."""

    lease_id: str
    token_digest: str
    device_name: str
    client_id: str
    paired_at: float
    expires_at: float
    last_seen_at: float

    def public_dict(self, *, now: float, health_timeout: float) -> dict[str, object]:
        healthy = self.expires_at > now and now - self.last_seen_at <= health_timeout
        return {
            "lease_id": self.lease_id,
            "device_name": self.device_name,
            "client_id": self.client_id,
            "paired_at": self.paired_at,
            "expires_at": self.expires_at,
            "last_seen_at": self.last_seen_at,
            "expires_in_seconds": max(0, int(self.expires_at - now)),
            "healthy": healthy,
        }


@dataclass(frozen=True, slots=True)
class PairingInvitation:
    """A short-lived, single-use code displayed by the Pi screen."""

    code: str
    issued_at: float
    expires_at: float

    def public_dict(self, *, now: float, url: str | None = None) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "expires_in_seconds": max(0, int(self.expires_at - now)),
            "single_use": True,
        }
        if url:
            value["url"] = url
        return value


class ModeStateMachine:
    """Thread-safe explicit mode machine with one active controller lease.

    ``settings`` is intentionally duck typed.  The application passes
    :class:`botanika.core.settings.AppSettings`, while unit tests can provide a
    small object with only the pairing values they need.
    """

    _CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

    def __init__(
        self,
        settings: object | None = None,
        *,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] | None = None,
        code_factory: Callable[[int], str] | None = None,
        network_available: Callable[[], bool] | None = None,
        recent_limit: int = 12,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._code_factory = code_factory or self._random_code
        self._network_available = network_available
        self._ttl_seconds = _positive_float(
            getattr(settings, "pairing_ttl_seconds", 300.0),
            "pairing_ttl_seconds",
        )
        self._health_timeout_seconds = _positive_float(
            getattr(settings, "controller_health_timeout_seconds", 45.0),
            "controller_health_timeout_seconds",
        )
        raw_length = getattr(settings, "pairing_code_length", 8)
        try:
            self._code_length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("pairing_code_length must be an integer") from exc
        if not 6 <= self._code_length <= 16:
            raise ValueError("pairing_code_length must be between 6 and 16")
        if recent_limit <= 0:
            raise ValueError("recent_limit must be positive")

        self._lock = threading.RLock()
        self._mode = Mode.SOLO
        self._invitation: PairingInvitation | None = None
        self._lease: PairingLease | None = None
        self._listeners: list[Callable[[Mode], None]] = []
        self._recent_results: deque[dict[str, object]] = deque(maxlen=recent_limit)
        self._transition_sequence = 0
        self._last_transition_at = self._clock()

    @property
    def mode(self) -> Mode:
        with self._lock:
            self._expire_locked()
            return self._mode

    @property
    def is_controller_paired(self) -> bool:
        return self.mode is Mode.NETWORKED_PAIRED

    @property
    def active_lease(self) -> PairingLease | None:
        with self._lock:
            self._expire_locked()
            return self._lease

    def add_mode_listener(self, listener: Callable[[Mode], None]) -> None:
        """Register a best-effort callback used by the GPIO LED adapter."""

        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    # A shorter alias is convenient for hardware adapters and external tests.
    subscribe = add_mode_listener

    def set_mode(self, target: Mode | str) -> Mode:
        """Move to an explicit mode and revoke incompatible credentials."""

        target_mode = target if isinstance(target, Mode) else Mode(str(target).upper())
        listeners: tuple[Callable[[Mode], None], ...] = ()
        with self._lock:
            self._expire_locked()
            if target_mode is Mode.SOLO:
                self._revoke_locked("return-to-solo")
                self._invitation = None
                changed = self._mode is not Mode.SOLO
                self._mode = Mode.SOLO
            elif target_mode is Mode.NETWORKED_UNPAIRED:
                if (
                    bool(getattr(self.settings, "network_enabled", False))
                    and not bool(getattr(self.settings, "tunnel_enabled", False))
                    and (
                        self._network_available is None
                        or not self._network_available()
                    )
                ):
                    raise ModeError("the private access point is not available")
                self._revoke_locked("networked-unpaired")
                self._mode = Mode.NETWORKED_UNPAIRED
                self._ensure_invitation_locked()
                changed = True
            else:
                raise ModeError(
                    "NETWORKED_PAIRED can only be entered by pairing a valid invitation"
                )
            if changed:
                listeners = self._transition_locked()
            result = self._mode
        self._notify(listeners, result)
        return result

    def toggle(self) -> Mode:
        """Software fallback for the physical mode button."""

        return self.set_mode(
            Mode.NETWORKED_UNPAIRED
            if self.mode is Mode.SOLO
            else Mode.SOLO
        )

    def enter_networked(self) -> dict[str, object]:
        self.set_mode(Mode.NETWORKED_UNPAIRED)
        return self.status()

    def return_to_solo(self) -> dict[str, object]:
        self.set_mode(Mode.SOLO)
        return self.status()

    def current_invitation(self) -> PairingInvitation | None:
        with self._lock:
            self._expire_locked()
            return self._invitation

    def pair(
        self,
        code: str,
        *,
        device_name: str = "Paired browser",
        client_id: str | None = None,
        takeover: bool = False,
    ) -> dict[str, object]:
        """Consume one invitation and return the bearer token once.

        The raw token is never retained and never appears in status output.
        Callers must keep the returned token in their browser session.
        """

        normalized_code = _clean_code(code)
        normalized_device = _clean_device_name(device_name)
        normalized_client = _clean_client_id(client_id)
        listeners: tuple[Callable[[Mode], None], ...] = ()
        with self._lock:
            self._expire_locked()
            if self._mode is Mode.SOLO:
                raise PairingError("networked mode is not active")
            if self._lease is not None:
                if not takeover:
                    raise PairingError("another controller is already paired")
                self._revoke_locked("operator-takeover")
                self._mode = Mode.NETWORKED_UNPAIRED
                self._ensure_invitation_locked()
            invitation = self._invitation
            if invitation is None:
                raise PairingError("no pairing invitation is available")
            if not hmac.compare_digest(normalized_code, invitation.code):
                raise PairingError("pairing code is invalid")
            now = self._clock()
            if now >= invitation.expires_at:
                self._invitation = None
                self._ensure_invitation_locked()
                raise PairingError("pairing code has expired")
            raw_token = str(self._token_factory())
            if len(raw_token.strip()) < 16:
                raise PairingError("could not create a controller token")
            lease = PairingLease(
                lease_id=uuid.uuid4().hex,
                token_digest=_digest(raw_token),
                device_name=normalized_device,
                client_id=normalized_client,
                paired_at=now,
                expires_at=now + self._ttl_seconds,
                last_seen_at=now,
            )
            self._lease = lease
            self._invitation = None  # single use
            self._mode = Mode.NETWORKED_PAIRED
            listeners = self._transition_locked()
            result = {
                "mode": self._mode.value,
                "session_token": raw_token,
                "expires_at": lease.expires_at,
                "lease": lease.public_dict(
                    now=now,
                    health_timeout=self._health_timeout_seconds,
                ),
                "status": self._status_locked(now=now),
            }
        self._notify(listeners, Mode.NETWORKED_PAIRED)
        return result

    def takeover_controller(self) -> dict[str, object]:
        """Revoke the current browser and show a fresh invitation."""

        listeners: tuple[Callable[[Mode], None], ...] = ()
        with self._lock:
            self._expire_locked()
            if self._mode is Mode.SOLO:
                self._mode = Mode.NETWORKED_UNPAIRED
            else:
                self._revoke_locked("operator-takeover")
                self._mode = Mode.NETWORKED_UNPAIRED
            self._ensure_invitation_locked(force=True)
            listeners = self._transition_locked()
            result = self._status_locked(now=self._clock())
        self._notify(listeners, Mode.NETWORKED_UNPAIRED)
        return result

    def authenticate(self, token: str | None) -> PairingLease:
        """Validate a controller bearer token and refresh its health timestamp."""

        raw_token = _extract_token(token)
        listeners: tuple[Callable[[Mode], None]] = ()
        with self._lock:
            self._expire_locked()
            lease = self._lease
            if self._mode is not Mode.NETWORKED_PAIRED or lease is None:
                raise PairingAuthenticationError("no active paired controller")
            if not hmac.compare_digest(lease.token_digest, _digest(raw_token)):
                raise PairingAuthenticationError("controller token is invalid")
            now = self._clock()
            self._lease = PairingLease(
                lease_id=lease.lease_id,
                token_digest=lease.token_digest,
                device_name=lease.device_name,
                client_id=lease.client_id,
                paired_at=lease.paired_at,
                expires_at=lease.expires_at,
                last_seen_at=now,
            )
            result = self._lease
        self._notify(listeners, self._mode)
        return result

    def commit_for_lease(self, lease_id: str, action: Callable[[], T]) -> T:
        """Run one authoritative commit only while the same lease is active.

        Holding the mode lock across the small commit prevents takeover, expiry,
        or a mode change from landing between the final lease check and publish.
        Slow classifier work happens before this boundary.
        """

        with self._lock:
            self._expire_locked()
            lease = self._lease
            if (
                self._mode is not Mode.NETWORKED_PAIRED
                or lease is None
                or lease.lease_id != lease_id
            ):
                raise PairingAuthenticationError("controller lease is no longer active")
            return action()

    def heartbeat(self, token: str | None) -> dict[str, object]:
        self.authenticate(token)
        return self.status()

    def disconnect(self, token: str | None) -> dict[str, object]:
        lease = self.authenticate(token)
        listeners: tuple[Callable[[Mode], None]] = ()
        with self._lock:
            # authenticate refreshed the lease; compare the lease ID so a
            # concurrent takeover cannot be disconnected by an old request.
            if self._lease is None or self._lease.lease_id != lease.lease_id:
                raise PairingAuthenticationError("controller lease is no longer active")
            self._revoke_locked("controller-disconnect")
            self._mode = Mode.NETWORKED_UNPAIRED
            self._ensure_invitation_locked()
            listeners = self._transition_locked()
            result = self._status_locked(now=self._clock())
        self._notify(listeners, Mode.NETWORKED_UNPAIRED)
        return result

    def revoke(self, reason: str = "operator-revocation") -> dict[str, object]:
        """Revoke the controller without requiring its token."""

        return self.takeover_controller() if reason == "operator-takeover" else self._revoke_to_unpaired(reason)

    def record_result(self, result: Mapping[str, Any] | object) -> None:
        """Keep a small redacted result log for the Pi status console."""

        if isinstance(result, Mapping):
            value = dict(result)
        else:
            value = {
                "request_id": getattr(result, "request_id", None),
                "result": getattr(getattr(result, "result", None), "to_dict", lambda: {})(),
            }
        nested = value.get("result") if isinstance(value.get("result"), Mapping) else value
        with self._lock:
            self._recent_results.append(
                {
                    "timestamp": self._clock(),
                    "request_id": str(value.get("request_id") or "controller-scan"),
                    "status": str(nested.get("status") or "unknown"),
                    "common_name": nested.get("common_name"),
                    "scientific_name": nested.get("scientific_name"),
                    "confidence": nested.get("confidence"),
                    "category": nested.get("category"),
                }
            )

    def status(
        self,
        *,
        network: Mapping[str, Any] | None = None,
        scan: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            self._expire_locked()
            return self._status_locked(now=self._clock(), network=network, scan=scan)

    def _status_locked(
        self,
        *,
        now: float,
        network: Mapping[str, Any] | None = None,
        scan: Mapping[str, Any] | None = None,
    ) -> dict[str, object]:
        settings = self.settings
        invitation = self._invitation
        lease = self._lease
        network_value: dict[str, object] = dict(network or {})
        ap_snapshot = network_value.get("status")
        ap_available = (
            bool(ap_snapshot.get("available", False))
            if isinstance(ap_snapshot, Mapping)
            else bool(network_value.get("available", False))
        )
        access_point = {
            "ssid": getattr(settings, "access_point_ssid", "Botanika"),
            "address": getattr(settings, "access_point_address", "192.168.50.1"),
            "hostname": getattr(settings, "local_hostname", "botanika.home.arpa"),
            "enabled": bool(getattr(settings, "network_enabled", False)),
            "available": ap_available,
        }
        tunnel_value = network_value.get("tunnel")
        tunnel = dict(tunnel_value) if isinstance(tunnel_value, Mapping) else {}
        tunnel_ready = tunnel.get("state") == "ready" and bool(
            tunnel.get("connect_url") or tunnel.get("url")
        )
        tunnel_url = (
            str(tunnel.get("connect_url") or tunnel.get("url"))
            if tunnel_ready
            else None
        )
        pairing_url = tunnel_url or getattr(settings, "pairing_url", None)
        pairing = (
            invitation.public_dict(
                now=now,
                url=pairing_url,
            )
            if self._mode is Mode.NETWORKED_UNPAIRED and invitation is not None
            else None
        )
        if pairing is not None and tunnel_url:
            pairing["deep_link"] = _pairing_deep_link(tunnel_url, invitation.code)
        return {
            "mode": self._mode.value,
            "state": self._mode.value,
            "transition_sequence": self._transition_sequence,
            "last_transition_at": self._last_transition_at,
            "access_point": access_point,
            "network": network_value,
            "tunnel": tunnel,
            "transport": (
                "cloudflare-quick-tunnel"
                if tunnel_ready
                else "private-access-point"
                if access_point["available"]
                else "loopback"
            ),
            "pairing": pairing,
            # Flat aliases make the status easy to consume from a tiny kiosk
            # script while the nested object remains the typed UI contract.
            "pairing_code": invitation.code if pairing is not None else None,
            "pairing_expires_at": invitation.expires_at if pairing is not None else None,
            "controller": (
                lease.public_dict(
                    now=now,
                    health_timeout=self._health_timeout_seconds,
                )
                if lease is not None
                else None
            ),
            "connection": {
                "healthy": bool(
                    lease is not None
                    and lease.expires_at > now
                    and now - lease.last_seen_at <= self._health_timeout_seconds
                ),
                "last_seen_at": lease.last_seen_at if lease is not None else None,
                "expires_at": lease.expires_at if lease is not None else None,
                "stale_after_seconds": self._health_timeout_seconds,
            },
            "scan": dict(scan or {}),
            "recent_results": list(self._recent_results),
            "controller_count": 1 if lease is not None else 0,
        }

    def _ensure_invitation_locked(self, *, force: bool = False) -> PairingInvitation:
        now = self._clock()
        if not force and self._invitation is not None and self._invitation.expires_at > now:
            return self._invitation
        code = _clean_code(self._code_factory(self._code_length))
        if len(code) != self._code_length:
            raise PairingError("pairing code factory returned the wrong length")
        invitation = PairingInvitation(
            code=code,
            issued_at=now,
            expires_at=now + self._ttl_seconds,
        )
        self._invitation = invitation
        return invitation

    def _expire_locked(self) -> None:
        now = self._clock()
        if self._invitation is not None and now >= self._invitation.expires_at:
            self._invitation = None
            if self._mode is Mode.NETWORKED_UNPAIRED:
                self._ensure_invitation_locked()
        if self._lease is not None and now >= self._lease.expires_at:
            self._revoke_locked("lease-expired")
            if self._mode is Mode.NETWORKED_PAIRED:
                self._mode = Mode.NETWORKED_UNPAIRED
                self._ensure_invitation_locked()
                listeners = self._transition_locked()
            else:
                listeners = ()
            self._notify(listeners, self._mode)

    def _revoke_to_unpaired(self, reason: str) -> dict[str, object]:
        listeners: tuple[Callable[[Mode], None], ...] = ()
        with self._lock:
            previous_mode = self._mode
            had_lease = self._lease is not None
            self._revoke_locked(reason)
            if self._mode is not Mode.SOLO:
                self._mode = Mode.NETWORKED_UNPAIRED
                self._ensure_invitation_locked()
            if had_lease or previous_mode is not self._mode:
                listeners = self._transition_locked()
            result = self._status_locked(now=self._clock())
            result_mode = self._mode
        self._notify(listeners, result_mode)
        return result

    def _revoke_locked(self, _reason: str) -> None:
        self._lease = None

    def _transition_locked(self) -> tuple[Callable[[Mode], None], ...]:
        self._transition_sequence += 1
        self._last_transition_at = self._clock()
        return tuple(self._listeners)

    @staticmethod
    def _random_code(length: int) -> str:
        return "".join(secrets.choice(ModeStateMachine._CODE_ALPHABET) for _ in range(length))

    @staticmethod
    def _notify(listeners: tuple[Callable[[Mode], None], ...], mode: Mode) -> None:
        for listener in listeners:
            try:
                listener(mode)
            except Exception:
                # A GPIO failure must not break the API transition itself.
                continue


# Descriptive aliases keep imports readable for callers that think in terms of
# a service rather than a finite-state machine.
ModeService = ModeStateMachine
ModeController = ModeStateMachine


def _pairing_deep_link(url: str, code: str) -> str:
    """Build the QR target without persisting or returning the code remotely."""

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}pair={quote(code, safe='')}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _extract_token(value: str | None) -> str:
    if not value:
        raise PairingAuthenticationError("controller token is required")
    token = str(value).strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if len(token) < 16:
        raise PairingAuthenticationError("controller token is invalid")
    return token


def _clean_code(value: object) -> str:
    code = str(value or "").strip().upper().replace("-", "")
    if not code or any(character not in ModeStateMachine._CODE_ALPHABET for character in code):
        raise PairingError("pairing code is malformed")
    return code


def _clean_device_name(value: object) -> str:
    name = " ".join(str(value or "Paired browser").strip().split())
    if not name:
        name = "Paired browser"
    if len(name) > 80:
        raise PairingError("device name must be at most 80 characters")
    return name


def _clean_client_id(value: object) -> str:
    client = " ".join(str(value or "browser").strip().split())
    if not client:
        client = "browser"
    if len(client) > 120:
        raise PairingError("client ID must be at most 120 characters")
    return client


def _positive_float(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a positive number")
    return result
