#!/usr/bin/env python3
"""Smoke-test the Phase 9 chat/library/weed surfaces at kiosk and phone sizes."""

from __future__ import annotations

import argparse
from pathlib import Path

from verify_phase8_ui import (
    assert_fixed_pi_canvas,
    assert_persistent_masthead,
    assert_persistent_masthead_pixels,
    assert_portrait_layout,
    capabilities,
    mode_status,
    new_context,
    serve_dist,
    wait_for_paint,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "evidence" / "phase9"


def phase9_capabilities() -> dict[str, object]:
    """Provide a ready Weed Beta fixture so this smoke test can open it.

    The production capability is correctly unavailable until its separately
    licensed model is installed.  This verifier exercises the ready-state
    layout with a mocked model contract; Phase 5 separately verifies that the
    home card is disabled when the capability is absent.
    """

    report = capabilities()
    report["weeds"] = {
        "available": True,
        "detail": "UI fixture",
        "model": {
            "available": True,
            "model_name": "fixture-weed-detector",
            "version": "fixture-v1",
            "region": "Maharashtra",
            "crop_context": "cotton",
            "labels": ["parthenium", "nutsedge"],
            "manifest": {
                "model_name": "fixture-weed-detector",
                "version": "fixture-v1",
                "region": "Maharashtra",
                "crop_context": "cotton",
                "labels": ["parthenium", "nutsedge"],
            },
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with serve_dist() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox"])
        fixture_capabilities = phase9_capabilities()
        context, page = new_context(
            browser,
            mode_status("SOLO"),
            {"width": 800, "height": 480},
            capability_report=fixture_capabilities,
        )
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(".home", timeout=3000)
            page.get_by_role("button", name="Ask Botanika").click()
            page.wait_for_selector(".chat-shell", timeout=3000)
            assert_fixed_pi_canvas(page)
            assert_persistent_masthead(page)
            wait_for_paint(page)
            assert_persistent_masthead_pixels(page)
            page.screenshot(path=str(args.output / "ask-800x480.png"))
            page.get_by_role("button", name="Home").click()
            # The production card is disabled without the independent Weed
            # Beta model.  This Phase 9 fixture explicitly marks that model
            # ready so the feature surface can be smoke-tested.
            page.locator(".home-card").nth(2).click()
            page.wait_for_selector(".weed-page", timeout=3000)
            assert_fixed_pi_canvas(page)
            assert_persistent_masthead(page)
            wait_for_paint(page)
            assert_persistent_masthead_pixels(page)
            page.screenshot(path=str(args.output / "weeds-800x480.png"))
        finally:
            context.close()

        context, page = new_context(
            browser,
            mode_status("NETWORKED_PAIRED", role="remote"),
            {"width": 390, "height": 844},
            token="phase9-browser-token",
            capability_report=fixture_capabilities,
        )
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(".responsive-shell", timeout=3000)
            page.locator(".home-card").nth(2).click()
            page.wait_for_selector(".weed-page", timeout=3000)
            assert_portrait_layout(page)
            page.screenshot(path=str(args.output / "weeds-browser-390x844.png"))
        finally:
            context.close()
        browser.close()
    print(f"Phase 9 chat and weed UI verified at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
