#!/usr/bin/env python3
"""Create the Botanika six-slide hackathon deck without external office deps."""

from __future__ import annotations

import argparse
import base64
import html
import zipfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables" / "Botanika_Field_Intelligence_Deck.pptx"
SCREENSHOTS = ROOT / "deliverables" / "screenshots"
LIVE_SCREENSHOTS = SCREENSHOTS / "live-phone"
PI_MODE = False

W, H = 12_192_000, 6_858_000
PAPER = "EFEDE3"
DEEP = "E2DFD5"
SURFACE = "F7F4E9"
INK = "272724"
MUTED = "5F5E59"
FAINT = "85827B"
LINE = "AAA79E"
GREEN = "486B51"
OCHRE = "8A692E"
RUST = "8B3028"


def shot(name: str) -> Path:
    names = {
        "home": "01-pi-home.png" if PI_MODE else "01-phone-home.png",
        "loaded": "03-pi-scan-saved-image-loaded.png" if PI_MODE else "02-plant-saved-image-loaded.png",
        "identified": "04-pi-scan-identified.png" if PI_MODE else "03-plant-identified.png",
        "weed": "11-pi-weed-detected-maize-field.png" if PI_MODE else "05-weed-beta-result.png",
    }
    return SCREENSHOTS / names[name]


def live_shot(name: str) -> Path:
    names = {
        "pair": "WhatsApp Image 2026-09-06 at 7.12.34 PM.jpeg",
        "home": "WhatsApp Image 2026-09-06 at 7.12.34 PM (1).jpeg",
        "crop": "WhatsApp Image 2026-09-06 at 8.59.56 PM (2).jpeg",
        "result": "WhatsApp Image 2026-09-06 at 8.59.55 PM (1).jpeg",
        "weed": "WhatsApp Image 2026-09-06 at 7.12.37 PM (1).jpeg",
    }
    return LIVE_SCREENSHOTS / names[name]

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def clr(value: str) -> str:
    return f'<a:solidFill><a:srgbClr val="{value}"/></a:solidFill>'


def line(fill: str = LINE, width: int = 900) -> str:
    return f'<a:ln w="{width}">{clr(fill)}</a:ln>'


def off_ext(x: int, y: int, w: int, h: int) -> str:
    return f'<a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'


def shape(slide: list[str], x: int, y: int, w: int, h: int, *, fill: str | None = None,
          stroke: str | None = None, radius: bool = False, rotate: int = 0) -> None:
    geom = "roundRect" if radius else "rect"
    rotation = f' rot="{rotate}"' if rotate else ""
    fill_xml = clr(fill) if fill else "<a:noFill/>"
    stroke_xml = line(stroke) if stroke else "<a:ln><a:noFill/></a:ln>"
    shape_id = 100 + len(slide)
    slide.append(
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="shape{shape_id}"/><p:cNvSpPr/><p:nvPr/>'
        f'</p:nvSpPr><p:spPr>{off_ext(x, y, w, h)}{rotation}<a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>'
        f'{fill_xml}{stroke_xml}</p:spPr></p:sp>'
    )


def text_box(slide: list[str], x: int, y: int, w: int, h: int, text: str, *, size: int = 18,
             color: str = INK, font: str = "Arial", bold: bool = False, italic: bool = False,
             align: str = "l", valign: str = "t", margin: int = 30_000) -> None:
    shape_id = 100 + len(slide)
    b = ' b="1"' if bold else ""
    i = ' i="1"' if italic else ""
    paras = []
    for paragraph in str(text).split("\n"):
        paras.append(
            f'<a:p><a:pPr algn="{align}"><a:defRPr sz="{size * 100}"{b}{i}>'
            f'<a:latin typeface="{font}"/>{clr(color)}</a:defRPr></a:pPr>'
            f'<a:r><a:rPr lang="en-US" sz="{size * 100}"{b}{i}><a:latin typeface="{font}"/>{clr(color)}</a:rPr>'
            f'<a:t>{esc(paragraph)}</a:t></a:r><a:endParaRPr lang="en-US" sz="{size * 100}"{b}{i}/></a:p>'
        )
    body = (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="text{shape_id}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr>{off_ext(x, y, w, h)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square" anchor="{valign}" lIns="{margin}" tIns="{margin}" rIns="{margin}" bIns="{margin}"/>'
        f'<a:lstStyle/>{"".join(paras)}</p:txBody></p:sp>'
    )
    slide.append(body)


