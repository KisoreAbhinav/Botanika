#!/usr/bin/env python3
"""Capture a deterministic Botanika phone demo from the built React app.

The browser UI is real; only the Pi API responses are replayed so the capture
is repeatable on a development machine without a live camera or classifier.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

from verify_phase8_ui import mode_status, serve_dist


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "deliverables" / "screenshots"
DEFAULT_VIDEO = PROJECT_ROOT / "deliverables" / "video"
PLANT_IMAGE = PROJECT_ROOT / "data" / "campus" / "enrollment" / "train" / "Hibiscus × rosa-sinensis" / "IMG_20260905_164205316.jpg"
WEED_IMAGE = PROJECT_ROOT / "data" / "campus" / "enrollment" / "train" / "Sphagneticola trilobata" / "IMG_20260905_163856144.jpg"


def capabilities() -> dict[str, object]:
    report = {
        name: {"available": True, "detail": "Replay fixture"}
        for name in ("camera", "detector", "classifier", "storage", "library", "preview")
    }
    report["knowledge"] = {"available": True, "detail": "Offline catalog ready: 7 species."}
    report["network"] = {"available": True, "detail": "Secure paired replay"}
    report["mode"] = {"available": True, "detail": "Paired replay"}
    report["weeds"] = {
        "available": True,
        "detail": "Replay fixture",
        "model": {
            "available": True,
            "model_name": "Botanika weed cue",
            "version": "beta-v1",
            "region": "internal manifest",
            "crop_context": "internal scope",
            "labels": ["weed"],
            "manifest": {
                "model_name": "Botanika weed cue",
                "version": "beta-v1",
                "region": "internal manifest",
                "crop_context": "internal scope",
                "labels": ["weed"],
            },
        },
    }
    return report


def accepted_classification() -> dict[str, object]:
    return {
        "status": "accepted",
        "species_id": "in:ficus-benghalensis",
        "common_name": "Banyan",
        "scientific_name": "Ficus benghalensis",
        "family": "Moraceae",
        "category": "Indian native",
        "conservation_status": "Not threatened (Kew species profile)",
        "confidence": 0.86,
        "short_notes": "A large strangling fig with aerial roots and strong cultural importance.",
        "sources": ["botanika:replay-evidence"],
        "classifier_version": "india-starter-feature-v1",
        "is_stub": False,
        "demo_label": "",
        "suggestions": [],
        "error": None,
    }


def crop_fields(route: Route) -> tuple[str | None, int | None, int | None]:
    body = route.request.post_data_buffer.decode("utf-8", errors="ignore")
    digest = re.search(r'name="crop_hash"\r?\n\r?\n([0-9a-f]{64})', body)
    width = re.search(r'name="width"\r?\n\r?\n(\d+)', body)
    height = re.search(r'name="height"\r?\n\r?\n(\d+)', body)
    return (
        digest.group(1) if digest else None,
        int(width.group(1)) if width else None,
        int(height.group(1)) if height else None,
    )


def api_handler(route: Route, status: dict[str, object], plant_data_url: str) -> None:
    url = route.request.url
    if url.endswith("/mode/status"):
        route.fulfill(json=status)
        return
    if url.endswith("/capabilities"):
        route.fulfill(json=capabilities())
        return
    if url.endswith("/health/ready"):
        route.fulfill(json={"status": "ok", "capabilities": capabilities()})
        return
    if url.endswith("/network/status"):
        route.fulfill(json=status["network"])
        return
    if url.endswith("/mode/controller/crop"):
        digest, width, height = crop_fields(route)
        route.fulfill(json={
            "ok": True,
            "crop": {"sha256": digest, "width": width, "height": height},
            "classification": {
                "request_id": "replay-plant-scan-001",
                "crop_hash": digest,
                "result": accepted_classification(),
            },
        })
        return
    if url.endswith("/library/records") and route.request.method == "POST":
        route.fulfill(json={"record": {"common_name": "Banyan", "scientific_name": "Ficus benghalensis"}})
        return
    if url.endswith("/library/records"):
        route.fulfill(json={"records": [], "groups": [], "total": 0, "species_count": 0, "observation_count": 0})
        return
    if url.endswith("/weeds/status"):
        route.fulfill(json=capabilities()["weeds"]["model"])
        return
    if url.endswith("/weeds/controller/frame"):
        route.fulfill(json={
            "status": "ok",
            "detections": [{"weed_class": "weed", "confidence": 0.78, "box": {"x1": 180, "y1": 110, "x2": 540, "y2": 420}}],
            "image_width": 640,
            "image_height": 480,
            "position_available": False,
            "position_message": "Coordinate skipped; no accurate fix was available.",
            "detail": "One visual weed cue found. Review the frame before acting.",
            "frame_data_url": plant_data_url,
        })
        return
    route.fulfill(json={"ok": True, "detail": "Botanika replay"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--chromium", default=shutil.which("chromium") or "/usr/bin/chromium")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.video.mkdir(parents=True, exist_ok=True)
    if not PLANT_IMAGE.is_file() or not WEED_IMAGE.is_file():
        raise SystemExit("saved campus image fixtures are missing")

    plant_data_url = "data:image/jpeg;base64," + base64.b64encode(PLANT_IMAGE.read_bytes()).decode("ascii")
    status = mode_status("NETWORKED_PAIRED", role="remote")

    with serve_dist() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=1,
            record_video_dir=str(args.video),
        )
        context.add_init_script("localStorage.setItem('botanika.controller.token', 'replay-controller-token');")
        page = context.new_page()
        page.route("**/api/v1/**", lambda route: api_handler(route, status, plant_data_url))
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector(".home", timeout=5000)
        page.screenshot(path=str(args.output / "01-phone-home.png"), full_page=True)

        page.get_by_text("Scan for Plants", exact=True).click()
        page.wait_for_selector(".networked-scan-page", timeout=5000)
        page.locator('input[type="file"]').set_input_files(str(PLANT_IMAGE))
        page.wait_for_selector(".phone-crop-preview", timeout=5000)
        page.screenshot(path=str(args.output / "02-plant-saved-image-loaded.png"), full_page=True)

        identify = page.get_by_role("button", name="Identify this crop")
        if identify.is_disabled():
            raise SystemExit("saved image did not pass the local quality gate")
        identify.click()
        page.wait_for_selector(".networked-confidence", timeout=5000)
        page.screenshot(path=str(args.output / "03-plant-identified.png"), full_page=True)

        page.get_by_role("button", name="Save to Pi library").click()
        page.wait_for_selector("text=Saved Banyan to the Pi library.", timeout=5000)
        page.screenshot(path=str(args.output / "04-plant-saved-to-library.png"), full_page=True)

        dismissals = page.locator('.toast button[aria-label="Dismiss"]')
        while dismissals.count():
            dismissals.first.click()
        page.get_by_role("button", name="Home").click()
        page.wait_for_selector(".home", timeout=5000)
        page.locator(".home-card").nth(2).click()
        page.wait_for_selector(".weed-page", timeout=5000)
        page.locator('input[type="file"]').set_input_files(str(WEED_IMAGE))
        page.wait_for_timeout(250)
        page.get_by_role("button", name="Analyze captured frame").click()
        page.wait_for_selector(".weed-result-count", timeout=5000)
        page.screenshot(path=str(args.output / "05-weed-beta-result.png"), full_page=True)
        page.screenshot(path=str(args.output / "06-weed-beta-result-wide.png"), full_page=False)

        context.close()
        browser.close()

    recordings = sorted(args.video.glob("*.webm"), key=lambda item: item.stat().st_mtime)
    if recordings:
        recordings[-1].replace(args.video / "botanika-phone-demo.webm")
    print(json.dumps({"screenshots": str(args.output), "video": str(args.video / "botanika-phone-demo.webm")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
