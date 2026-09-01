# Botanika Phase 2 Generic Detection Report — 2026-09-01

**Decision:** Phase 2 implementation and runtime soak pass. The generic
detector loads from a checksum-verified local artifact, runs on resized camera
frames, restores letterboxed coordinates, draws generic boxes, and releases
both model and camera resources cleanly. The current camera scene did not
contain detectable objects, so the two-object live-scene trial remains an
operator follow-up rather than an invented result.

## Model contract

| Field | Value |
| --- | --- |
| Model | Ultralytics YOLO11n, generic COCO detector |
| Model version | `8.3.237` |
| Artifact | `models/detectors/yolo11n.onnx` |
| Artifact size | approximately 11 MiB |
| SHA-256 | `634279b40c07c6391472c51ad45b81ebc48706a9a1fe72dd3396322acd0c053b` |
| Source | Ultralytics assets release `v8.4.0` |
| License | AGPL-3.0 |
| Labels | 80 COCO classes, recorded in the manifest |
| Input | 640×640 RGB float tensor, normalized to 0–1 |
| Output | YOLO `features_first`: 4 box values plus class scores |

The tracked contract is [`config/models/yolo11n-coco.json`](../config/models/yolo11n-coco.json).
The binary is ignored by Git and must be provisioned separately on another
checkout. The application never downloads it at runtime.

## Implementation

- `backend/src/botanika/vision/detection/geometry.py` handles detector
  letterboxing and fixed 800×480 display mapping.
- `backend/src/botanika/vision/detection/yolo.py` owns manifest verification,
  ONNX Runtime session loading, preprocessing, decoding, class-aware NMS, and
  bounded p50/p95 latency metrics.
- `tools/run_detection.py` uses the existing single-owner camera and one
  synchronous camera→inference→display loop. A new frame is not queued while
  inference is running, preventing stale backlog.
- The display labels detections as generic COCO objects and explicitly states
  that the model is not a plant-species classifier.

## Automated evidence

```text
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
Ran 17 tests ... OK

.venv/bin/python -m py_compile ...
git diff --check
```

Tests cover letterbox round trips, fixed-window coordinate mapping, output
decoding and class-aware NMS, checksum rejection, bounded metrics, and the
bundled model on a synthetic image.

An official COCO sample image was processed in memory and removed afterward.
The detector returned `bus` at 0.94 confidence and four `person` boxes between
0.398 and 0.902 confidence, demonstrating multiple generic classes and valid
box restoration.

## Pi hardware evidence

Command:

```sh
DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority \
  .venv/bin/python tools/run_detection.py --seconds 300
```

| Measurement | Result |
| --- | --- |
| Camera stream | 1536×864 RGB888 from the Sony IMX708 |
| Duration | 5 minutes |
| Frames | 1,639 |
| Visible FPS | 5.5 |
| Inference p50/p95 | 157.2 / 190.2 ms |
| Camera drops/errors | None observed |
| Temperature samples | 59.3°C, 60.9°C, 61.5°C |
| Throttling | `0x0` at all samples |
| Process RSS | approximately 260 MiB |
| Process CPU | approximately 387–390% |
| System available memory | approximately 13 GiB |

The runner logged orderly camera stop and close at completion. A separate
60-frame display run loaded the model and completed at 5.2 FPS with inference
p50/p95 of 156.6/173.7 ms. A 60-frame headless run on the current camera scene
completed at 5.6 FPS with zero detections.

OpenCV's Qt backend emitted a non-fatal missing-font-directory warning; it did
not prevent window creation, inference, or shutdown.

## Deferred final operator follow-up

Point the camera at a scene containing at least two ordinary COCO objects and
repeat the live display run, recording the visible labels and boxes. The
generic model's `potted plant` label is only a broad COCO object label; it is
not evidence of plant species identification.

The owner has deferred this physical-scene observation to final acceptance. It
remains open in `DEFERRED_OPERATOR_ACCEPTANCE.md`; automated work may continue
without treating the observation as passed.
