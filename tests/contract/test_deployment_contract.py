from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_reverse_proxy_is_loopback_only_and_has_matching_limits() -> None:
    config = (ROOT / "deploy/reverse_proxy/botanika.conf.example").read_text()
    assert "listen 127.0.0.1:8080" in config
    assert "listen 0.0.0.0" not in config
    assert "client_max_body_size 6m" in config
    assert "proxy_set_header Upgrade $http_upgrade" in config
    assert "proxy_read_timeout 1h" in config


def test_service_dependencies_and_backend_bind_are_explicit() -> None:
    backend = (ROOT / "deploy/systemd/botanika-backend.service").read_text()
    tunnel = (ROOT / "deploy/systemd/botanika-cloudflared.service").read_text()
    assert "--host 127.0.0.1 --port 8000" in backend
    assert "Requires=botanika-backend.service nginx.service" in tunnel
    assert "--token ${TUNNEL_TOKEN}" in tunnel
    assert "Restart=always" in tunnel


def test_example_environment_keeps_request_envelope_above_image_cap() -> None:
    environment = (ROOT / "config/environments/connectivity.env.example").read_text()
    assert "BOTANIKA_MAX_REQUEST_BYTES=6291456" in environment
    assert "BOTANIKA_MAX_IMAGE_BYTES=5242880" in environment