def add_image(slide: list[str], rels: list[tuple[str, Path]], path: Path, x: int, y: int, w: int, h: int,
              *, border: str = LINE) -> None:
    with Image.open(path) as im:
        iw, ih = im.size
    scale = min(w / iw, h / ih)
    dw, dh = int(iw * scale), int(ih * scale)
    dx, dy = x + (w - dw) // 2, y + (h - dh) // 2
    shape(slide, x - 30_000, y - 30_000, w + 60_000, h + 60_000, fill=INK, stroke=INK)
    rid = f"rId{len(rels) + 2}"
    rels.append((rid, path))
    pic_id = 200 + len(slide)
    slide.append(
        f'<p:pic><p:nvPicPr><p:cNvPr id="{pic_id}" name="{esc(path.name)}"/><p:cNvPicPr preferRelativeResize="0"/><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr>{off_ext(dx, dy, dw, dh)}<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )


def add_grid(slide: list[str]) -> None:
    shape(slide, 0, 0, W, H, fill=PAPER)
    step = 420_000
    for x in range(0, W + 1, step):
        shape(slide, x, 0, 2_000, H, fill=DEEP)
    for y in range(0, H + 1, step):
        shape(slide, 0, y, W, 2_000, fill=DEEP)


def eyebrow(slide: list[str], x: int, y: int, text: str, color: str = GREEN, w: int = 4_000_000) -> None:
    text_box(slide, x, y, w, 260_000, text.upper(), size=10, color=color, bold=True)


def footer(slide: list[str], number: int) -> None:
    shape(slide, 500_000, 6_500_000, 11_200_000, 2_000, fill=LINE)
    text_box(slide, 500_000, 6_550_000, 9_500_000, 180_000,
             "BOTANIKA  ·  GEG XR HACKATHON 2026  ·  LOCAL-FIRST FIELD INTELLIGENCE",
             size=8, color=FAINT, bold=True)
    text_box(slide, 11_250_000, 6_550_000, 450_000, 180_000, f"0{number}", size=9, color=GREEN, bold=True, align="r")


def slide_one() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    shape(s, 0, 0, 220_000, H, fill=GREEN)
    shape(s, 700_000, 780_000, 6_050_000, 4_850_000, fill=SURFACE, stroke=INK, radius=True)
    eyebrow(s, 1_000_000, 1_050_000, "PI-POWERED FIELD INTELLIGENCE")
    text_box(s, 960_000, 1_430_000, 5_300_000, 900_000, "Botanika", size=54, font="Georgia", bold=True)
    text_box(s, 990_000, 2_390_000, 5_150_000, 1_050_000,
             "Raspberry Pi intelligence.\nAny phone as the field interface.",
             size=28, font="Georgia", color=GREEN, bold=True)
    text_box(s, 1_000_000, 3_620_000, 5_200_000, 850_000,
             "The phone supplies a browser and camera. The Pi supplies the models, botanical knowledge, storage, and decisions—over an optional secure remote link or an offline private Wi-Fi fallback.",
             size=16, color=MUTED)
    shape(s, 1_000_000, 4_760_000, 5_100_000, 500_000, fill=GREEN, stroke=GREEN, radius=True)
    text_box(s, 1_180_000, 4_900_000, 4_750_000, 190_000,
             "NO APP INSTALL  ·  NO MODEL ON THE PHONE  ·  CROP-ONLY PLANT UPLOAD",
             size=10, color=SURFACE, bold=True, align="c")

    shape(s, 7_180_000, 780_000, 4_300_000, 4_850_000, fill=DEEP, stroke=INK, radius=True)
    eyebrow(s, 7_520_000, 1_050_000, "ONE SYSTEM · TWO SURFACES", GREEN, 3_500_000)
    add_image(s, rels, shot("home"), 7_520_000, 1_520_000, 3_550_000, 1_850_000)
    text_box(s, 7_520_000, 3_460_000, 3_550_000, 230_000, "PI KIOSK  ·  AUTHORITATIVE CONSOLE", size=10, color=GREEN, bold=True, align="c")
    add_image(s, rels, live_shot("home"), 8_370_000, 3_850_000, 1_850_000, 1_350_000)
    text_box(s, 7_520_000, 5_250_000, 3_550_000, 230_000, "LIVE PHONE  ·  RESPONSIVE CONTROLLER", size=10, color=OCHRE, bold=True, align="c")
    text_box(s, 1_000_000, 5_850_000, 5_100_000, 250_000, "TEAM BOTANIKA  ·  ABHINAV KISORE", size=10, color=GREEN, bold=True)
    footer(s, 1)
    return s, rels


def slide_two() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "01  ·  ACTUAL REMOTE WORKFLOW")
    text_box(s, 600_000, 780_000, 9_400_000, 600_000, "Pair once. Send only what the Pi needs.", size=31, font="Georgia", bold=True)
    text_box(s, 600_000, 1_340_000, 10_300_000, 360_000,
             "The remote path is a browser-to-Pi handoff—not a mobile AI app and not remote desktop control.", size=15, color=MUTED)

    add_image(s, rels, live_shot("pair"), 650_000, 1_900_000, 2_200_000, 3_750_000)
    text_box(s, 650_000, 5_760_000, 2_200_000, 220_000, "LIVE PAIRING SCREEN", size=10, color=GREEN, bold=True, align="c")

    steps = [
        ("1", "Pi opens access", "Operator enters NETWORKED. The Pi starts a temporary HTTPS Quick Tunnel; its private Wi-Fi AP remains the offline fallback."),
        ("2", "Phone pairs", "The Pi shows a QR link and one-time code. The first successful browser receives the only active, revocable controller lease."),
        ("3", "Browser prepares", "The phone owns its camera preview, captures one still, limits it to 2048 px, applies the manual crop, checks quality, and computes SHA-256."),
        ("4", "Pi decides", "Only the approved JPEG crop, hash, dimensions, and request ID are posted. The Pi validates them, classifies, and returns the result."),
        ("5", "Pi records", "Only an accepted result can be saved. Optional phone location is added at save time; the Pi keeps the authoritative SQLite record and image."),
    ]
    for i, (num, title, body) in enumerate(steps):
        y = 1_900_000 + i * 790_000
        shape(s, 3_250_000, y, 8_250_000, 620_000, fill=SURFACE if i % 2 == 0 else DEEP, stroke=LINE, radius=True)
        shape(s, 3_250_000, y, 600_000, 620_000, fill=GREEN if i < 4 else OCHRE, stroke=GREEN if i < 4 else OCHRE, radius=True)
        text_box(s, 3_400_000, y + 145_000, 300_000, 220_000, num, size=16, color=SURFACE, bold=True, align="c")
        text_box(s, 4_050_000, y + 95_000, 1_750_000, 220_000, title, size=15, font="Georgia", bold=True)
        text_box(s, 5_750_000, y + 55_000, 5_450_000, 510_000, body, size=10, color=MUTED, margin=10_000)
    footer(s, 2)
    return s, rels


