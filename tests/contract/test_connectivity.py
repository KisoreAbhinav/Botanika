from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import httpx
import jwt
import pytest
from PIL import Image
from cryptography.hazmat.primitives.asymmetric import rsa

from botanika.api.status import StatusHub
from botanika.core.access import AccessAuthenticationError, AccessVerifier
from botanika.core.settings import Settings
from botanika.main import create_app


def make_image(format_name: str = "JPEG") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 48), (46, 105, 67)).save(buffer, format=format_name)
    return buffer.getvalue()


def make_settings(tmp_path: Path) -> Settings:
    """Use the real checked-in UI and an isolated generated temp directory."""
    return Settings(
        frontend_dir=Path(__file__).parents[2] / "frontend",
        temporary_dir=tmp_path / "temp",
        access_required=False,
        csrf_required=False,
    )


@pytest.fixture
async def client(tmp_path: Path):
    app = create_app(make_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as test_client:
            yield test_client


async def test_health_and_placeholder_are_ready(client: httpx.AsyncClient) -> None:
    live = await client.get("/api/v1/health/live")
    ready = await client.get("/api/v1/health/ready")
    page = await client.get("/")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert "Botanika" in page.text


async def test_receipt_reports_decoded_image_and_does_not_retain_bytes(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    image = make_image()
    response = await client.post(
        "/api/v1/connectivity/receipt",
        headers={"Idempotency-Key": "test-crop-1"},
        files={"image": ("anything.jpg", image, "image/jpeg")},
        data={"metadata": '{"client_type":"phone"}'},
    )
    ready = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["width"] == 64
    assert body["height"] == 48
    assert body["mime_type"] == "image/jpeg"
    assert body["byte_count"] == len(image)
    assert body["content_hash"] == hashlib.sha256(image).hexdigest()
    assert ready.json()["temporary_file_count"] == 0
    assert ready.json()["idempotency_cache_entries"] == 1
    assert list((tmp_path / "temp").iterdir()) == []


async def test_duplicate_retry_is_idempotent_and_conflicting_bytes_are_rejected(
    client: httpx.AsyncClient,
) -> None:
    image = make_image()
    first = await client.post(
        "/api/v1/connectivity/receipt",
        headers={"Idempotency-Key": "same-request"},
        files={"image": ("crop.jpg", image, "image/jpeg")},
    )
    second = await client.post(
        "/api/v1/connectivity/receipt",
        headers={"Idempotency-Key": "same-request"},
        files={"image": ("crop.jpg", image, "image/jpeg")},
    )
    conflict = await client.post(
        "/api/v1/connectivity/receipt",
        headers={"Idempotency-Key": "same-request"},
        files={"image": ("crop.jpg", make_image("WEBP"), "image/webp")},
    )

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "idempotency_conflict"


async def test_declared_image_must_match_magic_and_decoder(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/connectivity/receipt",
        files={"image": ("fake.jpg", b"not an image", "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "magic_mismatch"


async def test_production_security_and_csrf_gates(tmp_path: Path) -> None:
    production_settings = Settings(
        frontend_dir=Path(__file__).parents[2] / "frontend",
        temporary_dir=tmp_path / "production-temp",
        access_required=True,
        csrf_required=True,
        access_team_domain="https://example.cloudflareaccess.com",
        access_jwks_url="https://example.cloudflareaccess.com/cdn-cgi/access/certs",
        access_audience="test-audience",
    )
    app = create_app(production_settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://botanika.example.com"
        ) as client:
            csrf = await client.get("/api/v1/security/csrf")
            response = await client.post(
                "/api/v1/connectivity/receipt",
                files={"image": ("crop.jpg", make_image(), "image/jpeg")},
            )

    assert csrf.status_code == 200
    assert csrf.cookies.get("botanika_csrf")
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "access_required"


async def test_rate_limit_and_image_boundary_are_enforced(tmp_path: Path) -> None:
    boundary_app = create_app(
        replace(make_settings(tmp_path), max_image_bytes=16, max_request_bytes=4096)
    )
    async with boundary_app.router.lifespan_context(boundary_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=boundary_app), base_url="http://testserver"
        ) as client:
            too_large = await client.post(
                "/api/v1/connectivity/receipt",
                files={"image": ("crop.jpg", b"x" * 17, "image/jpeg")},
            )

    rate_app = create_app(replace(make_settings(tmp_path), receipt_rate_limit=1))
    async with rate_app.router.lifespan_context(rate_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rate_app), base_url="http://testserver"
        ) as client:
            first = await client.post(
                "/api/v1/connectivity/receipt",
                files={"image": ("crop.jpg", make_image(), "image/jpeg")},
            )
            second = await client.post(
                "/api/v1/connectivity/receipt",
                files={"image": ("crop.jpg", make_image(), "image/jpeg")},
            )

    assert too_large.status_code == 422
    assert too_large.json()["detail"]["error"] == "image_too_large"
    assert first.status_code == 200
    assert second.status_code == 429


async def test_request_envelope_limit_is_separate_from_image_limit(tmp_path: Path) -> None:
    app = create_app(
        replace(make_settings(tmp_path), max_request_bytes=1024, max_image_bytes=5 * 1024 * 1024)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/connectivity/receipt",
                files={"image": ("crop.jpg", b"x" * 2048, "image/jpeg")},
            )

    assert response.status_code == 413
    assert response.json()["detail"]["error"] == "request_too_large"


def _jwk_from_public_key(public_key: rsa.RSAPublicKey) -> dict[str, str]:
    numbers = public_key.public_numbers()

    def encode(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return {"kid": "test-key", "kty": "RSA", "n": encode(numbers.n), "e": encode(numbers.e)}


def test_signed_cloudflare_access_assertion_is_verified() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(
        access_required=True,
        access_team_domain="https://team.cloudflareaccess.com",
        access_jwks_url="https://team.cloudflareaccess.com/cdn-cgi/access/certs",
        access_audience="botanika-audience",
    )
    verifier = AccessVerifier(settings)
    verifier._load_jwks = lambda: [_jwk_from_public_key(private_key.public_key())]
    now = datetime.now(UTC)
    assertion = jwt.encode(
        {
            "aud": [settings.access_audience],
            "iss": settings.access_team_domain,
            "email": "kisoreabhinav@gmail.com",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    assert verifier.verify(assertion)["email"] == "kisoreabhinav@gmail.com"
    disallowed_assertion = jwt.encode(
        {
            "aud": [settings.access_audience],
            "iss": settings.access_team_domain,
            "email": "not-the-owner@example.com",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with pytest.raises(AccessAuthenticationError):
        verifier.verify(disallowed_assertion)


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.incoming: asyncio.Queue[dict] = asyncio.Queue()

    async def accept(self) -> None:
        return None

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def receive_json(self) -> dict:
        return await self.incoming.get()


async def test_status_websocket_uses_events_not_video(tmp_path: Path) -> None:
    hub = StatusHub(make_settings(tmp_path))
    websocket = FakeWebSocket()
    task = asyncio.create_task(hub.serve(websocket))
    await asyncio.sleep(0)
    await websocket.incoming.put({"type": "ping"})
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert websocket.sent[0]["type"] == "connected"
    assert websocket.sent[0]["heartbeat_interval_seconds"] == 20
    assert any(message["type"] == "pong" for message in websocket.sent)
