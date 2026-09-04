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

## Phase 4 crop-to-classifier pipeline

Run the Phase 0–3 camera, generic detection, stability, quality, and crop path
with the deterministic classifier stub:

```sh
.venv/bin/python tools/run_phase4.py
.venv/bin/python tools/run_phase4.py --headless --max-frames 60
```

An accepted crop is passed directly to `ClassificationPipeline`, which prints
the crop path, hash association, timing, fake species details, and the visible
`DEMO DATA` warning. The stub never represents a real plant identification.
Classifier/result provenance mismatches become visibly labelled errors, and the
runner retains only a classification count rather than unbounded result
history.
Exercise the deterministic terminal paths with:

```sh
.venv/bin/python tools/run_phase4.py --demo-case uncertain
.venv/bin/python tools/run_phase4.py --demo-case error
.venv/bin/python tools/run_phase4.py --demo-case cancelled
```

Malformed image handling is covered by the unit contract tests; the live loop
only sends successfully written crop files to the classifier.

## Phase 5 modular monolith service

Run the FastAPI service (scan pipeline, demo library, observability, and the
built kiosk frontend) on loopback:

```sh
.venv/bin/python tools/run_api.py
.venv/bin/python tools/run_api.py --port 8123
```

The service binds to `127.0.0.1` by default and serves the built frontend from
`frontend/dist` at `/`. Build it first with `npm run build` inside `frontend/`.
Endpoints live under `/api/v1` (health, capabilities, scan state/events/preview,
scan commands, local-image fallback, demo library, diagnostics logs).

After `npm run build` in `frontend/`, run the automated kiosk-state and exact
layout verification with:

```sh
.venv/bin/python tools/verify_phase5_ui.py
```

It uses the installed Chromium binary, mocks only the local API boundary, checks
detecting/locking/processing/result/uncertain/error/cancellation/fallback states,
and refreshes `docs/evidence/phase5/` at exactly 800×480.

## Phase 7 private Wi-Fi boundary

The Phase 7 transport is opt-in. `run_api.py` remains loopback-only by default;
`--network` requests AP mode but falls back safely to loopback unless the live
AP and firewall preflight succeeds:

```sh
.venv/bin/python tools/run_api.py                 # SOLO, 127.0.0.1 only
.venv/bin/python tools/run_api.py --network       # AP plus loopback, firewall required
python3 tools/manage_access_point.py plan enable  # read-only recovery plan
sudo -E python3 tools/manage_access_point.py enable
python3 tools/manage_access_point.py status --json
```

Copy `config/environments/phase7-network.env.example` to the machine-local
`/etc/botanika/botanika.env`, replace the WPA passphrase, and install the
tracked files under `deploy/network/` and `deploy/systemd/` as described in
`deploy/README.md`. The operator command supports `enable`, `disable`, and
`recover`; it uses NetworkManager when present and falls back to hostapd plus
dnsmasq. It never prints the passphrase.

Run the safe repository check anywhere, or the live AP/loopback check on the
Pi after a phone can join the private SSID:

```sh
.venv/bin/python tools/verify_phase7_network.py
.venv/bin/python tools/verify_phase7_network.py --live --strict
```

## Phase 8 pairing and responsive handoff

Run the hardware-independent contract verifier from the repository root:

    .venv/bin/python tools/verify_phase8.py --strict

It checks the three-mode lease contract, GPIO-safe software adapter, separate
800×480/responsive layout markers, and the browser crop-only boundary. It does
not claim a physical button, LEDs, Pi camera, phone permission, Wi-Fi pairing,
or operator journey; those checks remain in
docs/DEFERRED_OPERATOR_ACCEPTANCE.md.

After building `frontend/`, run the local Chromium UI smoke check:

    .venv/bin/python tools/verify_phase8_ui.py

It mocks only the local API boundary, verifies the three Pi mode consoles at
exactly 800×480, checks the portrait pairing/client layout and 44px controls,
and writes deterministic evidence screenshots under `docs/evidence/phase8/`.
The screenshots are browser-rendered fixtures and do not replace the physical
Pi, AP, camera, or phone acceptance journey.

## Phase 9 extras and final hardening

Rebuild the offline knowledge index and verify its source/license boundary:

```sh
.venv/bin/python tools/ingest_knowledge.py --manifest-output docs/evidence/phase9/knowledge-manifest.json
```

Benchmark a manually installed quantized GGUF through the selected llama.cpp
backend. No network access or model download is attempted:

```sh
.venv/bin/python tools/benchmark_local_llm.py --model models/llm/botanika.gguf --output docs/evidence/phase9/llm-benchmark.json
```

Run the hardware-independent Phase 9 contract check:

```sh
.venv/bin/python tools/verify_phase9.py --strict
```

The verifier reports the physical Pi/operator gate separately; a passing
deterministic check is not evidence of a camera, audio, display, model,
boot/recovery, soak, or usability pass.