def slide_three() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "02  ·  TECHNICAL ARCHITECTURE")
    text_box(s, 600_000, 780_000, 9_100_000, 600_000, "The phone never becomes the compute node", size=31, font="Georgia", bold=True)
    text_box(s, 600_000, 1_350_000, 10_300_000, 340_000,
             "One React interface spans the Pi kiosk and paired browser; FastAPI on the Pi is the single backend contract and source of truth.", size=15, color=MUTED)

    cards = [
        (700_000, "PHONE · THIN CLIENT", GREEN,
         "• Responsive UI served by the Pi\n• getUserMedia or still-file capture\n• Local preview, crop, quality check\n• ≤2048 px JPEG + SHA-256\n• Result rendering + optional location\n\nNo model weights. No database. No live plant video upload."),
        (4_380_000, "SECURE TRANSPORT", OCHRE,
         "• Same-origin /api/v1 requests\n• Temporary trycloudflare HTTPS URL\n• QR + one-time pairing code\n• One bearer lease; heartbeat + polling\n• Hash/dimensions/request ID travel with crop\n\nPrivate Pi Wi-Fi is the no-internet fallback."),
        (8_060_000, "RASPBERRY PI · AUTHORITY", RUST,
         "• FastAPI mode + authorization\n• OpenCV/NumPy plant classifier\n• Separate ONNX weed beta\n• SQLite + FTS knowledge/library\n• Crop provenance and save checks\n• Local kiosk, camera, voice services\n\nInference, policy, knowledge, and persistence stay here."),
    ]
    for x, label, accent, body in cards:
        shape(s, x, 1_950_000, 3_430_000, 3_720_000, fill=SURFACE, stroke=accent, radius=True)
        shape(s, x, 1_950_000, 3_430_000, 520_000, fill=accent, stroke=accent, radius=True)
        text_box(s, x + 200_000, 2_100_000, 3_000_000, 190_000, label, size=11, color=SURFACE, bold=True, align="c")
        text_box(s, x + 250_000, 2_690_000, 2_930_000, 2_600_000, body, size=13, color=MUTED)
    text_box(s, 4_050_000, 3_230_000, 300_000, 300_000, "→", size=24, color=GREEN, bold=True, align="c")
    text_box(s, 7_730_000, 3_230_000, 300_000, 300_000, "→", size=24, color=GREEN, bold=True, align="c")
    shape(s, 700_000, 5_900_000, 10_790_000, 420_000, fill=DEEP, stroke=LINE, radius=True)
    text_box(s, 900_000, 6_020_000, 10_390_000, 180_000,
             "PLANT PATH · one approved crop per request   |   WEED PATH · bounded JPEG samples, never a MediaStream; no overlap while Pi inference runs",
             size=9, color=INK, bold=True, align="c")
    footer(s, 3)
    return s, rels


