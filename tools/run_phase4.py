#!/usr/bin/env python3
"""Run the Phase 0–3 camera pipeline and classify each accepted crop as demo data."""

from __future__ import annotations

import logging
from pathlib import Path
import sys

# Allow the script to run directly from a source checkout without installation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.vision.classification import (
    ClassificationPipeline,
    DummyClassifier,
    DummyScenario,
    format_diagnostic,
)

import run_lock_on


LOGGER = logging.getLogger("botanika.phase4")


def build_parser():
    parser = run_lock_on.build_parser()
    parser.description = __doc__
    parser.add_argument(
        "--demo-case",
        choices=[scenario.value for scenario in DummyScenario],
        default=DummyScenario.ACCEPTED.value,
        help="deterministic stub response to exercise (default: accepted)",
    )
    parser.add_argument(
        "--stub-confidence",
        type=float,
        default=0.93,
        help="demo confidence before the acceptance threshold (default: 0.93)",
    )
    parser.add_argument(
        "--acceptance-threshold",
        type=float,
        default=0.75,
        help="demo threshold used to produce accepted or uncertain output",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        args = build_parser().parse_args(argv)
        config = run_lock_on.make_config(args)
        manifest = run_lock_on.ModelManifest.from_file(args.manifest)
        quality_config = run_lock_on.QualityConfig.from_file(args.quality_config)
        labels = frozenset(args.eligible_label or ["potted plant"])
        classifier = DummyClassifier(
            scenario=DummyScenario(args.demo_case),
            confidence=args.stub_confidence,
            acceptance_threshold=args.acceptance_threshold,
        )
        pipeline = ClassificationPipeline(classifier)
        classification_count = 0

        print(
            "Botanika Phase 4 pipeline ready: DEMO DATA only; "
            f"classifier={classifier.classifier_version} case={args.demo_case}",
            flush=True,
        )

        def classify_capture(capture):
            nonlocal classification_count
            run = pipeline.classify_capture(capture)
            classification_count += 1
            print(format_diagnostic(run), flush=True)

        stats = run_lock_on.run_lock_on(
            config,
            manifest,
            quality_config,
            args.output_dir,
            eligible_labels=labels,
            confidence=args.confidence,
            nms_iou=args.nms_iou,
            stable_checks=args.stable_checks,
            appearance_similarity=args.appearance_similarity,
            cooldown_frames=args.cooldown_frames,
            padding=args.padding,
            automatic_capture=not args.no_auto_capture,
            seconds=args.seconds,
            max_frames=args.max_frames,
            headless=args.headless,
            on_capture=classify_capture,
        )
    except (run_lock_on.CameraError, run_lock_on.DetectorError, ValueError, OSError) as exc:
        print(f"Botanika Phase 4 unavailable: {exc}", file=sys.stderr)
        return 2
    except run_lock_on.cv2.error as exc:
        print(f"Botanika display unavailable: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nBotanika Phase 4 stopped.", file=sys.stderr)
        return 0

    print(
        "Botanika Phase 4 stopped cleanly: "
        f"{stats.rendered_frames} frames, {stats.last_fps:.1f} FPS, "
        f"{stats.captures} crops saved, {classification_count} DEMO DATA classifications"
    )
    if classification_count == 0:
        print("No accepted crop was produced; hold an eligible target steady to see the demo result.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
