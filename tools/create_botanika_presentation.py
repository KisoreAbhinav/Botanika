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
             align: str = "l", valign: str = "t", margin: int = 100) -> None:
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
    shape(s, 760_000, 920_000, 5_450_000, 3_800_000, fill=SURFACE, stroke=INK, radius=True)
    eyebrow(s, 1_050_000, 1_180_000, "LOCAL FIELD INTELLIGENCE")
    text_box(s, 1_020_000, 1_650_000, 5_000_000, 1_350_000, "Botanika", size=56, font="Georgia", bold=True)
    text_box(s, 1_050_000, 3_080_000, 4_600_000, 650_000, "An AR + AI assistant for\nIndia’s native flora", size=25, font="Georgia", color=GREEN, bold=True)
    text_box(s, 1_050_000, 4_060_000, 4_400_000, 350_000, "Scan  ·  understand  ·  conserve", size=15, color=MUTED, bold=True)
    shape(s, 7_100_000, 950_000, 4_100_000, 5_200_000, fill=DEEP, stroke=INK, radius=True)
    text_box(s, 7_450_000, 1_310_000, 3_300_000, 800_000, "Turn a phone into a\nbiodiversity field assistant.", size=28, font="Georgia", bold=True)
    text_box(s, 7_470_000, 2_450_000, 3_150_000, 1_250_000,
             "A campus-focused prototype combining plant identification, AR-style context, an offline botanical guide, and conservation-aware discovery records.",
             size=16, color=MUTED)
    add_image(s, rels, shot("home"), 8_150_000, 3_920_000, 2_150_000, 1_650_000)
    shape(s, 1_050_000, 5_250_000, 4_900_000, 470_000, fill=GREEN, stroke=GREEN, radius=True)
    text_box(s, 1_250_000, 5_380_000, 4_500_000, 190_000, "TEAM BOTANIKA  ·  MEMBERS TO BE ADDED", size=10, color=SURFACE, bold=True)
    footer(s, 1)
    return s, rels


def slide_two() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "01  ·  SOLUTION OVERVIEW")
    text_box(s, 600_000, 780_000, 7_000_000, 600_000, "From plant sighting to local knowledge", size=31, font="Georgia", bold=True)
    shape(s, 600_000, 1_650_000, 3_350_000, 3_950_000, fill=SURFACE, stroke=INK, radius=True)
    eyebrow(s, 900_000, 1_960_000, "THE GAP", RUST, 2_000_000)
    text_box(s, 900_000, 2_380_000, 2_650_000, 700_000, "Native plants are\nvisible but overlooked.", size=23, font="Georgia", bold=True)
    text_box(s, 900_000, 3_300_000, 2_650_000, 1_500_000,
             "• Scientific context is scattered\n• Field identification can be uncertain\n• Conservation action needs local evidence\n• Connectivity cannot be assumed", size=16, color=MUTED)
    text_box(s, 900_000, 5_020_000, 2_650_000, 350_000, "Pilot lens: campus / garden / biodiversity park", size=12, color=GREEN, bold=True)
    text_box(s, 4_480_000, 1_760_000, 6_900_000, 300_000, "USER JOURNEY  ·  ONE CLEAR LOOP", size=11, color=GREEN, bold=True)
    nodes = [("01", "Find", "Open Scan or Weed Detection"), ("02", "Frame", "Hold steady; crop the target"), ("03", "Learn", "Name, family, ecology, status"), ("04", "Keep", "Save a discovery and build the campus record")]
    for index, (num, title, body) in enumerate(nodes):
        x = 4_480_000 + index * 1_720_000
        shape(s, x, 2_350_000, 1_320_000, 2_500_000, fill=SURFACE, stroke=LINE, radius=True)
        text_box(s, x + 160_000, 2_600_000, 850_000, 300_000, num, size=12, color=GREEN, bold=True)
        text_box(s, x + 150_000, 3_080_000, 1_020_000, 350_000, title, size=20, font="Georgia", bold=True)
        text_box(s, x + 150_000, 3_650_000, 1_020_000, 900_000, body, size=12, color=MUTED)
        if index < 3:
            shape(s, x + 1_340_000, 3_540_000, 350_000, 20_000, fill=GREEN)
    shape(s, 4_480_000, 5_250_000, 6_900_000, 410_000, fill=DEEP, stroke=LINE, radius=True)
    text_box(s, 4_700_000, 5_370_000, 6_400_000, 170_000,
             "Minimum brief fit: 7-species starter catalog  ·  offline guide  ·  regional library  ·  conservation-aware copy",
             size=11, color=INK, bold=True)
    footer(s, 2)
    return s, rels