def slide_four() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "03  ·  LIVE CROSS-NETWORK EVIDENCE")
    text_box(s, 600_000, 780_000, 10_000_000, 600_000, "The remote phone ↔ Pi path is visible in the test captures", size=31, font="Georgia", bold=True)
    text_box(s, 600_000, 1_350_000, 10_700_000, 330_000,
             "Real handset screenshots show the temporary HTTPS origin, pairing, crop handoff, honest abstention, and the separate weed-beta response.", size=15, color=MUTED)
    proof = [
        (live_shot("pair"), "1 · PAIR", "Temporary HTTPS + one-time code"),
        (live_shot("crop"), "2 · SEND CROP", "Local checks pass before upload"),
        (live_shot("result"), "3 · PI RESPONSE", "Low confidence remains unsaved"),
        (live_shot("weed"), "4 · WEED BETA", "Boxes returned; image discarded"),
    ]
    for i, (path, label, detail) in enumerate(proof):
        x = 650_000 + i * 2_820_000
        add_image(s, rels, path, x, 1_900_000, 2_350_000, 3_550_000)
        text_box(s, x, 5_550_000, 2_350_000, 190_000, label, size=10, color=GREEN if i < 3 else OCHRE, bold=True, align="c")
        text_box(s, x, 5_800_000, 2_350_000, 280_000, detail, size=10, color=MUTED, align="c")
    text_box(s, 600_000, 6_180_000, 10_950_000, 190_000,
             "Evidence boundary · these captures prove the live interaction path; they do not claim production-grade species accuracy.", size=10, color=RUST, bold=True, align="c")
    footer(s, 4)
    return s, rels


def slide_five() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "04  ·  LIGHTWEIGHT BY DESIGN")
    text_box(s, 600_000, 780_000, 9_000_000, 600_000, "The user carries a camera and a webpage—not the AI stack", size=31, font="Georgia", bold=True)

    shape(s, 600_000, 1_720_000, 5_200_000, 3_920_000, fill=SURFACE, stroke=GREEN, radius=True)
    eyebrow(s, 900_000, 2_020_000, "ON THE PHONE", GREEN, 3_900_000)
    text_box(s, 900_000, 2_400_000, 4_400_000, 520_000, "Short-lived interface work", size=22, font="Georgia", bold=True)
    text_box(s, 900_000, 3_030_000, 4_400_000, 1_750_000,
         "• Browser UI loaded from the Pi\n• Camera preview stays on-device\n• One resized, manually approved plant crop\n• Local quality check + SHA-256\n• Optional plant-save / weed coordinates\n• Result display, heartbeat, and polling",
             size=16, color=MUTED)
    shape(s, 900_000, 5_040_000, 4_350_000, 360_000, fill=DEEP, stroke=LINE, radius=True)
    text_box(s, 1_020_000, 5_140_000, 4_100_000, 160_000, "NO INSTALL  ·  NO WEIGHTS  ·  NO LOCAL DATABASE", size=10, color=GREEN, bold=True, align="c")

    shape(s, 6_250_000, 1_720_000, 5_250_000, 3_920_000, fill=DEEP, stroke=RUST, radius=True)
    eyebrow(s, 6_550_000, 2_020_000, "ON THE RASPBERRY PI", RUST, 4_200_000)
    text_box(s, 6_550_000, 2_400_000, 4_500_000, 520_000, "Long-lived intelligence and evidence", size=22, font="Georgia", bold=True)
    text_box(s, 6_550_000, 3_030_000, 4_450_000, 1_750_000,
             "• Pairing, authorization, and mode state\n• Plant and weed inference runtimes\n• Confidence / acceptance policy\n• Botanical catalog, FTS knowledge, citations\n• Discovery images, notes, and map records\n• Pi camera, kiosk, local voice, and exports",
             size=16, color=MUTED)
    shape(s, 6_550_000, 5_040_000, 4_350_000, 360_000, fill=RUST, stroke=RUST, radius=True)
    text_box(s, 6_700_000, 5_140_000, 4_050_000, 160_000, "PI REMAINS THE SOURCE OF TRUTH", size=10, color=SURFACE, bold=True, align="c")
    text_box(s, 600_000, 5_910_000, 10_950_000, 370_000,
             "Privacy boundary · plant video is never streamed to the Pi. Weed samples are bounded still JPEGs, processed in memory and discarded; only supported detections with validated coordinates may persist.",
             size=11, color=INK, bold=True, align="c")
    footer(s, 5)
    return s, rels


