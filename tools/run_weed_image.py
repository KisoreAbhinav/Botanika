#!/usr/bin/env python3
"""Run the installed Botanika weed-beta model on one saved image."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import AppSettings
from botanika.vision.weeds import WeedService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.35)
    args = parser.parse_args()
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"could not decode image: {args.image}")

    settings = AppSettings(
        weed_confidence=args.confidence,
        weed_manifest_path=PROJECT_ROOT / "config" / "weed" / "phase9-beta.json",
    )
    service = WeedService(settings)
    result = service.detect_image(image, include_frame=False)
    annotated = image.copy()
    for item in result.get("detections", []):
        box = item["box"]
        x1, y1 = round(box["x1"]), round(box["y1"])
        x2, y2 = round(box["x2"]), round(box["y2"])
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (46, 105, 138), 3)
        label = f'{item["weed_class"]} {float(item["confidence"]):.0%}'
        cv2.rectangle(annotated, (x1, max(0, y1 - 30)), (x1 + 150, y1), (46, 105, 138), -1)
        cv2.putText(annotated, label, (x1 + 8, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (242, 242, 242), 2, cv2.LINE_AA)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), annotated):
        raise SystemExit(f"could not write annotated image: {args.output}")
    args.json.write_text(json.dumps({
        "input": str(args.image),
        "model": service.detector_version,
        "confidence_threshold": args.confidence,
        "image_width": int(image.shape[1]),
        "image_height": int(image.shape[0]),
        "result": result,
    }, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