def slide_three() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "02  ·  TECHNICAL ARCHITECTURE")
    text_box(s, 600_000, 780_000, 6_600_000, 600_000, "One Pi owns the intelligence", size=31, font="Georgia", bold=True)
    text_box(s, 600_000, 1_360_000, 7_000_000, 360_000, "Offline by default. The phone is a responsive controller; the Raspberry Pi remains the source of truth.", size=15, color=MUTED)
    layers = [
        ("FIELD INPUT", "Pi Camera  ·  phone camera  ·  saved image fallback", GREEN),
        ("INTERACTION", "React + Vite  ·  fixed 800×480 kiosk  ·  responsive paired client", INK),
        ("LOCAL SERVICES", "FastAPI  ·  OpenCV / ONNX  ·  crop quality + lock-on + AR-style overlay", OCHRE),
        ("AUTHORITATIVE DATA", "SQLite  ·  discovery library  ·  offline knowledge base  ·  coordinate-only weed runs", RUST),
    ]
    for i, (label, body, accent) in enumerate(layers):
        y = 2_040_000 + i * 770_000
        shape(s, 700_000, y, 6_300_000, 550_000, fill=SURFACE if i % 2 == 0 else DEEP, stroke=LINE, radius=True)
        shape(s, 700_000, y, 160_000, 550_000, fill=accent, stroke=accent)
        text_box(s, 1_050_000, y + 95_000, 1_600_000, 180_000, label, size=10, color=accent, bold=True)
        text_box(s, 2_700_000, y + 90_000, 4_000_000, 280_000, body, size=14, color=INK)
        if i < len(layers) - 1:
            shape(s, 3_770_000, y + 560_000, 20_000, 190_000, fill=LINE)
    shape(s, 7_450_000, 2_040_000, 4_050_000, 3_620_000, fill=SURFACE, stroke=INK, radius=True)
    eyebrow(s, 7_800_000, 2_350_000, "ENGINEERING CONTRACT", GREEN, 3_100_000)
    text_box(s, 7_800_000, 2_790_000, 3_350_000, 2_200_000,
             "• Single camera owner; stale frames dropped\n• Classify only an accepted padded crop\n• Unknown / low-confidence stays visible\n• Image provenance and model metadata retained\n• Weed images are transient; only validated metadata can persist\n• Local AP / Quick Tunnel pairing is optional",
             size=15, color=MUTED)
    shape(s, 7_800_000, 5_050_000, 3_300_000, 340_000, fill=GREEN, stroke=GREEN, radius=True)
    text_box(s, 8_000_000, 5_145_000, 2_900_000, 160_000, "PI 5  ·  16 GB  ·  512 GB SSD", size=11, color=SURFACE, bold=True, align="c")
    footer(s, 3)
    return s, rels


