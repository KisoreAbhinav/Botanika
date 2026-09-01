# Operator and Preparation Tools

Future tools will support hardware checks, camera-quality calibration, dataset
and knowledge preparation, model verification, Pi benchmarking, backup, and
restore. Runtime request handling must not import from this directory.

## Phase 0 environment verification

Run the verifier from the repository root before starting application work:

```sh
python3 tools/verify_phase0.py
python3 tools/verify_phase0.py --strict
DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority \
  .venv/bin/python tools/verify_phase0.py --probe-capture --strict
```

The default command records measured host, storage, temperature, software,
camera, display, and audio state without requiring third-party Python modules.
`--strict` returns a non-zero status when a required Phase 0 capability is
blocked. `--probe-capture` may be added to attempt one temporary native still;
the probe validates its JPEG markers and deletes its output after inspection.
The explicit X11 variables are useful from an SSH/IDE terminal; a terminal
opened inside the Pi desktop normally inherits them already. Hardware probes
must have access to the Pi device nodes and therefore may be blocked by a
container or managed sandbox even when the host hardware is healthy.

Because the virtual environment deliberately inherits Raspberry Pi OS packages
for Picamera2/libcamera, a generic `pip check` also inspects unrelated Debian
Python metadata and may report missing optional typing/distribution packages.
The Phase 0 verifier instead checks every Botanika direct Python pin exactly and
reports those results under `python_dependency_pins`.

Phase 0 dependency inputs are kept in:

- `config/environments/phase0-native-packages.txt` for Raspberry Pi OS packages;
- `config/environments/phase0-python-requirements.txt` for pinned Python
  packages; and
- the project-root `.venv`, created with `--system-site-packages` so native
  Picamera2/libcamera bindings remain available.

## Phase 1 raw camera feed

Run the Botanika-owned OpenCV feed on the Pi display:

```sh
.venv/bin/python tools/run_camera.py
```

The script uses one `CameraOwner`, requests the measured 1536×864 `RGB888`
preview stream, validates Picamera2's OpenCV-ready BGR array without swapping
channels, and renders a normal 800×480 window. Press `q` or `Esc` to quit. For
a bounded diagnostic run:

```sh
.venv/bin/python tools/run_camera.py --seconds 300
```

It reports successful frames, measured FPS, and read failures treated as
dropped frames, and always stops/closes the camera in a `finally` block.

## Phase 2 generic detection

Run the local COCO-pretrained YOLO11n detector over the same camera owner:

```sh
.venv/bin/python tools/run_detection.py
```

The detector loads once through ONNX Runtime, verifies the tracked manifest and
SHA-256 checksum, letterboxes each frame to 640×640, restores boxes to the
source frame, and displays every generic label/confidence. Inference runs in a
single synchronous loop, so stale frames cannot accumulate behind it. The
display reports visible FPS and inference p50/p95 latency. Use `--headless`
for a bounded non-display smoke test.

## Phase 3 lock-on and crop capture

Run the target tracker and crop-only capture path:

```sh
.venv/bin/python tools/run_lock_on.py
```

The default eligible generic label is `potted plant`. Hold an eligible target
steady for the configured checks; the runner evaluates size, edge clipping,
exposure, crop focus, and target appearance before saving one PNG under
`data/media/temp/phase3-crops/`. Press Space for a manual debug crop, and `q`
or `Esc` to quit. Use `--no-auto-capture` to inspect the lock without writing.
After a capture, the target must leave or be replaced before automatic capture
rearms. Quality values and the `--appearance-similarity` default are
unvalidated baselines that must be calibrated on real Pi Camera fixtures.