def slide_six() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "05  ·  MODES, GUARANTEES + LIMITS")
    text_box(s, 600_000, 780_000, 9_500_000, 600_000, "Three access paths. One authoritative backend.", size=31, font="Georgia", bold=True)
    columns = [
        ("SOLO · OFFLINE", GREEN, "Pi kiosk + Pi Camera\nFastAPI bound to loopback\nModels, knowledge, voice, and library local\nNo phone or network required"),
        ("PRIVATE AP · OFFLINE", OCHRE, "Phone joins Botanika Wi-Fi\nSame pairing and crop API\nFirewall blocks forwarding\nFallback when internet is unavailable"),
        ("QUICK TUNNEL · REMOTE", RUST, "Phone may use another network\nTemporary HTTPS URL + QR\nPi backend remains loopback-only\nDevelopment/test transport; no SLA"),
    ]
    for i, (label, accent, body) in enumerate(columns):
        x = 600_000 + i * 3_880_000
        shape(s, x, 1_850_000, 3_450_000, 2_650_000, fill=SURFACE, stroke=accent, radius=True)
        text_box(s, x + 280_000, 2_180_000, 2_850_000, 250_000, label, size=12, color=accent, bold=True)
        text_box(s, x + 280_000, 2_650_000, 2_850_000, 1_400_000, body, size=16, color=MUTED)
    shape(s, 600_000, 4_850_000, 10_950_000, 1_050_000, fill=GREEN, stroke=GREEN, radius=True)
    text_box(s, 900_000, 5_050_000, 2_050_000, 250_000, "FAIL-CLOSED CONTRACT", size=11, color=SURFACE, bold=True)
    text_box(s, 2_950_000, 5_000_000, 8_100_000, 520_000,
             "One active controller  ·  lease revoked on SOLO / disconnect / expiry / takeover / restart  ·  stale crop and save rejected  ·  uncertain stays visible",
             size=16, color=SURFACE, bold=True)
    text_box(s, 600_000, 6_090_000, 10_800_000, 300_000,
             "Current limit · production identification remains gated until held-out field accuracy and Raspberry Pi latency / memory / thermal benchmarks pass.",
             size=11, color=RUST, bold=True, align="c", margin=10_000)
    footer(s, 6)
    return s, rels


def slide_xml(shapes: list[str], name: str) -> str:
    group = (
        '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        + "".join(shapes)
        + "</p:spTree>"
    )
    return f'<p:sld xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}"><p:cSld name="{esc(name)}">{group}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'


