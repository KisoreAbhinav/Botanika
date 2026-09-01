#!/usr/bin/env python3
"""Run Botanika's Phase 2 generic YOLO detector on the Pi Camera.

Inference is deliberately synchronous: the camera loop reads one current frame,
runs one detector call, renders it, and only then requests the next frame. This
keeps a slow detector from accumulating an unbounded stale-frame queue.
Press ``q`` or ``Esc`` to quit.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
import time
from typing import Any, Callable

# Allow the script to run directly from a source checkout without installation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

import cv2
import numpy as np

from botanika.hardware.camera import CameraConfig, CameraError, CameraOwner, FrameReadError
from botanika.vision.detection import (
    Detection,
    DetectorError,
    DetectorInferenceError,
    DetectorMetrics,
    ModelManifest,
    YoloOnnxDetector,
    fit_frame_to_window,
)


LOGGER = logging.getLogger("botanika.phase2.detection")
DEFAULT_CONFIG = CameraConfig()
DEFAULT_MANIFEST = PROJECT_ROOT / "config" / "models" / "yolo11n-coco.json"
MAX_CONSECUTIVE_DROPS = 30
BOX_COLOR = (46, 105, 138)  # Warning ochre #8a692e in OpenCV BGR order.
TEXT_COLOR = (242, 242, 242)


@dataclass(slots=True)
class DetectionFeedStats:
    started_at: float
    rendered_frames: int = 0
    last_fps: float = 0.0
    frames_with_detections: int = 0
    detections_seen: int = 0

    def update(self, now: float, detection_count: int = 0) -> None:
        self.rendered_frames += 1
        self.detections_seen += detection_count
        if detection_count:
            self.frames_with_detections += 1
        self.last_fps = self.rendered_frames / max(now - self.started_at, 1e-9)


def draw_detection_frame(
    frame: np.ndarray,
    detections: list[Detection],
    detector: YoloOnnxDetector,
    stats: DetectionFeedStats,
    config: CameraConfig,
    *,
    cv2_module: Any = cv2,
) -> np.ndarray:
    """Fit the frame to the fixed window and draw every generic detection."""

    canvas, transform = fit_frame_to_window(
        frame,
        config.window_width,
        config.window_height,
        cv2_module=cv2_module,
    )
    for detection in detections:
        box = transform.to_display_box(detection.box)
        top_left = (round(box.x1), round(box.y1))
        bottom_right = (round(box.x2), round(box.y2))
        cv2_module.rectangle(canvas, top_left, bottom_right, BOX_COLOR, 2)
        label = f"{detection.label} {detection.confidence:.0%}"
        text_y = max(20, top_left[1] - 7)
        (text_width, text_height), baseline = cv2_module.getTextSize(
            label,
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.52,
            1,
        )
        cv2_module.rectangle(
            canvas,
            (top_left[0], max(0, text_y - text_height - baseline)),
            (min(config.window_width, top_left[0] + text_width + 8), text_y + 3),
            BOX_COLOR,
            -1,
        )
        cv2_module.putText(
            canvas,
            label,
            (top_left[0] + 4, text_y),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.52,
            TEXT_COLOR,
            1,
            cv2_module.LINE_AA,
        )

    cv2_module.rectangle(
        canvas,
        (0, 0),
        (config.window_width, 48),
        (24, 24, 24),
        -1,
    )
    diagnostic = (
        f"GENERIC YOLO  {len(detections)} BOXES  "
        f"FPS {stats.last_fps:4.1f}  "
        f"INF p50/p95 {detector.metrics.p50_ms:.0f}/{detector.metrics.p95_ms:.0f}ms"
    )
    cv2_module.putText(
        canvas,
        diagnostic,
        (10, 21),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.52,
        TEXT_COLOR,
        1,
        cv2_module.LINE_AA,
    )
    cv2_module.putText(
        canvas,
        "COCO labels only; not a plant-species classifier",
        (10, 41),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.42,
        (190, 190, 190),
        1,
        cv2_module.LINE_AA,
    )
    return canvas


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--nms-iou", type=float, default=0.45)
    parser.add_argument("--width", type=int, default=DEFAULT_CONFIG.width)
    parser.add_argument("--height", type=int, default=DEFAULT_CONFIG.height)
    parser.add_argument("--fps", type=int, default=DEFAULT_CONFIG.fps)
    parser.add_argument("--window-width", type=int, default=DEFAULT_CONFIG.window_width)
    parser.add_argument("--window-height", type=int, default=DEFAULT_CONFIG.window_height)
    parser.add_argument("--window-name", default="Botanika Detection")
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument(
        "--headless",
        action="store_true",
        help="capture and infer without opening an OpenCV window",
    )
    return parser


def make_config(args: argparse.Namespace) -> CameraConfig:
    if args.seconds is not None and args.seconds <= 0:
        raise ValueError("--seconds must be greater than zero")
    if args.max_frames is not None and args.max_frames <= 0:
        raise ValueError("--max-frames must be greater than zero")
    return CameraConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        window_width=args.window_width,
        window_height=args.window_height,
        window_name=args.window_name,
    )


def run_detection(
    config: CameraConfig,
    manifest: ModelManifest,
    *,
    confidence: float = 0.25,
    nms_iou: float = 0.45,
    seconds: float | None = None,
    max_frames: int | None = None,
    headless: bool = False,
    camera_factory: Callable[[], Any] | None = None,
    detector: YoloOnnxDetector | None = None,
    cv2_module: Any = cv2,
    clock: Callable[[], float] = time.monotonic,
) -> DetectionFeedStats:
    stats = DetectionFeedStats(started_at=clock())
    active_detector = detector or YoloOnnxDetector(
        manifest,
        confidence_threshold=confidence,
        nms_iou_threshold=nms_iou,
    )
    camera_kwargs: dict[str, Any] = {"config": config, "clock": clock}
    if camera_factory is not None:
        camera_kwargs["camera_factory"] = camera_factory
    camera = CameraOwner(**camera_kwargs)
    window_created = False
    consecutive_drops = 0

    try:
        active_detector.load()
        camera.open()
        if not headless:
            cv2_module.namedWindow(config.window_name, cv2_module.WINDOW_NORMAL)
            cv2_module.resizeWindow(
                config.window_name, config.window_width, config.window_height
            )
            window_created = True

        while True:
            try:
                captured = camera.read()
            except FrameReadError as exc:
                consecutive_drops += 1
                LOGGER.warning("Dropped camera frame: %s", exc)
                if not headless:
                    key = cv2_module.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        break
                if consecutive_drops >= MAX_CONSECUTIVE_DROPS:
                    raise CameraError(
                        "camera stopped delivering frames "
                        f"({consecutive_drops} consecutive drops)"
                    ) from exc
                continue

            consecutive_drops = 0
            detections = active_detector.detect(captured.image)
            stats.update(clock(), len(detections))
            if not headless:
                display_frame = draw_detection_frame(
                    captured.image,
                    detections,
                    active_detector,
                    stats,
                    config,
                    cv2_module=cv2_module,
                )
                cv2_module.imshow(config.window_name, display_frame)
                key = cv2_module.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break

            elapsed = clock() - stats.started_at
            if max_frames is not None and stats.rendered_frames >= max_frames:
                break
            if seconds is not None and elapsed >= seconds:
                break
    finally:
        camera.close()
        active_detector.close()
        if window_created:
            try:
                cv2_module.destroyWindow(config.window_name)
            except cv2_module.error:
                pass

    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        args = build_parser().parse_args(argv)
        config = make_config(args)
        manifest = ModelManifest.from_file(args.manifest)
        detector = YoloOnnxDetector(
            manifest,
            confidence_threshold=args.confidence,
            nms_iou_threshold=args.nms_iou,
        )
        stats = run_detection(
            config,
            manifest,
            seconds=args.seconds,
            max_frames=args.max_frames,
            headless=args.headless,
            detector=detector,
        )
    except (CameraError, DetectorError, ValueError, OSError) as exc:
        print(f"Botanika detection unavailable: {exc}", file=sys.stderr)
        return 2
    except cv2.error as exc:
        print(f"Botanika display unavailable: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nBotanika detection stopped.", file=sys.stderr)
        return 0

    detector_metrics = detector.metrics
    print(
        "Botanika detection stopped cleanly: "
        f"{stats.rendered_frames} frames, {stats.last_fps:.1f} FPS, "
        f"{stats.detections_seen} detections, "
        f"inference p50/p95 {detector_metrics.p50_ms:.1f}/{detector_metrics.p95_ms:.1f} ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
