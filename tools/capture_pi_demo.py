#!/usr/bin/env python3
"""Capture a slower, Pi-sized Botanika feature walkthrough.

The browser renders the real built React UI at the Pi's 800x480 kiosk contract.
API responses are deterministic replay data so the capture is repeatable without
claiming that a live camera, GPS receiver, or network service was active during
the recording. The weed fixture result is the output of the installed detector
stored in data/demo/weed-in-maize-field-result.json.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import sys

from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright

from verify_phase8_ui import mode_status, serve_dist


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST = PROJECT_ROOT / "frontend" / "dist"
PLANT_IMAGE = (
    PROJECT_ROOT
    / "data"
    / "campus"
    / "enrollment"
    / "train"
    / "Mimusops elengi"
    / "IMG_20260905_164056731.jpg"
)
WEED_IMAGE = PROJECT_ROOT / "data" / "demo" / "weed-in-maize-field.jpg"
WEED_RESULT = PROJECT_ROOT / "data" / "demo" / "weed-in-maize-field-result.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "deliverables" / "pi-demo" / "screenshots"
DEFAULT_VIDEO = PROJECT_ROOT / "deliverables" / "pi-demo" / "video"
OBSERVED_AT = 1788624000.0
DEMO_LATITUDE = 12.96930
DEMO_LONGITUDE = 79.15650


def json_body(route: Route, payload: object, *, content_type: str = "application/json") -> None:
    route.fulfill(
        status=200,
        content_type=content_type,
        body=json.dumps(payload),
        headers={"Cache-Control": "no-store"},
    )


def plant_record() -> dict[str, object]:
    location = {
        "sample_id": "pi-demo-sample-001",
        "observation_id": "pi-demo-observation-001",
        "latitude": DEMO_LATITUDE,
        "longitude": DEMO_LONGITUDE,
        "accuracy_m": 12.0,
        "captured_at": OBSERVED_AT,
        "map_url": f"https://www.google.com/maps/search/?api=1&query={DEMO_LATITUDE},{DEMO_LONGITUDE}",
        "directions_url": f"https://www.google.com/maps/dir/?api=1&destination={DEMO_LATITUDE},{DEMO_LONGITUDE}",
        "common_name": "Spanish cherry",
        "scientific_name": "Mimusops elengi",
        "category": "Indian native",
        "category_color": "#3f7d52",
    }
    return {
        "id": "pi-demo-observation-001",
        "species_id": "in:mimusops-elengi",
        "common_name": "Spanish cherry",
        "scientific_name": "Mimusops elengi",
        "family": "Sapotaceae",
        "region": "India",
        "category": "Indian native",
        "native_status": "Native to tropical Asia, including India, and cultivated in tropical settlements.",
        "is_native": True,
        "conservation_status": "Not assessed in this checklist",
        "ecology": "Evergreen tree with glossy leaves and fragrant flowers; commonly planted in South Asian towns and campuses.",
        "short_notes": "The campus photo shows glossy leaves consistent with the Spanish cherry entry in the local catalog.",
        "aliases": ["Bakul", "Maulsari"],
        "sources": ["https://powo.science.kew.org/"],
        "source_details": [
            {
                "source_id": "powo-mimusops-elengi",
                "title": "Mimusops elengi — Plants of the World Online",
                "publisher": "Royal Botanic Gardens, Kew",
                "url": "https://powo.science.kew.org/",
                "license": "CC BY 3.0",
            }
        ],
        "observed_at": OBSERVED_AT,
        "confidence": 0.91,
        "classifier_version": "india-starter-feature-v1",
        "note": "R-block east planting bed · synthetic demo coordinate",
        "crop_filename": "pi-demo-spanish-cherry.jpg",
        "crop_url": "/media/discoveries/pi-demo-spanish-cherry.jpg",
        "thumbnail_url": "/media/discoveries/pi-demo-spanish-cherry.jpg",
        "locations": [location],
    }


def accepted_classification() -> dict[str, object]:
    return {
        "status": "accepted",
        "species_id": "in:mimusops-elengi",
        "common_name": "Spanish cherry",
        "scientific_name": "Mimusops elengi",
        "family": "Sapotaceae",
        "category": "Indian native",
        "native_status": "Native to tropical Asia, including India.",
        "conservation_status": "Not assessed in this checklist",
        "confidence": 0.91,
        "short_notes": "Glossy leaves and the campus enrollment label support this catalog match. Confirm with flowers or fruit in the field.",
        "sources": ["Mimusops elengi — Plants of the World Online"],
        "classifier_version": "india-starter-feature-v1",
        "catalogued": True,
        "is_stub": False,
        "suggestions": [],
        "error": None,
    }


def scan_snapshot(phase: str) -> dict[str, object]:
    accepted = accepted_classification()
    classification = None
    if phase == "accepted":
        classification = {
            "request_id": "pi-demo-plant-scan-001",
            "crop_hash": "pi-demo-local-image-sha256",
            "duration_ms": 842.0,
            "result": accepted,
        }
    elif phase == "uncertain":
        classification = {
            "request_id": "pi-demo-plant-scan-uncertain",
            "crop_hash": "pi-demo-local-image-sha256",
            "duration_ms": 734.0,
            "result": {
                **accepted,
                "status": "uncertain",
                "species_id": None,
                "common_name": None,
                "scientific_name": None,
                "family": None,
                "category": None,
                "conservation_status": None,
                "confidence": 0.61,
                "short_notes": "The view does not contain enough distinguishing detail for a reliable match.",
                "suggestions": [
                    {
                        "common_name": "Spanish cherry",
                        "scientific_name": "Mimusops elengi",
                        "confidence": 0.61,
                    }
                ],
            },
        }
    elif phase == "validation":
        classification = {
            "request_id": "pi-demo-plant-scan-validation",
            "crop_hash": "pi-demo-local-image-sha256",
            "duration_ms": 768.0,
            "result": {
                **accepted,
                "status": "uncertain",
                "validation_pending": True,
                "confidence": 0.78,
                "short_notes": "The campus-photo match is provisional until independent field validation is complete.",
                "suggestions": [
                    {
                        "common_name": "Spanish cherry",
                        "scientific_name": "Mimusops elengi",
                        "confidence": 0.78,
                    }
                ],
            },
        }
    elif phase == "error":
        classification = {
            "request_id": "pi-demo-plant-scan-error",
            "crop_hash": "pi-demo-local-image-sha256",
            "duration_ms": 205.0,
            "result": {
                **accepted,
                "status": "error",
                "species_id": None,
                "common_name": None,
                "scientific_name": None,
                "family": None,
                "category": None,
                "conservation_status": None,
                "confidence": None,
                "error": "Classifier unavailable",
            },
        }
    if phase == "fallback":
        state = "Image loaded"
        hint = "Saved image loaded · ready to capture from the local frame."
    elif phase in {"accepted", "uncertain", "validation", "error"}:
        state = "Identified"
        hint = "Accepted crop received from the saved image."
    elif phase == "locked":
        state = "Locked"
        hint = "Target locked · hold steady."
    elif phase == "processing":
        state = "Captured"
        hint = "Processing plant…"
    elif phase == "cancelled":
        state = "Ready for a plant"
        hint = "Scan cancelled. Ready for another plant."
    else:
        state = "Ready for a plant"
        hint = "Hold a plant steady or load a saved image."
    return {
        "mode": "fallback" if phase == "fallback" else "camera",
        "camera_available": phase != "unavailable",
        "processing": phase == "processing",
        "state": state,
        "hint": hint,
        "frame": {
            "width": 2048,
            "height": 1536,
            "scale": 330 / 1536,
            "offset_x": 30,
            "offset_y": 0,
        },
        "detections": [] if phase == "unavailable" else [
            {"label": "plant", "confidence": 0.97, "box": {"x1": 210, "y1": 150, "x2": 1810, "y2": 1450}}
        ],
        "selected_index": None if phase == "unavailable" else 0,
        "stable_checks": 4 if phase in {"locked", "processing", "accepted", "uncertain", "validation", "error"} else 1,
        "required_checks": 4,
        "quality": None if phase == "unavailable" else {
            "ready": True,
            "target_width": 1600,
            "target_height": 1300,
            "saturated_fraction": 0.01,
            "mean_luma": 126,
            "reasons": [],
            "hint": "Good frame: target is stable and large enough.",
        },
        "classification": classification,
        "error": None,
    }


def capabilities() -> dict[str, object]:
    report = {
        name: {"available": True, "detail": "Pi demo replay"}
        for name in ("camera", "detector", "classifier", "storage", "library", "preview")
    }
    report["knowledge"] = {"available": True, "detail": "Offline catalog ready: 7 regional starter species."}
    report["network"] = {
        "available": True,
        "detail": "Loopback kiosk replay",
        "model": {"enabled": False, "available": True},
    }
    report["mode"] = {"available": True, "detail": "SOLO operator fixture"}
    report["weeds"] = {
        "available": True,
        "detail": "Installed detector result replay",
        "model": {
            "available": True,
            "model_name": "Broadleaf weed cue",
            "version": "broadleaf-yolo11n-640",
            "labels": ["weed"],
            "manifest": {
                "model_name": "Broadleaf weed cue",
                "version": "broadleaf-yolo11n-640",
                "labels": ["weed"],
            },
        },
    }
    return report


def regional_checklist(saved: bool) -> list[dict[str, object]]:
    entries = [
        (
            "in:ficus-benghalensis",
            "Banyan",
            "Ficus benghalensis",
            "Moraceae",
            "Indian native",
            "Large tropical fig with aerial roots.",
            "Tropical settlement and dry-forest tree.",
            "#3f7d52",
        ),
        (
            "in:ficus-religiosa",
            "Sacred fig",
            "Ficus religiosa",
            "Moraceae",
            "Indian native",
            "Heart-shaped leaves with a long tapering tip.",
            "Seasonally dry tropical tree; often planted near sacred sites.",
            "#3f7d52",
        ),
        (
            "in:artocarpus-heterophyllus",
            "Jackfruit",
            "Artocarpus heterophyllus",
            "Moraceae",
            "Indian native",
            "Food tree with fruit on branches and trunk.",
            "Wet-tropical food and shade tree.",
            "#3f7d52",
        ),
        (
            "in:ocimum-tenuiflorum",
            "Holy basil",
            "Ocimum tenuiflorum",
            "Lamiaceae",
            "Indian native",
            "Aromatic branching herb known locally as tulsi.",
            "Warm open habitats and household gardens.",
            "#3f7d52",
        ),
        (
            "in:moringa-oleifera",
            "Drumstick tree",
            "Moringa oleifera",
            "Moringaceae",
            "Indian native",
            "Drought-tolerant tree with compound leaves and long pods.",
            "Gardens and farms in warm climates.",
            "#3f7d52",
        ),
        (
            "in:jasminum-sambac",
            "Arabian jasmine",
            "Jasminum sambac",
            "Oleaceae",
            "Indian native",
            "Fragrant evergreen shrub with white flowers.",
            "Warm gardens and cultural flower plantings.",
            "#3f7d52",
        ),
        (
            "in:mimusops-elengi",
            "Spanish cherry",
            "Mimusops elengi",
            "Sapotaceae",
            "Indian native",
            "Glossy-leaved tree with fragrant flowers; campus observation saved.",
            "Tropical Asian tree commonly planted in South Asian towns.",
            "#3f7d52",
        ),
    ]
    result = []
    for species_id, common, scientific, family, category, notes, ecology, color in entries:
        found = saved and species_id == "in:mimusops-elengi"
        item: dict[str, object] = {
            "species_id": species_id,
            "common_name": common,
            "scientific_name": scientific,
            "family": family,
            "category": category,
            "category_color": color,
            "status": "found" if found else "not_found",
            "observation_count": 1 if found else 0,
            "short_notes": notes,
            "ecology": ecology,
            "native_status": "Native to India or the Indian subcontinent.",
            "conservation_status": "Starter checklist record",
            "aliases": [],
            "source_details": [],
        }
        if found:
            item["locations"] = plant_record()["locations"]
        result.append(item)
    return result


def library_fixture(saved: bool) -> dict[str, object]:
    record = plant_record()
    records = [record] if saved else []
    locations = []
    if saved:
        location = dict(record["locations"][0])
        locations.append({**location, "species_id": record["species_id"]})
    legend = [{"category": "Indian native", "color": "#3f7d52", "label": "Indian native"}]
    return {
        "records": records,
        "groups": [],
        "total": len(records),
        "species_count": 1 if saved else 0,
        "observation_count": len(records),
        "is_demo_only": False,
        "categories": ["Indian native"] if saved else [],
        "coverage": {
            "message": (
                "Synthetic demo coordinate saved · R-block east planting bed, VIT Vellore."
                if saved
                else "No observations saved yet."
            ),
            "coverage_percent": 14 if saved else 0,
        },
        "progress": {
            "discovered_species": 1 if saved else 0,
            "supported_species": 7,
            "coverage_percent": 14 if saved else 0,
            "category_progress": [{"category": "Indian native", "coverage_percent": 14 if saved else 0}],
            "milestones": [{"id": "first-observation", "label": "First campus observation", "complete": saved}],
        },
        "aggregate": {"anonymous": True},
        "map": {
            "locations": locations,
            "total": len(locations),
            "has_locations": bool(locations),
            "message": f"Synthetic demo point · R-block east planting bed, VIT Vellore · {DEMO_LATITUDE:.5f}, {DEMO_LONGITUDE:.5f} · not device GPS.",
            "legend": legend,
            "region": "Vellore region, Tamil Nadu",
        },
        "map_legend": legend,
        "regional_catalog": {
            "region": "Vellore region, Tamil Nadu",
            "scope_note": "Seven-species regional starter checklist for the Pi walkthrough; not an exhaustive flora.",
        },
        "regional_checklist": regional_checklist(saved),
    }


class Fixture:
    def __init__(self, plant_data: bytes, weed_data_url: str, weed_result: dict[str, object]) -> None:
        self.plant_data = plant_data
        self.weed_data_url = weed_data_url
        self.weed_result = weed_result
        self.phase = "camera"
        self.saved = False

    @property
    def scan(self) -> dict[str, object]:
        return scan_snapshot(self.phase)


def api_handler(route: Route, fixture: Fixture, capability_report: dict[str, object]) -> None:
    request = route.request
    path = urlparse_path(request.url)
    method = request.method

    if path.endswith("/mode/status"):
        json_body(route, mode_status("SOLO", role="operator"))
    elif path.endswith("/capabilities"):
        json_body(route, capability_report)
    elif path.endswith("/health/ready"):
        json_body(route, {"status": "ok", "capabilities": capability_report})
    elif path.endswith("/health/live"):
        json_body(route, {"status": "ok"})
    elif path.endswith("/network/status"):
        json_body(route, {"state": "loopback", "address": "127.0.0.1"})
    elif path.endswith("/scan/state"):
        json_body(route, fixture.scan)
    elif path.endswith("/scan/events"):
        payload = json.dumps(fixture.scan, separators=(",", ":"))
        route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=f"event: snapshot\ndata: {payload}\n\n",
            headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
        )
    elif path.endswith("/scan/preview.mjpg"):
        route.fulfill(status=200, content_type="image/jpeg", body=fixture.plant_data)
    elif path.endswith("/scan/fallback") and method == "POST":
        fixture.phase = "fallback"
        json_body(route, {"ok": True, "detail": "Saved image loaded into the Pi scan preview."})
    elif path.endswith("/scan/fallback/capture") and method == "POST":
        fixture.phase = "accepted"
        json_body(route, {"ok": True, "detail": "Saved image accepted for identification."})
    elif path.endswith("/scan/fallback/clear") and method == "POST":
        fixture.phase = "camera"
        json_body(route, {"ok": True})
    elif path.endswith("/scan/manual-capture") and method == "POST":
        fixture.phase = "accepted"
        json_body(route, {"ok": True})
    elif path.endswith("/scan/retake") and method == "POST":
        fixture.phase = "camera"
        json_body(route, {"ok": True})
    elif path.endswith("/scan/select") and method == "POST":
        json_body(route, {"ok": True})
    elif path.endswith("/library/records") and method == "POST":
        fixture.saved = True
        json_body(route, {"record": plant_record()})
    elif path.endswith("/library/records"):
        json_body(route, library_fixture(fixture.saved))
    elif path.endswith("/library/map"):
        json_body(route, library_fixture(fixture.saved)["map"])
    elif path.endswith("/weeds/status"):
        json_body(route, capability_report["weeds"]["model"])
    elif path.endswith("/weeds/camera") and method == "POST":
        result = dict(fixture.weed_result)
        result["frame_data_url"] = fixture.weed_data_url
        result.pop("crop_context", None)
        result["detail"] = "One generic broadleaf weed cue found in a maize-field frame. Review before acting."
        result["position_message"] = "Coordinates skipped for this replay; no device GPS was used."
        json_body(route, result)
    elif path.endswith("/voice/status"):
        json_body(route, {"available": False, "state": "idle", "detail": "Voice hardware not exercised in this screen capture."})
    elif path.endswith("/chat") and method == "POST":
        json_body(
            route,
            {
                "answer": "Spanish cherry (Mimusops elengi) is a glossy-leaved tree native to tropical Asia, including India. Confirm the match with flowers or fruit before treating the record as a field certainty.",
                "abstained": False,
                "citations": [
                    {
                        "chunk_id": "pi-demo-mimusops",
                        "source": {
                            "title": "Mimusops elengi — Plants of the World Online",
                            "url": "https://powo.science.kew.org/",
                            "license": "CC BY 3.0",
                        },
                    }
                ],
            },
        )
    elif path.endswith("/weeds/export"):
        route.fulfill(status=200, content_type="application/json", body="{}")
    else:
        json_body(route, {"ok": True, "detail": "Pi demo replay"})


def urlparse_path(url: str) -> str:
    # Avoid importing urllib.parse in every route call while retaining query-safe matching.
    return url.split("?", 1)[0]


def open_screen(page: Page, label: str, selector: str) -> None:
    # The home cards expose their descriptive paragraph and shortcut key in
    # the button's accessible name, so target the visible card label instead
    # of requiring an exact full accessible-name match.
    page.locator(".home-card").filter(has_text=label).first.click()
    page.wait_for_selector(selector, timeout=5000)


def settle(page: Page, milliseconds: int = 1250) -> None:
    page.wait_for_timeout(milliseconds)
    page.evaluate(
        """() => new Promise((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(resolve));
        })"""
    )


def capture(page: Page, output: Path, name: str) -> None:
    path = output / name
    page.screenshot(path=str(path), full_page=False)
    image_size = page.evaluate("[innerWidth, innerHeight]")
    if image_size != [800, 480]:
        raise RuntimeError(f"Pi capture is not 800x480: {image_size}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--chromium", default=shutil.which("chromium") or "/usr/bin/chromium")
    parser.add_argument(
        "--single-scan-phase",
        choices=("locked", "processing", "uncertain", "validation", "error", "cancelled", "unavailable"),
        help="Capture only one audited scan state instead of the full walkthrough.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.video.mkdir(parents=True, exist_ok=True)
    for path in (PLANT_IMAGE, WEED_IMAGE, WEED_RESULT, DIST / "index.html"):
        if not path.is_file():
            raise SystemExit(f"required demo asset is missing: {path}")

    weed_payload = json.loads(WEED_RESULT.read_text(encoding="utf-8"))["result"]
    plant_data = PLANT_IMAGE.read_bytes()
    weed_data_url = "data:image/jpeg;base64," + base64.b64encode(WEED_IMAGE.read_bytes()).decode("ascii")
    fixture = Fixture(plant_data, weed_data_url, weed_payload)
    capability_report = capabilities()

    with serve_dist() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium,
            headless=True,
            args=["--no-sandbox"],
        )
        context: BrowserContext = browser.new_context(
            viewport={"width": 800, "height": 480},
            device_scale_factor=1,
            record_video_dir=str(args.video),
        )
        page = context.new_page()
        page.route(
            "**/api/v1/**",
            lambda route: api_handler(route, fixture, capability_report),
        )
        page.route(
            "**/media/**",
            lambda route: route.fulfill(status=200, content_type="image/jpeg", body=plant_data),
        )

        if args.single_scan_phase:
            filenames = {
                "locked": "17-pi-scan-target-locked.png",
                "processing": "18-pi-scan-processing.png",
                "uncertain": "19-pi-scan-not-confident.png",
                "validation": "20-pi-scan-validation-pending.png",
                "error": "21-pi-scan-identification-error.png",
                "cancelled": "22-pi-scan-cancelled.png",
                "unavailable": "23-pi-scan-camera-unavailable.png",
            }
            fixture.phase = args.single_scan_phase
            page.goto(base_url, wait_until="domcontentloaded")
            page.wait_for_selector(".home", timeout=5000)
            open_screen(page, "Scan for Plants", ".scan")
            settle(page, 700)
            capture(page, args.output, filenames[args.single_scan_phase])
            context.close()
            browser.close()
            print(json.dumps({"screenshots": str(args.output), "phase": args.single_scan_phase}, indent=2))
            return 0

        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_selector(".home", timeout=5000)
        settle(page)
        capture(page, args.output, "01-pi-home.png")

        open_screen(page, "Scan for Plants", ".scan")
        settle(page)
        capture(page, args.output, "02-pi-scan-camera-ready.png")

        page.locator('input[aria-label="Upload a local image for analysis"]').set_input_files(str(PLANT_IMAGE))
        settle(page, 700)
        # The SOLO service owns the authoritative scan snapshot. Re-open the
        # screen after the upload so the replay shows the same state transition
        # a fresh Pi client would receive from its event channel.
        page.get_by_role("button", name="Home", exact=True).click()
        page.wait_for_selector(".home", timeout=5000)
        open_screen(page, "Scan for Plants", ".scan")
        settle(page)
        capture(page, args.output, "03-pi-scan-saved-image-loaded.png")

        page.get_by_role("button", name=re.compile("Capture from image")).click()
        settle(page, 850)
        page.get_by_role("button", name="Home", exact=True).click()
        page.wait_for_selector(".home", timeout=5000)
        open_screen(page, "Scan for Plants", ".scan")
        settle(page)
        capture(page, args.output, "04-pi-scan-identified.png")

        page.get_by_role("button", name=re.compile("Save to Library")).click()
        page.wait_for_selector("text=Saved Spanish cherry to the library.", timeout=5000)
        settle(page, 1000)
        capture(page, args.output, "05-pi-observation-saved.png")

        page.get_by_role("button", name="Home", exact=True).click()
        page.wait_for_selector(".home", timeout=5000)
        open_screen(page, "Library", ".library")
        page.wait_for_selector("text=Spanish cherry", timeout=5000)
        settle(page)
        capture(page, args.output, "06-pi-library-saved-record.png")

        page.get_by_role("button", name="Details", exact=True).click()
        page.wait_for_selector(".library-dialog", timeout=5000)
        settle(page)
        page.locator(".dialog-scroll").evaluate("element => { element.scrollTop = element.scrollHeight; }")
        settle(page, 500)
        capture(page, args.output, "07-pi-library-location-details.png")

        page.get_by_role("button", name="Close", exact=True).click()
        page.get_by_role("button", name="Observation map", exact=True).click()
        page.wait_for_selector('[aria-label="Discovery map"]', timeout=5000)
        settle(page)
        capture(page, args.output, "08-pi-observation-map.png")

        page.get_by_role("button", name="Vellore checklist", exact=True).click()
        page.wait_for_selector('[aria-label="Vellore regional flora checklist"]', timeout=5000)
        settle(page)
        capture(page, args.output, "09-pi-vellore-checklist.png")

        page.get_by_role("button", name="Home", exact=True).click()
        page.wait_for_selector(".home", timeout=5000)
        page.locator(".home-card").nth(2).click()
        page.wait_for_selector(".weed-page", timeout=5000)
        settle(page)
        capture(page, args.output, "10-pi-weed-before-analysis.png")
        page.get_by_role("button", name="Analyze Pi frame", exact=True).click()
        page.wait_for_selector(".weed-result-count", timeout=5000)
        settle(page, 1500)
        capture(page, args.output, "11-pi-weed-detected-maize-field.png")

        page.get_by_role("button", name=re.compile("Ask Botanika")).click()
        page.wait_for_selector(".chat-shell", timeout=5000)
        page.get_by_label("Question for Botanika").fill("Why does this plant matter in a campus landscape?")
        page.get_by_role("button", name="Send", exact=True).click()
        page.wait_for_selector("text=Spanish cherry (Mimusops elengi)", timeout=5000)
        settle(page, 1400)
        capture(page, args.output, "12-pi-ask-botanika.png")

        page.get_by_role("button", name="Capability diagnostics").click()
        page.wait_for_selector('[aria-label="Diagnostics"]', timeout=5000)
        settle(page, 900)
        capture(page, args.output, "13-pi-capability-diagnostics.png")

        page.get_by_role("button", name="Close", exact=True).click()
        page.get_by_role("button", name="Home", exact=True).click()
        page.wait_for_selector(".home", timeout=5000)
        page.keyboard.press("F1")
        page.wait_for_selector(".shortcuts-pop", timeout=5000)
        settle(page, 500)
        capture(page, args.output, "14-pi-keyboard-shortcuts.png")

        page.keyboard.press("Escape")
        page.get_by_role("button", name=re.compile("Ask Botanika")).click()
        page.wait_for_selector(".chat-empty", timeout=5000)
        settle(page, 500)
        capture(page, args.output, "15-pi-ask-empty.png")

        fixture.saved = False
        page.get_by_role("button", name="Home", exact=True).click()
        page.wait_for_selector(".home", timeout=5000)
        open_screen(page, "Library", ".library")
        settle(page, 600)
        capture(page, args.output, "16-pi-library-empty.png")
        fixture.saved = True

        for phase, filename in (
            ("locked", "17-pi-scan-target-locked.png"),
            ("processing", "18-pi-scan-processing.png"),
            ("uncertain", "19-pi-scan-not-confident.png"),
            ("validation", "20-pi-scan-validation-pending.png"),
            ("error", "21-pi-scan-identification-error.png"),
            ("cancelled", "22-pi-scan-cancelled.png"),
            ("unavailable", "23-pi-scan-camera-unavailable.png"),
        ):
            fixture.phase = phase
            page.goto(base_url, wait_until="domcontentloaded")
            page.wait_for_selector(".home", timeout=5000)
            open_screen(page, "Scan for Plants", ".scan")
            settle(page, 700)
            capture(page, args.output, filename)

        context.close()
        browser.close()

    recordings = sorted(args.video.glob("*.webm"), key=lambda item: item.stat().st_mtime)
    if recordings:
        target = args.video / "botanika-pi-demo-slow.webm"
        if target.exists():
            target.unlink()
        recordings[-1].replace(target)
        print(json.dumps({"screenshots": str(args.output), "video": str(target)}, indent=2))
    else:
        print(json.dumps({"screenshots": str(args.output), "video": None}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
