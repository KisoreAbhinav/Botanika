# Detection improvement evidence

The campus classifier calibration now blends 10% of the prototype similarity
with 90% nearest enrolled-photo similarity. The previous blend was 70/30. On
the local enrollment index (75 images, 22 labels; regenerated with the
reproducible enrollment command), leave-one-out scoring
changed from 52/75 accepted views (69.3% coverage, 100% accuracy among
accepted views) to 58/75 (77.3% coverage, 100% accuracy among accepted views).
The label-exclusion diagnostic accepted 1/75 queries (1.33% false accepts)
when each query's own label was removed; this remained 1/75 under the old
calibration and is only a negative sanity check, not unknown-image evidence.
This is training-set leave-one-out evidence only. There are no independent
held-out or unknown images in this index, so the classifier remains provisional
and saves stay disabled.

The local artifact is intentionally ignored by git because enrollment photos
are operator data. Recreate it with:
`PYTHONPATH=backend/src .venv/bin/python tools/enroll_plants.py --dataset data/campus/enrollment/train --output models/plant_classifier/campus-fewshot-v1.json --min-images-per-label 3`

Weed inference keeps the full-frame pass and six bounded overlapping tile
passes. Before final NMS it removes a tile result when a same-class whole-frame
box covers at least 80% of the tile box. A 65% fallback is used only when the
tile box touches a tile edge and the whole-frame box continues beyond that
same edge, which is evidence of clipping during tiling. The two-to-one area
guard remains in place, and invalid or below-threshold whole-frame boxes are
excluded from suppression; coordinates are finite and clamped before a parent
can suppress anything. Regression fixtures cover clipped duplicates,
weak-parent neighbors, and invalid or non-finite parents.

On `data/demo/weed-in-maize-field.jpg`, the detector returned one box after
the change at both its native 800x600 size and a 1200x900 resized stress input.
The native result confidence was 0.665; the stress result confidence was
0.580. These are wiring and duplicate-suppression checks, not weed accuracy
measurements, because the image has no ground-truth boxes and the model is
documented for Wisconsin lawn imagery rather than Indian crops.
