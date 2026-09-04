"""Request trust boundaries for the Pi operator and paired controller."""

from __future__ import annotations

from copy import deepcopy
import ipaddress
import re
from typing import Any

from fastapi import Request

from botanika.core.errors import ControllerAuthorizationError
from botanika.mode import PairingAuthenticationError, PairingLease


CONTROLLER_COOKIE = "botanika_controller"
_CLOUDFLARE_RAY_RE = re.compile(r"^[0-9A-Fa-f]{16,64}(?:-[A-Za-z]{3,8})?$")


def is_cloudflare_proxy_request(request: Request) -> bool:
    """Recognize a Cloudflare-proxied request without trusting X-Forwarded-For.

    cloudflared forwards the visitor address in ``CF-Connecting-IP`` and adds
    a ``CF-Ray`` identifier.  Both headers must have valid shapes.  A forged
    or partial marker is ignored, which preserves ordinary Pi loopback access
    while never granting an external caller operator privileges.
    """

    connecting_ip = request.headers.get("CF-Connecting-IP", "").strip()
    ray = request.headers.get("CF-Ray", "").strip()
    if not connecting_ip or not ray or "," in connecting_ip or "," in ray:
        return False
    try:
        parsed = ipaddress.ip_address(connecting_ip)
    except (TypeError, ValueError):
        return False
    if parsed.is_unspecified or parsed.is_multicast:
        return False
    return _CLOUDFLARE_RAY_RE.fullmatch(ray) is not None


def is_local_operator(request: Request) -> bool:
    """Return true for an unmarked Pi loopback peer, never a tunnel caller."""

    if is_cloudflare_proxy_request(request):
        return False

    client = request.client
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except (TypeError, ValueError):
        return False


def controller_token(request: Request) -> str | None:
    """Read the controller credential from API headers or the same-site cookie."""

    return (
        request.headers.get("X-Botanika-Controller-Token")
        or request.headers.get("Authorization")
        or request.cookies.get(CONTROLLER_COOKIE)
    )


def require_local_operator(request: Request) -> None:
    if not is_local_operator(request):
        raise ControllerAuthorizationError("this operation is available only on the Pi")


def require_controller(runtime: Any, request: Request) -> PairingLease:
    try:
        return runtime.mode.authenticate(controller_token(request))
    except PairingAuthenticationError as exc:
        raise ControllerAuthorizationError(str(exc)) from exc


def require_local_or_controller(runtime: Any, request: Request) -> PairingLease | None:
    if is_local_operator(request):
        return None
    return require_controller(runtime, request)


def mode_status_for_request(
    status: dict[str, object],
    request: Request,
) -> dict[str, object]:
    """Add the caller role and keep invitation secrets on the Pi screen."""

    value = deepcopy(status)
    local = is_local_operator(request)
    value["client_role"] = "operator" if local else "remote"
    if local:
        return value
    pairing = value.get("pairing")
    if isinstance(pairing, dict):
        pairing.pop("code", None)
        # The operator-only QR target embeds the one-time code as ``?pair=``.
        pairing.pop("deep_link", None)
    value["pairing_code"] = None
    value.pop("pairing_deep_link", None)
    tunnel = value.get("tunnel")
    if isinstance(tunnel, dict):
        tunnel.pop("diagnostics", None)
    network = value.get("network")
    if isinstance(network, dict):
        nested_tunnel = network.get("tunnel")
        if isinstance(nested_tunnel, dict):
            nested_tunnel.pop("diagnostics", None)
    return value


__all__ = [
    "CONTROLLER_COOKIE",
    "controller_token",
    "is_cloudflare_proxy_request",
    "is_local_operator",
    "mode_status_for_request",
    "require_controller",
    "require_local_operator",
    "require_local_or_controller",
]
