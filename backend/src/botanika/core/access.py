"""Cloudflare Access assertion verification.

Cloudflare performs the edge login, but the origin still verifies the signed
assertion when production authentication is enabled. This prevents a caller
that can reach the loopback origin from selecting an arbitrary identity header.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request as URLRequest
from urllib.request import urlopen

import jwt

from botanika.core.settings import Settings


class AccessAuthenticationError(Exception):
    """Raised when an Access assertion is missing or invalid."""


class AccessConfigurationError(Exception):
    """Raised when production Access verification is not configured."""


class AccessVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks: dict[str, dict[str, Any]] | None = None
        self._jwks_loaded_at = 0.0
        self._lock = threading.Lock()

    def verify(self, assertion: str | None) -> dict[str, Any]:
        if not self.settings.access_required:
            return {"email": "local-development", "authenticated": False}
        if not assertion:
            raise AccessAuthenticationError("Cloudflare Access assertion is required")
        if (
            not self.settings.access_audience
            or not self.settings.access_jwks_url
            or not self.settings.access_team_domain
        ):
            raise AccessConfigurationError(
                "Cloudflare Access audience and JWKS URL must be configured"
            )
        if urlsplit(self.settings.access_jwks_url).scheme != "https":
            raise AccessConfigurationError("Cloudflare Access JWKS URL must use HTTPS")

        try:
            header = jwt.get_unverified_header(assertion)
            key_data = self._key_for_kid(header.get("kid"))
            signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
            claims = jwt.decode(
                assertion,
                signing_key,
                algorithms=["RS256"],
                audience=self.settings.access_audience,
                issuer=self.settings.access_team_domain,
                options={"require": ["exp", "iat"]},
            )
        except AccessConfigurationError:
            raise
        except Exception as exc:  # PyJWT exposes several specific exception types.
            raise AccessAuthenticationError("Cloudflare Access assertion is invalid") from exc

        email = str(claims.get("email", "")).strip().lower()
        if not email or email != self.settings.access_allowed_email:
            raise AccessAuthenticationError("Cloudflare Access identity is not allowed")
        return claims

    def _key_for_kid(self, kid: str | None) -> dict[str, Any]:
        keys = self._load_jwks()
        if kid is None:
            raise AccessAuthenticationError("Cloudflare Access assertion has no key id")
        try:
            return next(key for key in keys if key.get("kid") == kid)
        except StopIteration as exc:
            # Refresh once so a key rotation does not require a service restart.
            with self._lock:
                self._jwks = None
            keys = self._load_jwks()
            try:
                return next(key for key in keys if key.get("kid") == kid)
            except StopIteration as second_exc:
                raise AccessAuthenticationError("Cloudflare Access signing key not found") from second_exc

    def _load_jwks(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            if self._jwks is not None and now - self._jwks_loaded_at < 3600:
                return list(self._jwks.get("keys", []))
            try:
                request = URLRequest(
                    self.settings.access_jwks_url or "",
                    headers={"Accept": "application/json"},
                )
                with urlopen(request, timeout=5) as response:  # noqa: S310 - configured HTTPS URL
                    document = json.load(response)
            except Exception as exc:
                raise AccessConfigurationError("Could not load Cloudflare Access signing keys") from exc
            if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
                raise AccessConfigurationError("Cloudflare Access JWKS response is malformed")
            self._jwks = document
            self._jwks_loaded_at = now
            return list(document["keys"])
