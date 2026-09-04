#!/usr/bin/env python3
"""Automated 800x480 Phase 5 kiosk state and screenshot verification."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from verify_phase8_ui import assert_persistent_masthead, assert_persistent_masthead_pixels, wait_for_paint


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST = PROJECT_ROOT / "frontend" / "dist"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "evidence" / "phase5"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chromium", default=shutil.which("chromium") or "/usr/bin/chromium")
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
    thread = threading.Thread(target=server.serve_forever, name="phase5-ui-static", daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def accepted_result() -> dict[str, object]:
    return {
        "status": "accepted",
        "species_id": "demo:phase4:example-plant",
        "common_name": "Demo Plant",
        "scientific_name": "Specimenus demonstratus",
        "family": "Demonstration family",
        "category": "Demo specimen",
        "conservation_status": "Demo only — not assessed",
        "confidence": 0.93,
        "short_notes": "Placeholder output proving crop-to-result wiring; not an identification.",
        "sources": ["DEMO DATA: phase-4 fixture"],
        "classifier_version": "stub-phase-4",
        "is_stub": True,
        "demo_label": "DEMO DATA",
        "suggestions": [],
        "error": None,
    }


def snapshot(*, state: str = "Searching", hint: str = "Searching for a plant", processing: bool = False,
             result: dict[str, object] | None = None, mode: str = "camera") -> dict[str, object]:
    return {
        "sequence": 12,
        "timestamp": 1.0,
        "session_id": "ui-evidence",
        "mode": mode,
        "state": state,
        "hint": hint,
        "frame": {
            "source_width": 640,
            "source_height": 480,
            "preview_width": 500,
            "preview_height": 330,
            "scale": 0.6875,
            "offset_x": 30,
            "offset_y": 0,
            "rendered_width": 440,
            "rendered_height": 330,
            "source_sequence": 12,
            "source_timestamp": 1.0,
        },
        "detections": [{
            "class_id": 58,
            "label": "potted plant" if mode == "camera" else "manual image",
            "confidence": 0.91,
            "box": {"x1": 160, "y1": 100, "x2": 480, "y2": 380},
        }],
        "selected_index": 0,
        "quality": {
            "focus_score": 240.0,
            "mean_luma": 126.0,
            "saturated_fraction": 0.0,
            "target_width": 320,
            "target_height": 280,
            "edge_clipped": False,
            "ready": True,
            "reasons": [],
            "hint": "Ready",
        },
        "stable_checks": 4 if state in ("Locked", "Captured") else 1,
        "required_checks": 4,
        "capture": None,
        "classification": None if result is None else {
            "request_id": "ui-evidence",
            "crop_path": "demo.png",
            "crop_hash": "evidence",
            "started_at": 1.0,
            "completed_at": 1.01,
            "duration_ms": 10.0,
            "result": result,
        },
        "processing": processing,
        "camera_available": mode == "camera",
        "detector_latency": {"p50_ms": 21.0, "p95_ms": 28.0},
        "error": None,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    capabilities = {
        name: {"available": True, "detail": "Ready"}
        for name in ("camera", "detector", "classifier", "storage", "library", "preview")
    }
    capabilities["knowledge"] = {"available": False, "detail": "Phase 6"}
    current = {"snapshot": snapshot(), "records": []}
    image = np.zeros((330, 500, 3), dtype=np.uint8)
    image[:] = [36, 60, 38]
    cv2.rectangle(image, (140, 70), (360, 270), (62, 120, 68), -1)
    encoded_ok, encoded = cv2.imencode(".jpg", image)
    if not encoded_ok:
        raise SystemExit("could not create synthetic preview")

    def handle(route) -> None:
        url = route.request.url
        if url.endswith("/capabilities"):
            route.fulfill(json=capabilities)
        elif url.endswith("/health/ready"):
            route.fulfill(json={"status": "ok", "capabilities": capabilities})
        elif url.endswith("/scan/state"):
            route.fulfill(json=current["snapshot"])
        elif url.endswith("/scan/events"):
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=f"event: snapshot\ndata: {json.dumps(current['snapshot'])}\n\n",
            )
        elif url.endswith("/scan/preview.mjpg"):
            route.fulfill(status=200, content_type="image/jpeg", body=encoded.tobytes())
        elif url.endswith("/library/records") and route.request.method == "GET":
            route.fulfill(json={"records": current["records"], "total": len(current["records"]), "is_demo_only": True})
        else:
            route.fulfill(json={"ok": True, "detail": "UI verification"})

    with serve_dist() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 800, "height": 480}, device_scale_factor=1)
        page.route("**/api/v1/**", handle)

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        assert page.evaluate("[innerWidth, innerHeight]") == [800, 480]
        assert page.evaluate(
            "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
        ) == [800, 480]
        assert page.locator(".masthead").evaluate("element => element.offsetHeight") == 66
        assert page.locator(".home-card").nth(2).is_disabled()
        assert not undersized_controls(page)
        page.keyboard.press("?")
        page.wait_for_selector(".shortcuts-pop")
        page.keyboard.press("1")
        assert page.locator(".home").is_visible()
        page.keyboard.press("Escape")
        assert page.locator(".shortcuts-pop").count() == 0
        page.locator(".masthead-side.right .icon-target").click()
        page.keyboard.press("1")
        assert page.locator(".home").is_visible()
        page.keyboard.press("Escape")
        assert page.locator(".diagnostics-pop").count() == 0
        # The kiosk navigation contract follows InnoHack's physical-input
        # pattern. Verify the actual document listener, including its guard
        # while a text field is focused.
        page.keyboard.press("1")
        page.wait_for_selector(".scan")
        assert_persistent_masthead(page)
        page.keyboard.press("h")
        page.wait_for_selector(".home")
        page.keyboard.press("a")
        page.wait_for_selector(".chat-shell")
        assert_persistent_masthead(page)
        page.keyboard.press("2")
        page.wait_for_selector(".library")
        filter_select = page.locator(".library-toolbar select").first
        filter_select.focus()
        page.keyboard.press("1")
        assert page.locator(".library").is_visible()
        # Move focus back to a non-editable surface before exercising the
        # navigation shortcut again; the guard intentionally keeps H from
        # stealing keystrokes while a select is active.
        page.locator(".library-heading").click()
        page.keyboard.press("h")
        page.wait_for_selector(".home")
        wait_for_paint(page)
        assert_persistent_masthead_pixels(page)
        page.screenshot(path=str(args.output / "home-800x480.png"))

        states = [
            (snapshot(), "Guidance"),
            (snapshot(state="Locked", hint="Target locked"), "Guidance"),
            (snapshot(state="Captured", hint="Processing plant…", processing=True), "Processing plant…"),
            (snapshot(state="Captured", hint="Crop captured", result=accepted_result()), "Result"),
            (snapshot(state="Captured", hint="Not confident", result={
                **accepted_result(), "status": "uncertain", "species_id": None, "common_name": None,
                "scientific_name": None, "family": None, "category": None,
                "conservation_status": None, "confidence": 0.61,
                "suggestions": [{
                    "common_name": "Demo Plant",
                    "scientific_name": "Specimenus demonstratus",
                    "confidence": 0.61,
                }],
            }), "Not confident"),
            (snapshot(state="Captured", hint="Identification failed", result={
                **accepted_result(), "status": "error", "species_id": None, "common_name": None,
                "scientific_name": None, "family": None, "category": None,
                "conservation_status": None, "confidence": None, "error": "Classifier unavailable",
            }), "Identification failed"),
            (snapshot(hint="Scan cancelled"), "Guidance"),
        ]
        for state_value, expected_heading in states:
            current["snapshot"] = state_value
            page.goto(url, wait_until="domcontentloaded")
            page.get_by_text("Scan for Plants", exact=True).click()
            page.wait_for_timeout(200)
            assert_persistent_masthead(page)
            assert page.locator(".side-header").inner_text() == expected_heading
            assert page.evaluate(
                "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
            ) == [800, 480]
            assert not undersized_controls(page)

        current["snapshot"] = states[3][0]
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("Scan for Plants", exact=True).click()
        page.wait_for_timeout(200)
        assert page.get_by_role("button", name="Save to Library").is_enabled()
        wait_for_paint(page, 0)
        assert_persistent_masthead_pixels(page)
        page.screenshot(path=str(args.output / "scan-result-800x480.png"))

        current["snapshot"] = snapshot(mode="fallback", hint="Local image selected")
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("Scan for Plants", exact=True).click()
        page.wait_for_timeout(200)
        assert page.get_by_alt_text("Selected local image").is_visible()
        assert page.get_by_role("button", name="Capture from image").is_visible()

        record = {
            **accepted_result(),
            "id": "observation-1",
            "saved_at": 1_788_364_800.0,
            "crop_filename": "demo.png",
            "crop_hash": "one",
            "width": 320,
            "height": 280,
        }
        current["records"] = [record, {**record, "id": "observation-2", "crop_hash": "two"}]
        page.goto(url, wait_until="domcontentloaded")
        page.get_by_text("Library", exact=True).first.click()
        page.wait_for_timeout(200)
        assert_persistent_masthead(page)
        assert page.locator(".library-row").count() == 1
        assert page.get_by_text("2 observation(s)").is_visible()
        page.get_by_role("button", name="Details").click()
        assert page.locator(".observation").count() == 2
        page.keyboard.press("1")
        assert page.locator(".library-dialog").is_visible()
        assert page.locator(".library").is_visible()
        assert page.evaluate(
            "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
        ) == [800, 480]
        assert not undersized_controls(page)
        browser.close()

    print(f"Phase 5 UI states and screenshots verified at {args.output}")
    return 0


def undersized_controls(page) -> list[dict[str, float]]:
    return page.eval_on_selector_all(
        "button, select",
        "elements => elements.map(element => element.getBoundingClientRect())"
        ".filter(rect => rect.width < 40 || rect.height < 40)",
    )


if __name__ == "__main__":
    raise SystemExit(main())
