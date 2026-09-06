#!/usr/bin/env python3
"""Exercise the responsive saved-observation map with deterministic fixtures.

The check runs the built frontend at phone widths and uses the same local API
fixture as the Phase 8 browser verifier.  It checks map rendering and links;
it does not claim that a real phone opened Google Maps or received turn by
turn navigation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import base64
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Browser, Page, Route, sync_playwright

from verify_phase8_ui import (
    api_handler,
    library_fixture,
    mode_status,
    serve_dist,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "evidence" / "phase10"
MOCK_TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chromium", default=shutil.which("chromium") or "/usr/bin/chromium")
    parser.add_argument("--focused", action="store_true", help="run marker/popup/tile interaction checks only")
    return parser


def phone_fixture(*, coincident: bool = False) -> dict[str, object]:
    """Return two category-colored plants, optionally at one exact coordinate."""
    fixture = library_fixture()
    locations = fixture["map"]["locations"]
    assert isinstance(locations, list)
    first = locations[0]
    second = locations[1]
    assert isinstance(first, dict) and isinstance(second, dict)
    if coincident:
        second["latitude"] = first["latitude"]
        second["longitude"] = first["longitude"]

    # Match the production URL shape, including walking and the explicit
    # Google Maps navigate action.  This is a browser fixture, not navigation.
    for location in locations:
        latitude = float(location["latitude"])
        longitude = float(location["longitude"])
        coordinate = f"{latitude:.7f},{longitude:.7f}"
        location["map_url"] = f"https://www.google.com/maps/search/?api=1&query={coordinate}"
        location["directions_url"] = (
            "https://www.google.com/maps/dir/?api=1"
            f"&destination={coordinate.replace(',', '%2C')}"
            "&travelmode=walking&dir_action=navigate"
        )
    fixture["map"]["message"] = "Markers are saved plant observations. Open walking directions in Google Maps."
    return fixture


def empty_phone_fixture() -> dict[str, object]:
    """Return the production-shaped library payload before the first save."""
    fixture = phone_fixture()
    fixture["map"]["locations"] = []
    fixture["map"]["total"] = 0
    fixture["map"]["has_locations"] = False
    fixture["map"]["message"] = "No saved observations include an accurate location yet."
    return fixture


def api_fixture_handler(route: Route, fixture: dict[str, object]) -> None:
    path = urlparse(route.request.url).path
    if path.endswith("/library/records"):
        route.fulfill(json=fixture)
        return
    if path.endswith("/library/map"):
        route.fulfill(json=fixture["map"])
        return
    api_handler(route, mode_status("NETWORKED_PAIRED", role="remote"))


def block_map_tiles(route: Route) -> None:
    """Simulate offline tile failure while allowing the local app and API."""
    url = route.request.url.lower()
    tile_tokens = ("tile", "tiles", "openstreetmap", "mapbox", "google.com/maps", "cartocdn")
    if any(token in url for token in tile_tokens):
        route.abort()
        return
    route.continue_()


def map_container(page: Page):
    candidates = page.locator(".observation-map, [data-testid='observation-map'], [aria-label='Discovery map']")
    assert candidates.count() > 0, "saved observations need an actual map container"
    return candidates.first


def markers(page: Page):
    candidates = page.locator(".map-marker, [data-testid='map-marker']")
    assert candidates.count() > 0, "saved observations need map markers"
    return candidates


def assert_no_horizontal_overflow(page) -> None:
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.evaluate("document.body.scrollWidth <= innerWidth")


def assert_marker_colors(page: Page) -> None:
    observed = page.locator(".map-marker, [data-testid='map-marker']").evaluate_all(
        """els => els.map(el => {
            const all = [el, ...el.querySelectorAll('*')];
            const colors = all.flatMap(item => [getComputedStyle(item).backgroundColor, item.dataset.categoryColor || item.style.backgroundColor]);
            return {colors};
        })"""
    )
    assert len(observed) >= 2, observed
    values = {color for item in observed for color in item["colors"] if color}
    assert any("63, 125, 82" in value or value.lower() == "#3f7d52" for value in values), values
    assert any("180, 73, 73" in value or value.lower() == "#b44949" for value in values), values


def assert_direction_links(page: Page, fixture: dict[str, object]) -> None:
    links = page.locator(".map-location-list a, [data-testid='map-direction'], a[href*='google.com/maps/dir']")
    assert links.count() >= 2, "each mapped plant needs a walking directions action"
    expected = fixture["map"]["locations"]
    assert isinstance(expected, list)
    found_destinations = set()
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href") or ""
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        destination = query.get("destination", [""])[0]
        found_destinations.add(destination.replace(",", "%2C"))
        assert parsed.netloc == "www.google.com", href
        assert parsed.path == "/maps/dir/", href
        assert query.get("travelmode") == ["walking"], href
        assert query.get("dir_action") == ["navigate"], href
    for location in expected:
        coordinate = f"{float(location['latitude']):.7f},{float(location['longitude']):.7f}"
        assert coordinate in {value.replace("%2C", ",") for value in found_destinations}, (coordinate, found_destinations)


def assert_plant_access(page: Page, fixture: dict[str, object]) -> None:
    text = page.locator(".library-map-panel").inner_text()
    assert "Banyan" in text and "Lantana" in text, text
    # The map's detail affordances carry the scientific/common names when the
    # map is used on a narrow viewport.  Keep the check tolerant of a popup or
    # a side list implementation.
    scientific_names = page.locator(".library-map-panel").evaluate(
        """panel => {
            const content = panel.innerText;
            const attrs = [...panel.querySelectorAll('*')].flatMap(el => [el.title || '', el.getAttribute('aria-label') || '']).join(' ');
            return content + ' ' + attrs;
        }"""
    )
    assert "Ficus benghalensis" in scientific_names
    assert "Lantana camara" in scientific_names


def fulfill_mock_tiles(route: Route) -> None:
    route.fulfill(status=200, content_type="image/png", body=MOCK_TILE)


def run_focused_interactions(browser: Browser, base_url: str, output: Path, *, coincident: bool = False) -> None:
    """Exercise actual marker/popup taps and load deterministic raster tiles."""
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    context.add_init_script("localStorage.setItem('botanika.controller.token', 'phase10-browser-token');")
    page = context.new_page()
    page.set_default_timeout(7000)
    fixture = phone_fixture(coincident=coincident)
    requests: list[str] = []

    def google_navigation(route: Route) -> None:
        requests.append(route.request.url)
        route.fulfill(status=204, body="")

    page.route("**/api/v1/**", lambda route: api_fixture_handler(route, fixture))
    page.route("**/tile.openstreetmap.org/**", fulfill_mock_tiles)
    context.route("**/www.google.com/maps/**", google_navigation)
    try:
        page.goto(base_url, wait_until="domcontentloaded")
        page.locator(".home-card").filter(has_text="Library").click()
        page.get_by_role("button", name="Observation map", exact=True).click()
        page.locator(".leaflet-marker-icon").first.wait_for(state="visible")
        tiles = page.locator(".leaflet-tile-loaded")
        assert tiles.count() > 0, "mocked street tiles did not load"
        assert tiles.evaluate_all("els => els.every(el => el.complete && el.naturalWidth > 0)"), "loaded tile has no pixels"

        map_markers = page.locator(".leaflet-marker-icon")
        assert map_markers.count() >= 2, f"expected two fanned Leaflet markers, found {map_markers.count()}"
        assert all((box := map_markers.nth(index).bounding_box()) and box["width"] >= 44 and box["height"] >= 44 for index in range(map_markers.count())), "map marker touch target is below 44px"
        list_markers = page.locator(".map-list-marker")
        assert all((box := list_markers.nth(index).bounding_box()) and box["width"] >= 44 and box["height"] >= 44 for index in range(list_markers.count())), "list marker touch target is below 44px"
        expected = fixture["map"]["locations"]
        assert isinstance(expected, list)
        marker_elements = map_markers.element_handles()
        selected = []
        for index in range(2 if coincident else 1):
            marker_elements[index].dispatch_event("click")
            page.locator(".leaflet-popup").last.wait_for(state="visible")
            popup = page.locator(".map-popup").last
            popup.wait_for(state="visible")
            popup_text = popup.inner_text()
            assert expected[index]["common_name"] in popup_text, popup_text
            assert expected[index]["scientific_name"] in popup_text, popup_text
            directions = popup.locator("a").filter(has_text="Walking directions")
            assert directions.count() == 1
            expected_url = expected[index]["directions_url"]
            assert directions.get_attribute("href") == expected_url
            with page.expect_popup() as popup_info:
                directions.click()
            navigation_popup = popup_info.value
            navigation_popup.wait_for_load_state("domcontentloaded")
            navigation_popup.close()
            selected.append(expected[index]["common_name"])
            page.locator(".leaflet-popup-close-button").click()
        assert selected == [item["common_name"] for item in expected[: 2 if coincident else 1]]
        assert len(requests) == len(selected), requests
        for request_url, item in zip(requests, expected):
            assert request_url == item["directions_url"], (request_url, item["directions_url"])
        page.screenshot(path=str(output / f"phone-map-focused{'-coincident' if coincident else ''}.png"), full_page=True)
    finally:
        context.close()


def run_width(browser: Browser, base_url: str, output: Path, width: int, *, coincident: bool = False, offline: bool = False) -> None:
    context = browser.new_context(viewport={"width": width, "height": 844}, is_mobile=True, has_touch=True)
    context.add_init_script("localStorage.setItem('botanika.controller.token', 'phase10-browser-token');")
    page = context.new_page()
    page.set_default_timeout(7000)
    fixture = phone_fixture(coincident=coincident)
    if offline:
        page.route("**/*", block_map_tiles)
    # Register the API route after the broad offline route: Playwright uses
    # the last matching handler, and the fixture must remain available while
    # tile requests fail.
    page.route("**/api/v1/**", lambda route: api_fixture_handler(route, fixture))
    try:
        page.goto(base_url, wait_until="domcontentloaded")
        page.locator(".home-card").filter(has_text="Library").click()
        page.get_by_role("button", name="Observation map", exact=True).click()
        container = map_container(page)
        container.wait_for(state="visible")
        box = container.bounding_box()
        assert box and box["width"] >= width - 34 and box["height"] >= 120, box
        assert_no_horizontal_overflow(page)
        assert_marker_colors(page)
        assert_plant_access(page, fixture)
        assert_direction_links(page, fixture)
        if coincident:
            map_markers = markers(page)
            assert map_markers.count() >= 2
            # Distinct links prove that coincident plants remain individually accessible.
            first_two = [
                {
                    "href": map_markers.nth(index).get_attribute("href"),
                    "label": map_markers.nth(index).get_attribute("aria-label"),
                    "title": map_markers.nth(index).get_attribute("title"),
                }
                for index in range(2)
            ]
            assert len({item["href"] for item in first_two}) == 2, first_two
            assert len({item["label"] or item["title"] for item in first_two}) == 2, first_two
        if offline:
            fallback = page.locator(".map-offline-fallback, [data-testid='map-offline-fallback']")
            fallback_text = page.get_by_text(re.compile("offline|tile.*(unavailable|failed)|map.*(unavailable|failed)", re.I))
            assert fallback.count() > 0 or fallback_text.count() > 0, "tile failure needs an offline fallback"
        page.screenshot(path=str(output / f"phone-map-{width}{'-offline' if offline else ''}.png"), full_page=True)
    finally:
        context.close()


def run_empty_library(browser: Browser, base_url: str, output: Path) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    context.add_init_script("localStorage.setItem('botanika.controller.token', 'phase10-browser-token');")
    page = context.new_page()
    page.set_default_timeout(7000)
    fixture = empty_phone_fixture()
    page.route("**/api/v1/**", lambda route: api_fixture_handler(route, fixture))
    page.route("**/tile.openstreetmap.org/**", fulfill_mock_tiles)
    try:
        page.goto(base_url, wait_until="domcontentloaded")
        page.locator(".home-card").filter(has_text="Library").click()
        page.get_by_role("button", name="Observation map", exact=True).click()
        container = page.get_by_test_id("observation-map")
        container.wait_for(state="visible")
        assert container.locator(".leaflet-map-pane").count() == 1, "empty library did not initialize Leaflet"
        assert page.locator(".leaflet-tile-loaded").count() > 0, "empty library map did not render street tiles"
        assert page.locator(".leaflet-marker-icon").count() == 0, "empty library map unexpectedly rendered markers"
        assert "0 mapped observations" in page.locator(".library-map-head").inner_text()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=str(output / "phone-map-empty-390.png"), full_page=True)
    finally:
        context.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    with serve_dist() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True, args=["--no-sandbox"])
        if args.focused:
            run_focused_interactions(browser, url, args.output)
            run_focused_interactions(browser, url, args.output, coincident=True)
        else:
            run_width(browser, url, args.output, 360)
            run_width(browser, url, args.output, 390)
            run_width(browser, url, args.output, 390, coincident=True)
            run_width(browser, url, args.output, 390, offline=True)
            run_empty_library(browser, url, args.output)
        browser.close()
    print(json.dumps({"status": "ok", "focused": args.focused, "widths": [360, 390] if not args.focused else [390], "offline_fallback": not args.focused, "real_device_navigation": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
