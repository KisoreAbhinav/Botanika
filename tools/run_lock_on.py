#!/usr/bin/env python3
"""Run Botanika's Phase 3 lock-on and crop-only capture loop.

The runner keeps the Phase 2 generic detector labels separate from the Phase 3
target lock. It writes only accepted candidate crops. Press Space for the
manual debug capture path, or ``q``/``Esc`` to quit.
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
    ModelManifest,
    YoloOnnxDetector,
    fit_frame_to_window,
)
from botanika.vision.quality import (
    CaptureResult,
    CropStore,
    LockOnConfig,
    LockOnEngine,
    LockOnState,
    LockOnUpdate,
    QualityConfig,
)


LOGGER = logging.getLogger("botanika.phase3.lock_on")
DEFAULT_CONFIG = CameraConfig(window_name="Botanika Lock On")
DEFAULT_MANIFEST = PROJECT_ROOT / "config" / "models" / "yolo11n-coco.json"
DEFAULT_QUALITY_CONFIG = PROJECT_ROOT / "config" / "vision" / "phase3-quality-baseline.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "media" / "temp" / "phase3-crops"
MAX_CONSECUTIVE_DROPS = 30
OCHRE = (46, 105, 138)
GREEN = (81, 107, 72)
WHITE = (242, 242, 242)


@dataclass(slots=True)
class LockOnFeedStats:
    started_at: float
    rendered_frames: int = 0
    last_fps: float = 0.0
    captures: int = 0

    def update(self, now: float, capture: CaptureResult | None) -> None:
        self.rendered_frames += 1
        self.record_capture(capture)
        self.last_fps = self.rendered_frames / max(now - self.started_at, 1e-9)

    def record_capture(self, capture: CaptureResult | None) -> None:
        if capture is not None and capture.path is not None:
            self.captures += 1


def draw_lock_on_frame(
    frame: np.ndarray,
    detections: list[Detection],
    update: LockOnUpdate,
    stats: LockOnFeedStats,
    config: CameraConfig,
    *,
    cv2_module: Any = cv2,
) -> np.ndarray:
    """Draw generic boxes plus the selected target and quality state."""

    canvas, transform = fit_frame_to_window(
        frame,
        config.window_width,
        config.window_height,
        cv2_module=cv2_module,
    )
    for detection in detections:
        selected = update.detection == detection
        box = transform.to_display_box(detection.box)
        color = GREEN if selected else OCHRE
        top_left = (round(box.x1), round(box.y1))
        bottom_right = (round(box.x2), round(box.y2))
        cv2_module.rectangle(canvas, top_left, bottom_right, color, 2)
        label_prefix = "TARGET " if selected else ""
        label = f"{label_prefix}{detection.label} {detection.confidence:.0%}"
        cv2_module.putText(
            canvas,
            label,
            (top_left[0] + 3, max(66, top_left[1] - 6)),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            1,
            cv2_module.LINE_AA,
        )

    cv2_module.rectangle(canvas, (0, 0), (config.window_width, 58), (24, 24, 24), -1)
    quality = update.quality
    quality_text = (
        f"FOCUS {quality.focus_score:.0f}  LUMA {quality.mean_luma:.0f}  "
        f"SIZE {quality.target_width:.0f}x{quality.target_height:.0f}"
        if quality is not None
        else "FOCUS --  LUMA --  SIZE --"
    )
    status_text = (
        f"{update.state.value.upper()}  "
        f"STABLE {update.stable_checks}/{update.required_checks}  "
        f"{stats.last_fps:4.1f} FPS"
    )
    cv2_module.putText(
        canvas,
        status_text,
        (10, 21),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.52,
        WHITE,
        1,
        cv2_module.LINE_AA,
    )
    cv2_module.putText(
        canvas,
        quality_text,
        (10, 43),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.42,
        (190, 190, 190),
        1,
        cv2_module.LINE_AA,
    )
    cv2_module.rectangle(
        canvas,
        (0, config.window_height - 31),
        (config.window_width, config.window_height),
        (24, 24, 24),
        -1,
    )
    cv2_module.putText(
        canvas,
        f"{update.hint}  |  SPACE manual crop  |  {stats.captures} saved",
        (10, config.window_height - 11),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.44,
        WHITE,
        1,
        cv2_module.LINE_AA,
    )
    return canvas


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--quality-config", type=Path, default=DEFAULT_QUALITY_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--eligible-label", action="append", default=None)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--nms-iou", type=float, default=0.45)
    parser.add_argument("--stable-checks", type=int, default=4)
    parser.add_argument("--cooldown-frames", type=int, default=30)
    parser.add_argument("--padding", type=float, default=0.08)
    parser.add_argument("--no-auto-capture", action="store_true")
    parser.add_argument("--width", type=int, default=DEFAULT_CONFIG.width)
    parser.add_argument("--height", type=int, default=DEFAULT_CONFIG.height)
    parser.add_argument("--fps", type=int, default=DEFAULT_CONFIG.fps)
    parser.add_argument("--window-width", type=int, default=DEFAULT_CONFIG.window_width)
    parser.add_argument("--window-height", type=int, default=DEFAULT_CONFIG.window_height)
    parser.add_argument("--window-name", default=DEFAULT_CONFIG.window_name)
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--headless", action="store_true")
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


def run_lock_on(
    config: CameraConfig,
    manifest: ModelManifest,
    quality_config: QualityConfig,
    output_dir: Path,
    *,
    eligible_labels: frozenset[str] = frozenset({"potted plant"}),
    confidence: float = 0.25,
    nms_iou: float = 0.45,
    stable_checks: int = 4,
    cooldown_frames: int = 30,
    padding: float = 0.08,
    automatic_capture: bool = True,
    seconds: float | None = None,
    max_frames: int | None = None,
    headless: bool = False,
    camera_factory: Callable[[], Any] | None = None,
    detector: YoloOnnxDetector | None = None,
    cv2_module: Any = cv2,
    clock: Callable[[], float] = time.monotonic,
) -> LockOnFeedStats:
    stats = LockOnFeedStats(started_at=clock())
    active_detector = detector or YoloOnnxDetector(
        manifest,
        confidence_threshold=confidence,
        nms_iou_threshold=nms_iou,
    )
    crop_store = CropStore(output_dir, padding_ratio=padding, clock=clock)
    engine = LockOnEngine(
        LockOnConfig(
            eligible_labels=eligible_labels,
            stable_checks=stable_checks,
            cooldown_frames=cooldown_frames,
            crop_padding_ratio=padding,
            automatic_capture=automatic_capture,
            quality=quality_config,
        ),
        crop_store,
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
            update = engine.update(captured.image, detections)
            stats.update(clock(), update.capture)
            if update.capture is not None:
                if update.capture.path is not None:
                    LOGGER.info("Saved crop-only capture: %s", update.capture.path)
                elif update.capture.duplicate:
                    LOGGER.info("Skipped duplicate crop: %s", update.capture.content_hash[:12])

            if not headless:
                display_frame = draw_lock_on_frame(
                    captured.image,
                    detections,
                    update,
                    stats,
                    config,
                    cv2_module=cv2_module,
                )
                cv2_module.imshow(config.window_name, display_frame)
                key = cv2_module.waitKey(1) & 0xFF
                if key == 32:
                    manual_update = engine.manual_capture(captured.image)
                    if manual_update.capture is not None:
                        stats.record_capture(manual_update.capture)
                        if manual_update.capture.path is not None:
                            LOGGER.info("Saved manual crop-only capture: %s", manual_update.capture.path)
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
        quality_config = QualityConfig.from_file(args.quality_config)
        labels = frozenset(args.eligible_label or ["potted plant"])
        stats = run_lock_on(
            config,
            manifest,
            quality_config,
            args.output_dir,
            eligible_labels=labels,
            confidence=args.confidence,
            nms_iou=args.nms_iou,
            stable_checks=args.stable_checks,
            cooldown_frames=args.cooldown_frames,
            padding=args.padding,
            automatic_capture=not args.no_auto_capture,
            seconds=args.seconds,
            max_frames=args.max_frames,
            headless=args.headless,
        )
    except (CameraError, DetectorError, ValueError, OSError) as exc:
        print(f"Botanika lock-on unavailable: {exc}", file=sys.stderr)
        return 2
    except cv2.error as exc:
        print(f"Botanika display unavailable: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nBotanika lock-on stopped.", file=sys.stderr)
        return 0

    print(
        "Botanika lock-on stopped cleanly: "
        f"{stats.rendered_frames} frames, {stats.last_fps:.1f} FPS, "
        f"{stats.captures} crops saved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
