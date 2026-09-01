#!/usr/bin/env python3
"""Run Botanika's Phase 1 raw Pi Camera feed.

The camera is owned by ``CameraOwner`` and each frame is rendered by OpenCV in
a normal window on the Pi display. Press ``q`` or ``Esc`` to quit. ``--seconds``
and ``--max-frames`` are bounded options for repeatable diagnostics; ordinary
interactive use has no automatic stop.
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

from botanika.hardware.camera import (
    CameraConfig,
    CameraError,
    CameraFrame,
    CameraOwner,
    FrameReadError,
)


LOGGER = logging.getLogger("botanika.phase1.camera")
DEFAULT_CONFIG = CameraConfig()
MAX_CONSECUTIVE_DROPS = 30


@dataclass(slots=True)
class FeedStats:
    """Display-friendly measurements for the current raw-feed run."""

    started_at: float
    rendered_frames: int = 0
    last_fps: float = 0.0

    def update(self, now: float) -> None:
        self.rendered_frames += 1
        elapsed = max(now - self.started_at, 1e-9)
        self.last_fps = self.rendered_frames / elapsed


def draw_diagnostics(
    frame: np.ndarray,
    camera: CameraOwner,
    stats: FeedStats,
    *,
    cv2_module: Any = cv2,
) -> np.ndarray:
    """Draw non-invasive Phase 1 diagnostics onto a BGR frame."""

    height, width = frame.shape[:2]
    text = (
        f"BOTANIKA CAMERA  {width}x{height}  "
        f"FPS {stats.last_fps:4.1f}  "
        f"FRAMES {camera.frames_read}  DROPPED {camera.dropped_frames}"
    )
    baseline_y = min(30, max(height - 8, 16))
    cv2_module.rectangle(frame, (0, 0), (width, 42), (24, 24, 24), -1)
    cv2_module.putText(
        frame,
        text,
        (10, baseline_y),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.62,
        (242, 242, 242),
        1,
        cv2_module.LINE_AA,
    )
    return frame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=DEFAULT_CONFIG.width)
    parser.add_argument("--height", type=int, default=DEFAULT_CONFIG.height)
    parser.add_argument("--fps", type=int, default=DEFAULT_CONFIG.fps)
    parser.add_argument("--window-width", type=int, default=DEFAULT_CONFIG.window_width)
    parser.add_argument("--window-height", type=int, default=DEFAULT_CONFIG.window_height)
    parser.add_argument("--window-name", default=DEFAULT_CONFIG.window_name)
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="stop after this many seconds (useful for a bounded hardware check)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="stop after this many successfully rendered frames",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="capture and measure without opening an OpenCV window",
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


def run_feed(
    config: CameraConfig,
    *,
    seconds: float | None = None,
    max_frames: int | None = None,
    headless: bool = False,
    camera_factory: Callable[[], Any] | None = None,
    cv2_module: Any = cv2,
    clock: Callable[[], float] = time.monotonic,
) -> FeedStats:
    """Run the feed until a quit key, bound, or interrupt is received."""

    stats = FeedStats(started_at=clock())
    camera_kwargs: dict[str, Any] = {"config": config, "clock": clock}
    if camera_factory is not None:
        camera_kwargs["camera_factory"] = camera_factory
    camera = CameraOwner(**camera_kwargs)
    window_created = False
    consecutive_drops = 0

    try:
        camera.open()
        if not headless:
            cv2_module.namedWindow(config.window_name, cv2_module.WINDOW_NORMAL)
            cv2_module.resizeWindow(
                config.window_name, config.window_width, config.window_height
            )
            window_created = True

        while True:
            try:
                captured: CameraFrame = camera.read()
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
            stats.update(clock())
            if not headless:
                display_frame = draw_diagnostics(
                    captured.image, camera, stats, cv2_module=cv2_module
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
        if window_created:
            try:
                cv2_module.destroyWindow(config.window_name)
            except cv2_module.error:
                # The window may already have been closed by the desktop.
                pass

    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        args = build_parser().parse_args(argv)
        config = make_config(args)
        stats = run_feed(
            config,
            seconds=args.seconds,
            max_frames=args.max_frames,
            headless=args.headless,
        )
    except (CameraError, ValueError) as exc:
        print(f"Botanika camera unavailable: {exc}", file=sys.stderr)
        return 2
    except cv2.error as exc:
        print(f"Botanika display unavailable: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nBotanika camera stopped.", file=sys.stderr)
        return 0

    print(
        "Botanika camera stopped cleanly: "
        f"{stats.rendered_frames} frames, {stats.last_fps:.1f} FPS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