def slide_four() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "03  ·  PROTOTYPE PROOF")
    if PI_MODE:
        text_box(s, 600_000, 780_000, 9_500_000, 600_000, "A working Pi loop, captured at 800 × 480", size=31, font="Georgia", bold=True)
        text_box(s, 600_000, 1_380_000, 10_500_000, 320_000, "Saved campus image → local crop quality → Pi classifier response → library + map save. The beta weed cue stays visibly separate.", size=15, color=MUTED)
        add_image(s, rels, shot("loaded"), 600_000, 2_000_000, 3_550_000, 2_750_000)
        add_image(s, rels, shot("identified"), 4_350_000, 2_000_000, 3_550_000, 2_750_000)
        add_image(s, rels, shot("weed"), 8_100_000, 2_000_000, 3_450_000, 2_750_000)
        text_box(s, 720_000, 4_900_000, 3_300_000, 330_000, "01  ·  LOAD SAVED IMAGE", size=11, color=GREEN, bold=True, align="c")
        text_box(s, 4_470_000, 4_900_000, 3_300_000, 330_000, "02  ·  IDENTIFY + SAVE", size=11, color=GREEN, bold=True, align="c")
        text_box(s, 8_200_000, 4_900_000, 3_250_000, 330_000, "03  ·  MAIZE / WEED CUE", size=11, color=OCHRE, bold=True, align="c")
        shape(s, 600_000, 5_420_000, 10_950_000, 650_000, fill=SURFACE, stroke=GREEN, radius=True)
        text_box(s, 900_000, 5_590_000, 10_350_000, 200_000, "DEMO VIDEO  ·  25.9 s slow Pi walkthrough  ·  botanika-pi-demo-slow.mp4", size=14, color=GREEN, bold=True, align="c")
        text_box(s, 600_000, 6_160_000, 10_950_000, 220_000, "The saved record is marked synthetic: R-block east planting bed, VIT Vellore · 12.96930, 79.15650.", size=11, color=FAINT, align="c")
    else:
        text_box(s, 600_000, 780_000, 8_000_000, 600_000, "A working phone loop, captured from the built UI", size=31, font="Georgia", bold=True)
        text_box(s, 600_000, 1_380_000, 8_800_000, 320_000, "Saved campus image → local crop quality → Pi classifier response → library save. The beta weed cue remains visibly separate.", size=15, color=MUTED)
        add_image(s, rels, shot("loaded"), 700_000, 2_000_000, 2_550_000, 3_950_000)
        add_image(s, rels, shot("identified"), 3_700_000, 2_000_000, 2_550_000, 3_950_000)
        add_image(s, rels, shot("weed"), 6_700_000, 2_000_000, 4_700_000, 2_820_000)
        shape(s, 6_700_000, 5_050_000, 4_700_000, 900_000, fill=SURFACE, stroke=GREEN, radius=True)
        text_box(s, 7_000_000, 5_260_000, 4_100_000, 350_000, "DEMO VIDEO  ·  11.8 s", size=13, color=GREEN, bold=True)
        text_box(s, 7_000_000, 5_610_000, 4_100_000, 200_000, "botanika-phone-demo.mp4", size=12, color=MUTED, italic=True)
        text_box(s, 700_000, 6_050_000, 5_700_000, 220_000, "Screens 1–2: load and identify  ·  Screen 3: weed cue and coordinate guard", size=11, color=FAINT)
    footer(s, 4)
    return s, rels


def slide_five() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "04  ·  IMPACT + USER VALIDATION")
    text_box(s, 600_000, 780_000, 9_000_000, 600_000, "Conservation value needs local evidence", size=31, font="Georgia", bold=True)
    shape(s, 600_000, 1_700_000, 5_200_000, 4_150_000, fill=SURFACE, stroke=INK, radius=True)
    eyebrow(s, 900_000, 2_020_000, "WHAT THE SYSTEM ENABLES", GREEN, 3_900_000)
    text_box(s, 900_000, 2_430_000, 4_400_000, 2_700_000,
             "• Make native flora legible to non-specialists\n• Pair every sighting with ecology, family, and conservation context\n• Grow a species-grouped campus discovery library\n• Keep uncertain answers honest and actionable\n• Support offline field work where connectivity is weak\n• Create a future evidence base for restoration and stewardship",
             size=16, color=MUTED)
    shape(s, 900_000, 5_050_000, 4_450_000, 440_000, fill=DEEP, stroke=LINE, radius=True)
    text_box(s, 1_100_000, 5_170_000, 4_050_000, 180_000, "Alignment: NGCPR  ·  native species  ·  public outreach", size=11, color=GREEN, bold=True)
    shape(s, 6_250_000, 1_700_000, 5_250_000, 4_150_000, fill=DEEP, stroke=OCHRE, radius=True)
    eyebrow(s, 6_550_000, 2_020_000, "ILLUSTRATIVE UX READOUT", OCHRE, 4_200_000)
    text_box(s, 6_550_000, 2_360_000, 4_500_000, 420_000, "Mixed opinions to validate with 5 real users", size=22, font="Georgia", bold=True)
    text_box(s, 6_550_000, 2_930_000, 4_450_000, 1_900_000,
             "LIKED  ·  The single Scan → crop → save loop is easy to explain.\n\nMIXED  ·  The manual crop slider helps control the result, but is unfamiliar on first use.\n\nCONCERN  ·  Camera permission and “why local?” need a clearer first-run cue.\n\nRESPONSE  ·  Stream reattachment, saved-image fallback, visible quality checks, and local-first copy.",
             size=14, color=MUTED)
    text_box(s, 6_550_000, 5_080_000, 4_450_000, 420_000, "STATUS  ·  Real five-person study still required before submission.", size=11, color=RUST, bold=True)
    footer(s, 5)
    return s, rels


