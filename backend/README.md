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

Phase 4 adds the reusable species-classification boundary under
[`src/botanika/vision/classification/`](src/botanika/vision/classification/).
`ClassificationPipeline` passes each successful crop path directly to the
classifier and associates the result with the crop hash and timing. The only
available implementation is `DummyClassifier`, version `stub-phase-4`; every
response is marked `is_stub: true` and `DEMO DATA`. The pipeline fails closed
if classifier/result provenance disagrees, and in-memory crops must be
non-empty three-channel `uint8` BGR arrays. Run the complete diagnostic loop
with:

```sh
.venv/bin/python tools/run_phase4.py --headless --max-frames 60
```

Use `--demo-case uncertain`, `--demo-case error`, or `--demo-case cancelled` to
exercise deterministic non-success responses. This phase does not download,
train, or validate a species model.

Phase 6 adds the normal runtime under [`src/botanika/knowledge/`](src/botanika/knowledge/),
[`src/botanika/storage/database.py`](src/botanika/storage/database.py), and
[`src/botanika/storage/discoveries.py`](src/botanika/storage/discoveries.py).
The India starter catalog contains seven stable species IDs with aliases,
native/category metadata, conservation records, ecology notes, source/license
provenance, and a model-release label map. `CompactSpeciesClassifier` loads the
checksum-verified OpenCV/NumPy feature artifact, joins labels to the catalog,
and abstains on out-of-range, ambiguous, or unvalidated views. Accepted results
remain gated until held-out/per-class metrics, unknown-rejection trials, and Pi
latency/memory/thermal evidence are recorded. Normal
`AppSettings` uses this non-stub path; the old demo repository is reachable only
through an explicit Phase 5 compatibility configuration.

Run the local service from the repository root with:

```sh
.venv/bin/python tools/run_api.py
```

The service seeds the configured SQLite database on first start. Repository
defaults use `data/database/botanika.sqlite` and
`data/media/discoveries/real/`; the production environment example moves the
database, crops, temporary files, and backup archives beneath
`/var/lib/botanika`. Export and failure-atomic restore archives include the
SQLite snapshot and verified image linkage. Position is optional, so saving
never waits for coordinates.

## Phase 7 private Wi-Fi and optional internet tunnel

The Phase 7 network boundary lives under
[`src/botanika/network/`](src/botanika/network/). It reports measured interface,
AP-stack, DHCP/DNS, firewall, and FastAPI listener checks through
`/api/v1/network/status` and the `network` capability. `AppSettings()` remains
loopback-only; network mode enables the same application for the controlled
private AP only after a live boundary preflight, while retaining loopback
access behind the AP-only firewall template.

Use `tools/manage_access_point.py` for explicit `plan`, `enable`, `disable`,
and `recover` operations. NetworkManager is selected when available and
hostapd plus dnsmasq is the fallback. The `/connect` route is a minimal
no-JavaScript phone landing page; pairing, responsive scan UI, and controller
handoff are intentionally not part of this phase.

The private AP is not required for internet pairing. With
`BOTANIKA_NETWORK_ENABLED=false`, `BOTANIKA_HOST=127.0.0.1`,
`BOTANIKA_LOOPBACK_ONLY=true`, and `BOTANIKA_TUNNEL_ENABLED=true`, selecting
NETWORKED starts the locally installed `cloudflared` executable in a bounded
background worker. Its strict HTTPS `*.trycloudflare.com` URL is exposed in
the operator mode status and rendered as a local QR code; the phone then uses
the same API and Pi-owned inference/storage from any internet-connected
network. The URL worker drains output, times out, restarts without stale
processes, and is stopped on SOLO or application shutdown.

Quick Tunnels are free and require no Cloudflare account or domain, but are
documented by Cloudflare for development/testing: URLs are random per process,
there is no SLA, the limit is 200 in-flight requests, and SSE is unsupported.
Botanika's remote paired flow deliberately uses 2-second status polling and
crop uploads rather than SSE. HTTPS also gives phone camera APIs a secure
context.

## Phase 8 controller handoff

`botanika.mode` owns the explicit `SOLO`, `NETWORKED_UNPAIRED`, and
`NETWORKED_PAIRED` states. A networked session consumes one short-lived pairing
code and receives one longer bearer lease; the raw lease is returned once and
only its digest is retained in memory. Returning to SOLO, expiry, disconnect,
operator takeover, or a backend restart revokes it.

Pi operator routes accept only loopback peers. Remote status and `/connect`
responses never include the pairing code; the active controller uses a
same-site HTTP-only cookie or bearer header for feature, library, and media
requests. Crop publication and save are bound to the live lease, request ID,
and crop hash. Heartbeat freshness drives the Pi console health indicator.

The mode button and status LEDs use `botanika.hardware.gpio`. BCM pins are
optional configuration, boot outputs are forced low before the safe SOLO state
is shown, and cleanup is idempotent. Without a GPIO backend, the `/mode/toggle`
route and keyboard `N` shortcut provide the same software fallback.

On a secure origin, the paired browser owns its `getUserMedia` camera. The
private-HTTP AP path uses the native `capture="environment"` still input because
stream and geolocation APIs require a secure context. The browser-side detector
is currently intentionally unavailable, so the UI labels a manual capture/photo
fallback, performs a local crop/quality gate, and uploads one still crop only.
`/api/v1/mode/controller/crop` checks the uploaded hash and dimensions, then
reuses the existing Pi classifier. The existing library save route remains
authoritative and accepts optional browser position only during an explicit
save. Insecure-origin or denied location is treated as unavailable and never
blocks that save.

## Phase 9 extras

The knowledge boundary rebuilds a local catalog search index from reviewed
records. Every hit retains its source/license citation and answers abstain when
exact evidence is missing. `tools/ingest_knowledge.py` validates the tracked
source/license manifest and emits a stable chunk manifest without network
access.

`AudioCoordinator` owns bounded Vosk/Piper turns, endpointing, cached models,
speaker interruption, and typed-chat fallback. Missing Pi audio devices or
voice assets are reported as unavailable.

`vision/weeds` is an independent, multi-box beta contract with an explicit
crop/region manifest. It accepts one SOLO Pi frame or one paired-browser still,
never stores images, and records only accurate coordinate observations and
model metadata outside the plant library. The exact no-position message is
`Exact location could not be found. Coordinate collection was skipped.`

Library progress is derived from active saved observations and includes catalog
coverage, category progress, first/repeat indicators, milestones, and an
anonymous local aggregate summary. The readiness-gated Chromium launcher and
systemd kiosk unit live under `tools/launch_kiosk.py` and `deploy/systemd/`.
