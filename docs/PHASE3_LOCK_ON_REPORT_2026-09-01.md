# Botanika Phase 3 Lock-On and Crop Report — 2026-09-01

**Decision:** Phase 3 implementation and integration smoke pass. The lock-on
engine, quality gate, crop-only writer, cooldown/deduplication guard, and
manual capture path are implemented and tested. The required live trial with a
steady eligible plant target remains pending because the current camera scene
contained no eligible `potted plant` detection; no crop was fabricated.

## Implementation

- `vision/quality/quality.py` measures focus on the candidate crop using
  Laplacian variance, mean luminance, saturation, target size, and edge
  clipping. It returns actionable rejection reasons.
- `vision/quality/lock_on.py` implements `Searching`, `Tracking`, `Hold steady`,
  `Checking sharpness`, `Locked`, `Capturing`, `Captured`, and `Cooldown`.
  Matching uses class, IoU, normalized center movement, size change, and
  disappearance tolerance.
- `vision/quality/capture.py` pads and clamps the selected box, extracts the
  crop in memory, and writes a lossless PNG made only from that crop. The full
  frame is never written. Crop hashes prevent rapid identical saves.
- `tools/run_lock_on.py` combines the existing camera owner and generic
  detector, shows the lock/quality diagnostics in the fixed 800×480 window,
  auto-captures after a quality lock, and supports Space for manual debugging.

## Threshold status

The tracked quality file is
[`config/vision/phase3-quality-baseline.json`](../config/vision/phase3-quality-baseline.json).
It is deliberately marked `baseline_unvalidated`. Its thresholds are
configurable and covered by deterministic fixtures, but must be replaced or
confirmed using actual sharp, blurry, dark, bright, and clipped Pi Camera
fixtures before they are called calibrated.

## Original automated evidence

```text
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
Ran 23 tests ... OK

.venv/bin/python -m py_compile ...
git diff --check
```

Tests cover candidate selection, stable target capture, exact crop dimensions,
moving-target rejection, blurry/too-small/dark/edge rejection, cooldown, rapid
duplicate prevention, and crop-only filesystem behavior.

## Pi integration evidence

```text
DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority \
  .venv/bin/python tools/run_lock_on.py --headless --max-frames 60
```

Observed result:

| Measurement | Result |
| --- | --- |
| Camera stream | 1536×864 RGB888 from the Sony IMX708 |
| Detector/inference | YOLO11n ONNX through ONNX Runtime |
| Frames | 60 |
| Integrated FPS | 5.7 |
| Camera errors/drops | None observed |
| Eligible target detections | 0 in the current scene |
| Crops saved | 0 |
| Resource cleanup | Camera stopped/closed successfully; detector released |

The no-target result is expected for the current scene. A physical trial with
an eligible potted plant must confirm the full `Tracking → Hold steady →
Checking sharpness → Captured` path and verify that one, and only one, PNG is
created. At the time of this Phase 3 report, Phase 4 classification had not
been started; its current implementation is recorded separately in
`PHASE4_CLASSIFIER_REPORT_2026-09-01.md`.

## Post-audit correction

The 2026-09-01 audit made the lock-on states externally observable, added BGR
appearance-histogram matching, and changed automatic capture rearming so the
same visible target cannot save again after a time-only cooldown. The target
must leave for the configured disappearance tolerance or be replaced by a
non-matching target. Cooldown updates no longer re-emit the prior capture, so
saved-file metrics and logs count each file once. Automated tests cover these
regressions; the current suite runs 30 tests.

Quality/appearance thresholds and the physical stable, moving, blurry, clipped,
disappeared, and multi-target trials remain deferred—not passed—and are listed
in `DEFERRED_OPERATOR_ACCEPTANCE.md` for final acceptance.

A post-correction headless/no-capture hardware smoke run processed 20 frames at
5.1 FPS through the IMX708, YOLO adapter, and lock-on engine. It wrote zero crop
files and stopped/closed the camera cleanly.
