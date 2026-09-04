#!/usr/bin/env python3
"""Verify honest Phase 6 baseline states at the fixed 800x480 viewport."""

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
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "evidence" / "phase6"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        return


@contextmanager
def serve_dist():
    if not (DIST / "index.html").is_file():
        raise SystemExit("frontend/dist is missing; run `npm run build` first")
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(DIST), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
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
        "species_id": "in:ficus-benghalensis",
        "common_name": "Banyan",
        "scientific_name": "Ficus benghalensis",
        "family": "Moraceae",
        "category": "Indian native",
        "conservation_status": "Not threatened (Kew species profile)",
        "confidence": 0.86,
        "short_notes": "A large strangling fig with aerial roots.",
        "sources": ["https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:852482-1/general-information"],
        "classifier_version": "india-starter-feature-1.0.0",
        "is_stub": False,
        "demo_label": "",
        "suggestions": [],
        "error": None,
    }


def baseline_abstention() -> dict[str, object]:
    return {
        "status": "uncertain",
        "species_id": None,
        "common_name": None,
        "scientific_name": None,
        "family": None,
        "category": None,
        "conservation_status": None,
        "confidence": 0.86,
        "short_notes": (
            "The local classifier baseline matched this view, but field validation is incomplete. "
            "No production identification or library save is allowed yet."
        ),
        "sources": ["botanika:unvalidated-classifier-baseline"],
        "classifier_version": "india-starter-feature-1.0.0",
        "is_stub": False,
        "demo_label": "",
        "suggestions": [{
            "common_name": "Banyan",
            "scientific_name": "Ficus benghalensis",
            "confidence": 0.86,
        }],
        "error": None,
    }