def slide_six() -> tuple[list[str], list[tuple[str, Path]]]:
    s, rels = [], []
    add_grid(s)
    eyebrow(s, 600_000, 480_000, "05  ·  ROADMAP + SCALE")
    text_box(s, 600_000, 780_000, 9_500_000, 600_000, "Start on one campus. Scale the field intelligence layer.", size=31, font="Georgia", bold=True)
    columns = [
        ("NOW", GREEN, "Stabilise phone camera + crop flow\nComplete five-user validation\nAdd accepted local campus images\nBenchmark Pi latency and confidence"),
        ("NEXT", OCHRE, "Calibrate the seven-species catalog\nExpand regional checklist and map\nAdd multilingual botanical guidance\nIntroduce richer AR-style annotations"),
        ("LATER", RUST, "Campus → city biodiversity network\nRestoration and nursery workflows\nAgriculture and sustainability scouting\nEnvironmental monitoring APIs"),
    ]
    for i, (label, accent, body) in enumerate(columns):
        x = 600_000 + i * 3_880_000
        shape(s, x, 1_850_000, 3_450_000, 2_650_000, fill=SURFACE, stroke=accent, radius=True)
        text_box(s, x + 280_000, 2_180_000, 2_850_000, 250_000, label, size=12, color=accent, bold=True)
        text_box(s, x + 280_000, 2_650_000, 2_850_000, 1_400_000, body, size=16, color=MUTED)
    shape(s, 600_000, 4_850_000, 10_950_000, 1_050_000, fill=GREEN, stroke=GREEN, radius=True)
    text_box(s, 900_000, 5_060_000, 10_350_000, 250_000, "WHY IT CAN SCALE", size=11, color=SURFACE, bold=True)
    text_box(s, 2_550_000, 5_040_000, 8_450_000, 400_000, "One local backend contract  ·  pluggable catalogs  ·  privacy-preserving crop uploads  ·  structured provenance", size=18, color=SURFACE, bold=True)
    text_box(s, 600_000, 6_120_000, 10_800_000, 260_000,
             "Judging fit  ·  Innovation 15%  ·  Technical execution 20%  ·  AI + AR 20%  ·  UX + validation 10%  ·  NGCPR alignment 20%  ·  Presentation 15%",
             size=11, color=INK, bold=True, align="c")
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
                media_name = f"image-{i}-{len(rel_xml)}.png"
                rel_xml.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/{media_name}"/>')
            rel_xml.append('</Relationships>')
            zf.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", "".join(rel_xml))
            for index, (_, path) in enumerate(all_rels[i - 1], start=1):
                zf.writestr(f"ppt/media/image-{i}-{index + 2}.png", path.read_bytes())


def main() -> int:
    global SCREENSHOTS, PI_MODE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--screenshots", type=Path, default=SCREENSHOTS)
    parser.add_argument("--pi", action="store_true", help="Use the 800x480 Pi walkthrough evidence")
    args = parser.parse_args()
    SCREENSHOTS = args.screenshots
    PI_MODE = args.pi
    required = [
        shot("home"),
        shot("loaded"),
        shot("identified"),
        shot("weed"),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing captured screenshots: " + ", ".join(missing))
    write_pptx(args.output)
    print(f"Created {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
