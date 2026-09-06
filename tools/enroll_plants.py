#!/usr/bin/env python3
"""Enroll campus plant/tree photos into a checksummed few-shot index.

Typical first pass (five or more photos per label):

    .venv/bin/python tools/enroll_plants.py --dataset /media/campus-plants

The dataset may either be a directory of label folders or a bundle containing
``train/``, ``held-out/`` and ``unknown/`` directories.  See
``docs/CAMPUS_PLANT_ENROLLMENT.md`` for the release/evaluation workflow.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import AppSettings  # noqa: E402
from botanika.vision.classification import EnrollmentError, build_enrollment_artifact  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    settings = AppSettings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True, type=Path, help="label folders, or a bundle containing train/")
    parser.add_argument("--held-out", type=Path, default=None, help="independent label folders used only for evaluation")
    parser.add_argument("--unknown", type=Path, default=None, help="images that should be rejected as unknown")
    parser.add_argument("--output", type=Path, default=settings.campus_classifier_model_path, help="checksummed JSON artifact")
    parser.add_argument("--embedding-model", type=Path, default=settings.embedding_model_path)
    parser.add_argument("--catalog", type=Path, default=settings.species_catalog_path)
    parser.add_argument(
        "--regional-catalog",
        type=Path,
        default=settings.regional_catalog_path,
        help="sourced reference catalog used for explicit campus joins",
    )
    parser.add_argument("--catalog-map", type=Path, default=None, help="optional JSON mapping of folder name to immutable species_id")
    parser.add_argument("--min-images-per-label", type=int, default=3)
    parser.add_argument(
        "--approve-production",
        action="store_true",
        help="allow promotion only when every independent evidence gate passes; never needed for provisional suggestions",
    )
    args = parser.parse_args(argv)

    dataset = args.dataset.expanduser().resolve()
    # A single archive-like bundle is convenient for the operator.  Keep the
    # explicit flags authoritative when supplied.
    if (dataset / "train").is_dir():
        train = dataset / "train"
        held_out = args.held_out or (dataset / "held-out" if (dataset / "held-out").is_dir() else None)
        unknown = args.unknown or (dataset / "unknown" if (dataset / "unknown").is_dir() else None)
    else:
        train = dataset
        held_out = args.held_out
        unknown = args.unknown

    catalog_map = None
    if args.catalog_map is not None:
        try:
            catalog_map = json.loads(args.catalog_map.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"could not read --catalog-map: {exc}")
        if not isinstance(catalog_map, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in catalog_map.items()):
            parser.error("--catalog-map must be a JSON object mapping folder names to species IDs")

    try:
        artifact = build_enrollment_artifact(
            train,
            args.output,
            embedding_model_path=args.embedding_model,
            catalog_path=args.catalog,
            regional_catalog_path=args.regional_catalog,
            held_out_dir=held_out,
            unknown_dir=unknown,
            catalog_map=catalog_map,
            min_images_per_label=args.min_images_per_label,
            approve_production=args.approve_production,
        )
    except (EnrollmentError, OSError, ValueError, RuntimeError) as exc:
        print(f"enrollment failed: {exc}", file=sys.stderr)
        return 2

    metrics = artifact["metrics"]
    print(json.dumps({
        "output": str(args.output.expanduser().resolve()),
        "artifact_sha256": artifact["artifact_sha256"],
        "labels": [item["display_name"] for item in artifact["labels"]],
        "training_observations": metrics.get("training_observations"),
        "held_out_observations": metrics.get("held_out_observations"),
        "unknown_observations": metrics.get("unknown_observations"),
        "leave_one_out": metrics.get("leave_one_out"),
        "leave_one_label_out_unknown": metrics.get("leave_one_label_out_unknown"),
        "held_out": metrics.get("held_out"),
        "unknown_rejection_rate": metrics.get("unknown_rejection_rate"),
        "pi_benchmark": metrics.get("pi_benchmark"),
        "deployment_ready": artifact["deployment_ready"],
        "deployment_blockers": metrics.get("deployment_blockers"),
    }, indent=2, ensure_ascii=False))
    if not artifact["deployment_ready"]:
        print("provisional index written; Botanika will show suggestions but will not save an identification", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