def snapshot() -> dict[str, object]:
    result = baseline_abstention()
    return {
        "sequence": 12,
        "timestamp": 1788364800.0,
        "session_id": "phase6-ui-evidence",
        "mode": "camera",
        "state": "Uncertain",
        "hint": "Field validation incomplete",
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
            "source_timestamp": 1788364800.0,
        },
        "detections": [{
            "class_id": 58,
            "label": "potted plant",
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
        "stable_checks": 4,
        "required_checks": 4,
        "capture": None,
        "classification": {
            "request_id": "phase6-ui-evidence",
            "crop_path": "in_ficus-benghalensis/observation.png",
            "crop_hash": "evidence",
            "started_at": 1788364800.0,
            "completed_at": 1788364800.01,
            "duration_ms": 10.0,
            "result": result,
        },
        "processing": False,
        "camera_available": True,
        "detector_latency": {"p50_ms": 21.0, "p95_ms": 28.0},
        "error": None,
    }


def record(record_id: str, suffix: str) -> dict[str, object]:
    return {
        **accepted_result(),
        "id": record_id,
        "observation_id": record_id,
        "saved_at": 1788364800.0,
        "observed_at": 1788364800.0,
        "crop_relative_path": f"in_ficus-benghalensis/{suffix}.png",
        "thumbnail_path": f"in_ficus-benghalensis/{suffix}.thumb.jpg",
        "crop_url": f"/media/discoveries/in_ficus-benghalensis/{suffix}.png",
        "thumbnail_url": f"/media/discoveries/in_ficus-benghalensis/{suffix}.thumb.jpg",
        "crop_hash": suffix,
        "width": 320,
        "height": 280,
        "native_status": "Native to the Indian subcontinent.",
        "is_native": True,
        "ecology": "Tree of tropical forest and seasonally dry tropical habitats.",
        "note": "Garden edge observation",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chromium", default=shutil.which("chromium") or "/usr/bin/chromium")
    args = parser.parse_args(argv)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    current_snapshot = snapshot()
    records = [record("observation-1", "one"), record("observation-2", "two")]
    capabilities = {
        name: {"available": True, "detail": "Ready"}
        for name in ("camera", "detector", "classifier", "storage", "library", "preview")
    }
    capabilities["classifier"] = {
        "available": False,
        "detail": "Held-out metrics, unknown-rejection trials, and Pi benchmark evidence are incomplete.",
        "model": {"version": "india-starter-feature-1.0.0", "deployment_ready": False},
    }
    capabilities["knowledge"] = {
        "available": True,
        "detail": "Offline catalog ready: 7 species.",
        "model": {"catalog_id": "botanika-india-starter", "species_count": 7},
    }
    ok, encoded = cv2.imencode(".jpg", np.full((330, 500, 3), (65, 95, 70), dtype=np.uint8))
    if not ok:
        raise SystemExit("could not create UI preview fixture")

    def handle(route) -> None:
        url = route.request.url
        if url.endswith("/capabilities"):
            route.fulfill(json=capabilities)
        elif url.endswith("/health/ready"):
            route.fulfill(json={"status": "degraded", "capabilities": capabilities})
        elif url.endswith("/scan/state"):
            route.fulfill(json=current_snapshot)
        elif url.endswith("/scan/events"):
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=f"event: snapshot\ndata: {json.dumps(current_snapshot)}\n\n",
            )
        elif url.endswith("/scan/preview.mjpg"):
            route.fulfill(status=200, content_type="image/jpeg", body=encoded.tobytes())
        elif url.endswith("/library/records") and route.request.method == "GET":
            route.fulfill(json={
                "records": records,
                "total": len(records),
                "is_demo_only": False,
                "species_count": 1,
                "observation_count": len(records),
                "categories": ["Indian native"],
                "coverage": {
                    "location_available": False,
                    "message": "Location unavailable — discoveries are still saved.",
                },
                "groups": [],
            })
        elif url.endswith("/chat"):
            route.fulfill(json={
                "answer": "Banyan is native to the Indian subcontinent.",
                "citations": [{
                    "chunk_id": "banyan-kew",
                    "source": {"source_id": "kew-powo", "title": "Plants of the World Online", "url": "https://powo.science.kew.org/"},
                }],
                "evidence": [],
                "abstained": False,
            })
        else:
            route.fulfill(json={"ok": True, "detail": "Phase 6 UI verification"})

    def media(route) -> None:
        route.fulfill(status=200, content_type="image/jpeg", body=encoded.tobytes())

    with serve_dist() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium,
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 800, "height": 480}, device_scale_factor=1)
        page.route("**/api/v1/**", handle)
        page.route("**/media/**", media)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(250)
        assert page.evaluate("[innerWidth, innerHeight]") == [800, 480]
        assert page.evaluate("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]") == [800, 480]
        assert not undersized_controls(page)
        assert_persistent_masthead(page)
        wait_for_paint(page, 0)
        assert_persistent_masthead_pixels(page)
        page.screenshot(path=str(output / "home-800x480.png"))
        assert page.get_by_text("Models: Unavailable", exact=True).is_visible()

        page.get_by_text("Scan for Plants", exact=True).click()
        page.wait_for_timeout(200)
        assert_persistent_masthead(page)
        assert page.locator(".side-header").inner_text() == "Not confident"
        assert not page.locator(".demo-tag").count()
        assert page.get_by_role("button", name="Save to Library").is_disabled()
        assert page.get_by_text("field validation is incomplete", exact=False).is_visible()
        wait_for_paint(page, 0)
        assert_persistent_masthead_pixels(page)
        page.screenshot(path=str(output / "scan-baseline-abstention-800x480.png"))

        page.get_by_role("button", name="Home").click()
        page.get_by_text("Library", exact=True).first.click()
        page.wait_for_timeout(200)
        assert page.locator(".library-row").count() == 1
        assert page.get_by_text("2 observation(s)").is_visible()
        page.get_by_role("button", name="Details").click()
        assert_persistent_masthead(page)
        assert page.get_by_role("dialog").locator(".species-name").inner_text() == "Banyan"
        assert page.evaluate("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]") == [800, 480]
        assert not undersized_controls(page)
        wait_for_paint(page, 0)
        assert_persistent_masthead_pixels(page)
        page.screenshot(path=str(output / "library-details-800x480.png"))

        page.get_by_role("button", name="Close").click()
        page.get_by_role("button", name="Ask Botanika (available)").click()
        page.get_by_role("textbox", name="Question for Botanika").fill("Where is banyan native?")
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(200)
        assert_persistent_masthead(page)
        assert page.get_by_text("Banyan is native to the Indian subcontinent.").is_visible()
        assert page.evaluate("[document.documentElement.scrollWidth, document.documentElement.scrollHeight]") == [800, 480]
        assert not undersized_controls(page)
        wait_for_paint(page, 0)
        assert_persistent_masthead_pixels(page)
        page.screenshot(path=str(output / "ask-grounded-800x480.png"))
        browser.close()
    print(f"Phase 6 baseline-abstention and local-data UI states verified at {output}")
    return 0


def undersized_controls(page) -> list[dict[str, float]]:
    return page.eval_on_selector_all(
        "button, select",
        "elements => elements.map(element => element.getBoundingClientRect())"
        ".filter(rect => rect.width < 40 || rect.height < 40)",
    )


if __name__ == "__main__":
    raise SystemExit(main())