def write_pptx(output: Path) -> None:
    builders = [slide_one, slide_two, slide_three, slide_four, slide_five, slide_six]
    slides = []
    all_rels: list[list[tuple[str, Path]]] = []
    for builder in builders:
        content, rels = builder()
        slides.append(content)
        all_rels.append(rels)

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Default Extension="png" ContentType="image/png"/>',
        '<Default Extension="jpg" ContentType="image/jpeg"/>',
        '<Default Extension="jpeg" ContentType="image/jpeg"/>',
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for i in range(len(slides)):
        content_types.append(f'<Override PartName="/ppt/slides/slide{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
    content_types.append('</Types>')

    root_rels = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{NS_REL}">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

    pres_rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', f'<Relationships xmlns="{NS_REL}">', '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
    for i in range(len(slides)):
        pres_rels.append(f'<Relationship Id="rId{i + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i + 1}.xml"/>')
    pres_rels.append('</Relationships>')

    presentation = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">
<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
<p:sldIdLst>{"".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>' for i in range(len(slides)))}</p:sldIdLst>
<p:sldSz cx="{W}" cy="{H}" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/>
<p:defaultTextStyle><a:defPPr/><a:lvl1pPr marL="0" algn="l"><a:defRPr sz="1800"/></a:lvl1pPr></p:defaultTextStyle>
</p:presentation>'''

    master = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}"><p:cSld name="Master"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="1" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>'''
    layout = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'''
    theme = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="{NS_A}" name="Botanika"><a:themeElements><a:clrScheme name="Botanika"><a:dk1><a:srgbClr val="{INK}"/></a:dk1><a:lt1><a:srgbClr val="{PAPER}"/></a:lt1><a:dk2><a:srgbClr val="{MUTED}"/></a:dk2><a:lt2><a:srgbClr val="{SURFACE}"/></a:lt2><a:accent1><a:srgbClr val="{GREEN}"/></a:accent1><a:accent2><a:srgbClr val="{OCHRE}"/></a:accent2><a:accent3><a:srgbClr val="{RUST}"/></a:accent3><a:accent4><a:srgbClr val="{DEEP}"/></a:accent4><a:accent5><a:srgbClr val="{LINE}"/></a:accent5><a:accent6><a:srgbClr val="{FAINT}"/></a:accent6><a:hlink><a:srgbClr val="{GREEN}"/></a:hlink><a:folHlink><a:srgbClr val="{RUST}"/></a:folHlink></a:clrScheme><a:fontScheme name="Botanika"><a:majorFont><a:latin typeface="Georgia"/></a:majorFont><a:minorFont><a:latin typeface="Arial"/></a:minorFont></a:fontScheme><a:fmtScheme name="Botanika"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme></a:themeElements></a:theme>'''

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("ppt/presentation.xml", presentation)
        zf.writestr("ppt/_rels/presentation.xml.rels", "".join(pres_rels))
        zf.writestr("ppt/slideMasters/slideMaster1.xml", master)
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{NS_REL}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>''')
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{NS_REL}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>''')
        zf.writestr("ppt/theme/theme1.xml", theme)
        zf.writestr("docProps/core.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Botanika — Field Intelligence for India’s Native Flora</dc:title><dc:subject>GEG XR Hackathon 2026</dc:subject><dc:creator>Team Botanika</dc:creator></cp:coreProperties>')
        zf.writestr("docProps/app.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Botanika presentation generator</Application><PresentationFormat>Widescreen</PresentationFormat><Slides>6</Slides></Properties>')
        for i, content in enumerate(slides, 1):
            zf.writestr(f"ppt/slides/slide{i}.xml", slide_xml(content, f"Botanika slide {i}"))
            rel_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', f'<Relationships xmlns="{NS_REL}">', '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>']
            for rid, path in all_rels[i - 1]:
                extension = path.suffix.lower().lstrip(".") or "png"
                if extension not in {"png", "jpg", "jpeg"}:
                    extension = "png"
                media_name = f"image-{i}-{len(rel_xml)}.{extension}"
                rel_xml.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/{media_name}"/>')
            rel_xml.append('</Relationships>')
            zf.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", "".join(rel_xml))
            for index, (_, path) in enumerate(all_rels[i - 1], start=1):
                extension = path.suffix.lower().lstrip(".") or "png"
                if extension not in {"png", "jpg", "jpeg"}:
                    extension = "png"
                zf.writestr(f"ppt/media/image-{i}-{index + 2}.{extension}", path.read_bytes())


def main() -> int:
    global SCREENSHOTS, LIVE_SCREENSHOTS, PI_MODE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--screenshots", type=Path, default=SCREENSHOTS)
    parser.add_argument("--live-screenshots", type=Path, default=LIVE_SCREENSHOTS)
    parser.add_argument("--pi", action="store_true", help="Use the 800x480 Pi walkthrough evidence")
    args = parser.parse_args()
    SCREENSHOTS = args.screenshots
    LIVE_SCREENSHOTS = args.live_screenshots
    PI_MODE = args.pi
    required = [
        shot("home"),
        shot("loaded"),
        shot("identified"),
        shot("weed"),
        live_shot("pair"),
        live_shot("home"),
        live_shot("crop"),
        live_shot("result"),
        live_shot("weed"),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing captured screenshots: " + ", ".join(missing))
    write_pptx(args.output)
    print(f"Created {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
