# Botanika Phase 1 Raw Feed Report — 2026-09-01

**Decision:** Phase 1 implementation and camera-feed gate pass. The Botanika
Python code opened the Pi Camera, rendered OpenCV frames in a normal window,
reported live diagnostics, and released the camera cleanly. No detector,
classifier, API, browser UI, database, or persistent image behavior was added.

## Implementation

- `backend/src/botanika/hardware/camera.py` provides the single `CameraOwner`.
- Picamera2 is configured for the measured IMX708 `1536×864` `RGB888` preview
  stream at 30 FPS.
- Frames are converted once from RGB888 to OpenCV BGR.
- `tools/run_camera.py` renders a normal OpenCV window sized to `800×480`.
- The window reports source resolution, measured FPS, successful frame count,
  and dropped-frame count. `q` and `Esc` quit.
- Startup failures, invalid/read failures, persistent consecutive drops, and
  keyboard interruption have bounded or recoverable paths. Camera stop/close
  runs from `finally`, including partial-startup cleanup.

## Automated evidence

```text
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
Ran 11 tests ... OK

.venv/bin/python -m py_compile ...
git diff --check
```

The tests cover exact RGB-to-BGR conversion, configuration defaults, sequential
frames, dropped-frame retry, partial startup cleanup, CLI defaults, and a
bounded headless runner cleanup.

## Pi hardware evidence

The feed was run with:

```text
DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority \
  .venv/bin/python tools/run_camera.py --seconds 300
```

Observed native stack and run results:

| Measurement | Result |
| --- | --- |
| Camera | Sony IMX708, native path through Picamera2/libcamera |
| Selected stream | `1536×864-RGB888/sRGB` |
| Duration | 5 minutes |
| Successful frames | 8,993 |
| Final measured FPS | 30.0 |
| Dropped-frame warnings | None observed; runner count remained 0 |
| Temperature samples | 49.4°C, 46.6°C, 47.7°C |
| Throttling | `0x0` at all sampled points |
| Runner RSS | approximately 141 MiB |
| Runner CPU | approximately 49% at sampled points |
| System available memory | approximately 14 GiB at the first sample |

After the soak, the same command was started again with `--max-frames 30`.
It reacquired the camera, rendered 30 frames at 21.5 FPS, and logged:
`Camera stopped`, `Camera closed successfully`, and `stopped cleanly`.

OpenCV's Qt backend emitted a non-fatal warning about a missing packaged font
directory. It did not prevent window creation, frame rendering, or shutdown.

## Remaining operator-owned checks

The Stage 0 readiness report still tracks the separate human checks for camera
orientation/autofocus, microphone intelligibility, speaker clarity, and reboot
recovery. This Phase 1 run does not fabricate completion of those checks.

