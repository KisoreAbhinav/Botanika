# Backend Boundary

This directory will contain Botanika’s Pi-local FastAPI modular monolith.
Hardware ownership, inference, knowledge retrieval, local discovery storage, and
voice orchestration live behind explicit modules under `src/botanika/`.

The first implementation slice is the single-owner Phase 1 camera adapter in
[`src/botanika/hardware/camera.py`](src/botanika/hardware/camera.py). It is
intentionally independent of the future FastAPI application and browser UI.

Run the raw feed from the repository root with:

```sh
.venv/bin/python tools/run_camera.py
```

The default stream is the measured IMX708 1536×864 RGB888 preview mode.
Picamera2 exposes that stream in OpenCV-ready BGR byte order, so frames are
validated but not channel-swapped. The OpenCV window is sized to 800×480 and
displays frame count, measured FPS, and dropped-frame count. Press `q` or `Esc`
to stop. Use `--seconds` or `--max-frames` for bounded checks, and `--headless`
only for non-display smoke tests.

Phase 2 adds the generic ONNX Runtime detector under
[`src/botanika/vision/detection/`](src/botanika/vision/detection/). It is a
COCO object detector only; its labels are not botanical species
identifications. Run its Pi camera window with:

```sh
.venv/bin/python tools/run_detection.py
```

Phase 3 adds reusable target quality, lock-on, and crop-only capture services
under [`src/botanika/vision/quality/`](src/botanika/vision/quality/). Run the
integrated debug loop with:

```sh
.venv/bin/python tools/run_lock_on.py
```

The current default quality thresholds are explicitly marked as an unvalidated
Pi-camera baseline in `config/vision/phase3-quality-baseline.json`. Appearance
matching participates in tracking, and automatic capture does not rearm until
the captured target leaves or is replaced.
