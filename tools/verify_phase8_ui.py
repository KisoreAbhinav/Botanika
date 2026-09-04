#!/usr/bin/env python3
"""Verify Phase 8 mode consoles and paired portrait UI with local API mocks.

This is a deterministic browser smoke check. It proves the built frontend can
render the required layout contracts and browser-owned camera handoff without
claiming a real Pi display, Wi-Fi AP, phone camera, or physical touch session.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST = PROJECT_ROOT / "frontend" / "dist"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "evidence" / "phase8"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--chromium",
        default=shutil.which("chromium") or "/usr/bin/chromium",
    )
    return parser


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return


@contextmanager
def serve_dist():
    if not (DIST / "index.html").is_file():
        raise SystemExit("frontend/dist is missing; run `npm run build` in frontend first")
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(DIST), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, name="phase8-ui-static", daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def capabilities() -> dict[str, object]:
    report = {
        name: {"available": True, "detail": "UI fixture"}
        for name in ("camera", "detector", "classifier", "storage", "library", "preview")
    }
    report["knowledge"] = {"available": True, "detail": "UI fixture"}
    report["network"] = {
        "available": True,
        "detail": "Private AP fixture",
        "model": {"enabled": False, "available": True},
    }
    report["mode"] = {"available": True, "detail": "UI fixture"}
    return report


def mode_status(
    mode: str,
    *,
    role: str = "operator",
    tunnel_state: str | None = None,
) -> dict[str, object]:
    status: dict[str, object] = {
        "mode": mode,
        "client_role": role,
        "state": mode.lower(),
        "transition_count": 8,
        "last_transition_at": 1788364800.0,
        "access_point": {"ssid": "Botanika", "address": "192.168.50.1"},
        "network": {"state": "connected", "address": "192.168.50.1"},
        "pairing": None,
        "controller": None,
        "controller_count": 0,
        "connection": {"healthy": False, "state": "idle"},
        "scan": {"state": "Waiting", "hint": "Ready for a controller."},
        "recent_results": [],
    }
    if mode == "NETWORKED_UNPAIRED":
        status["pairing"] = {
            "code": "BOTANIKA",
            "expires_at": 1788365100.0,
            "expires_in_seconds": 300,
            "single_use": True,
        }
        status["network"] = {
            "state": "connected",
            "address": "192.168.50.1",
            "ssid": "Botanika",
        }
        if tunnel_state is not None:
            ready = tunnel_state == "ready"
            url = "https://fern-field.trycloudflare.com" if ready else None
            tunnel = {
                "enabled": True,
                "state": tunnel_state,
                "url": url,
                "connect_url": url,
                "detail": (
                    "Secure connection is ready. Waiting for device…"
                    if ready
                    else "cloudflared could not reach the Internet."
                    if tunnel_state == "failed"
                    else "Setting up secure connection…"
                ),
                "diagnostics": [],
            }
            status["tunnel"] = tunnel
            status["network"]["tunnel"] = tunnel
            status["transport"] = (
                "cloudflare-quick-tunnel" if ready else "loopback"
            )
            if ready:
                status["pairing"]["url"] = url
                status["pairing"]["deep_link"] = f"{url}/?pair=BOTANIKA"
    elif mode == "NETWORKED_PAIRED":
        status["controller"] = {
            "device_name": "Field phone",
            "client_id": "phone-fixture",
            "paired_at": 1788364800.0,
            "last_seen_at": 1788364980.0,
            "expires_at": 1788365280.0,
            "expires_in_seconds": 300,
        }
        status["controller_count"] = 1
        status["connection"] = {"healthy": True, "state": "connected"}
        result = {
            "status": "accepted",
            "common_name": "Banyan",
            "scientific_name": "Ficus benghalensis",
            "confidence": 0.86,
        }
        status["scan"] = {"state": "Identified", "hint": "Accepted crop received.", "result": result}
        status["recent_results"] = [
            {"request_id": "fixture-1", "status": "accepted", "common_name": "Banyan", "confidence": 0.86}
        ]
    return status


def api_handler(
    route: Route,
    status: dict[str, object],
    capability_report: dict[str, object] | None = None,
) -> None:
    path = urlparse(route.request.url).path
    if path.endswith("/mode/status"):
        route.fulfill(json=status)
    elif path.endswith("/capabilities"):
        route.fulfill(json=capability_report or capabilities())
    elif path.endswith("/health/ready"):
        route.fulfill(json={"status": "ok", "capabilities": capability_report or capabilities()})
    elif path.endswith("/network/status"):
        route.fulfill(json=status["network"])
    elif path.endswith("/library/records"):
        route.fulfill(json={"records": [], "total": 0, "is_demo_only": False})
    elif path.endswith("/mode/controller/crop"):
        route.fulfill(json={"ok": True, "detail": "UI fixture"})
    else:
        route.fulfill(json={"ok": True, "detail": "Phase 8 UI verification"})


def new_context(
    browser: Browser,
    status: dict[str, object],
    viewport: dict[str, int],
    token: str | None = None,
    deny_camera: bool = False,
    capability_report: dict[str, object] | None = None,
) -> tuple[BrowserContext, Page]:
    context = browser.new_context(viewport=viewport, device_scale_factor=1)
    if token:
        context.add_init_script(
            f"localStorage.setItem('botanika.controller.token', {json.dumps(token)});"
        )
    if deny_camera:
        context.add_init_script(
            "Object.defineProperty(navigator, 'mediaDevices', {"
            "configurable: true, value: { getUserMedia: () => Promise.reject(new Error('fixture denial')) }"
            "});"
        )
    page = context.new_page()
    page.route(
        "**/api/v1/**",
        lambda route: api_handler(route, status, capability_report),
    )
    return context, page


def assert_fixed_pi_canvas(page: Page) -> None:
    assert page.evaluate("[innerWidth, innerHeight]") == [800, 480]
    assert page.evaluate(
        "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
    ) == [800, 480]
    shell = page.locator(".shell").bounding_box()
    assert shell is not None
    assert round(shell["width"]) == 800
    assert round(shell["height"]) == 480
    undersized = undersized_controls(page)
    assert not undersized, undersized


def assert_portrait_layout(page: Page) -> None:
    assert page.evaluate("[innerWidth, innerHeight]") == [390, 844]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.evaluate("document.body.scrollWidth <= innerWidth")
    undersized = undersized_controls(page)
    assert not undersized, undersized


def undersized_controls(page: Page) -> list[dict[str, float]]:
    return page.eval_on_selector_all(
        "button, select, input:not([type='file']):not([type='range'])",
        "elements => elements.map(element => ({element, rect: element.getBoundingClientRect(), style: getComputedStyle(element)}))"
        ".filter(({rect, style}) => style.display !== 'none' && style.visibility !== 'hidden' && (rect.width < 44 || rect.height < 44))"
        ".map(({rect}) => ({width: rect.width, height: rect.height}))",
    )


def fixture_photo() -> dict[str, object]:
    """Return a deterministic local image fixture without a network request."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">'
        '<rect width="640" height="480" fill="#1d3b2b"/>'
        '<rect x="90" y="70" width="460" height="340" fill="#78a35a"/>'
        '<circle cx="320" cy="240" r="120" fill="#d6c56a"/>'
        '<path d="M120 380 C240 150 360 330 520 95" stroke="#244d31" stroke-width="30" fill="none"/>'
        '</svg>'
    ).encode("utf-8")
    return {"name": "plant-fixture.svg", "mimeType": "image/svg+xml", "buffer": svg}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)

    with serve_dist() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium,
            headless=True,
            args=["--no-sandbox"],
        )

        for mode, filename, marker in (
            ("SOLO", "solo-800x480.png", ".home"),
            ("NETWORKED_UNPAIRED", "networked-unpaired-800x480.png", ".unpaired-console"),
            ("NETWORKED_PAIRED", "networked-paired-800x480.png", ".paired-console"),
        ):
            context, page = new_context(browser, mode_status(mode), {"width": 800, "height": 480})
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector(marker, timeout=3000)
                page.wait_for_timeout(150)
                assert_fixed_pi_canvas(page)
                page.screenshot(path=str(args.output / filename))
            finally:
                context.close()

        for tunnel_state, filename, expected_text in (
            ("starting", "tunnel-starting-800x480.png", "Setting up secure connection"),
            ("ready", "tunnel-ready-800x480.png", "Waiting for device"),
            ("failed", "tunnel-failed-800x480.png", "Retry secure connection"),
        ):
            context, page = new_context(
                browser,
                mode_status("NETWORKED_UNPAIRED", tunnel_state=tunnel_state),
                {"width": 800, "height": 480},
            )
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector(".unpaired-console", timeout=3000)
                page.get_by_text(expected_text, exact=False).first.wait_for(timeout=3000)
                page.wait_for_timeout(150)
                assert_fixed_pi_canvas(page)
                if tunnel_state == "ready":
                    assert page.locator(".tunnel-qr").is_visible()
                page.screenshot(path=str(args.output / filename))
            finally:
                context.close()

        context, page = new_context(
            browser,
            mode_status("NETWORKED_UNPAIRED", role="remote"),
            {"width": 390, "height": 844},
        )
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(".mobile-mode-page", timeout=3000)
            page.wait_for_timeout(150)
            assert_portrait_layout(page)
            assert page.get_by_role("heading", name="Pair this device").is_visible()
            page.screenshot(path=str(args.output / "pairing-browser-390x844.png"))
        finally:
            context.close()

        context, page = new_context(
            browser,
            mode_status("NETWORKED_PAIRED", role="remote"),
            {"width": 390, "height": 844},
            token="phase8-browser-token",
            deny_camera=True,
        )
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(".responsive-shell", timeout=3000)
            page.wait_for_timeout(150)
            assert_portrait_layout(page)
            page.screenshot(path=str(args.output / "paired-browser-home-390x844.png"))

            page.get_by_text("Scan for Plants", exact=True).click()
            page.wait_for_selector(".networked-scan-page", timeout=3000)
            page.wait_for_selector(".detector-fallback-label", timeout=3000)
            page.wait_for_timeout(250)
            assert_portrait_layout(page)
            assert page.get_by_text("Continuous phone video never reaches the Pi.", exact=False).is_visible()
            page.screenshot(path=str(args.output / "paired-camera-390x844.png"))

            page.get_by_label("Open the phone camera or choose a local plant image").set_input_files(fixture_photo())
            page.wait_for_timeout(250)
            page.wait_for_selector(".manual-crop-control", timeout=3000)
            page.wait_for_timeout(150)
            assert page.get_by_text("Manual crop inset", exact=False).is_visible()
            assert_portrait_layout(page)
            page.screenshot(path=str(args.output / "paired-manual-crop-390x844.png"))
        finally:
            context.close()
        browser.close()

    print(f"Phase 8 mode consoles and responsive browser screenshots verified at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
