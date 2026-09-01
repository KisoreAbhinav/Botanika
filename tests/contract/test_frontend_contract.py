from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_browser_upload_timeout_covers_csrf_and_upload_and_preserves_retry() -> None:
    source = (ROOT / "frontend/src/placeholder.js").read_text()
    assert "const timeoutId = setTimeout" in source
    assert "controller.abort()" in source
    assert 'signal });' in source  # CSRF fetch receives the same abort signal.
    assert "signal: controller.signal" in source
    assert "Upload timed out. The crop is still on this phone; retry or cancel." in source
    assert "state.controller = null;" in source


def test_browser_uses_binary_crop_upload_and_no_live_video_api() -> None:
    html = (ROOT / "frontend/index.html").read_text()
    source = (ROOT / "frontend/src/placeholder.js").read_text()
    assert 'type="file"' in html
    assert "new FormData()" in source
    assert "getUserMedia" not in source
    assert "WebRTC" not in source
    assert "MediaRecorder" not in source
