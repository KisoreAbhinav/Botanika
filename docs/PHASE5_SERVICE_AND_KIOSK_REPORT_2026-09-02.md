# Phase 5 Completion Report — Modular Monolith Service & 800×480 Kiosk Interface

**Date:** 2026-09-02
**Scope:** BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md → Phase 5 (SOLO build)
**Status:** Implementation corrected and automated checks pass; physical Pi operator acceptance remains deferred

## What was built

### Backend — one FastAPI service (`botanika.api`)

| Area | Modules | Notes |
| --- | --- | --- |
| Config | `core/settings.py` | `AppSettings` dataclass: loopback host/port, SQLite + media dirs, `FRONTEND_DIST`. `phase5-python-requirements.txt` added under `config/environments/`. |
| App factory | `api/app.py` | Creates FastAPI, mounts routers, serves the built kiosk at `/`, serves demo media at `/media/demo/`, installs problem-detail error handlers and request-ID middleware. |
| Runtime container | `api/runtime.py` | Lifespan-owned settings, scan, library, and bounded request-log services without module globals. |
| Schemas | `api/schemas.py` | Typed health, readiness, command, library, and diagnostics contracts. |
| Routes | `api/routes/{health,capabilities,scan,library}.py` | `/api/v1/health/live`, `/health/ready`, `/capabilities`, `/scan/state`, `/scan/events` (SSE), `/scan/preview.mjpg`, `/scan/select`, `/scan/manual-capture`, `/scan/retake`, `/scan/cancel`, `/scan/fallback{,/capture,/clear}`, `/library/records` (GET/POST/DELETE), `/diagnostics/logs`. |
| Errors | `core/errors.py` | `BotanikaError` hierarchy → RFC-7807-style `ProblemDetail` (`type/title/status/detail/code/request_id`). Handlers were adjusted so the frontend can read `detail` directly. |
| Observability | `observability/logs.py` | In-memory bounded structured request log exposed via `/diagnostics/logs`. |
| Capabilities | `core/capabilities.py` | `CapabilitiesReport` covering camera, detector, classifier, knowledge, storage, library, preview; drives `/capabilities` and the kiosk status strip. |
| Scan service wiring | `vision/services/{scan,snapshot,events,preview,overlay}.py` | One owner thread coordinates camera/detector/classifier, increasing preview sequences, terminal-result hold, cooperative cancellation, reconnect, and detector-free manual local-image fallback. |
| Library | `storage/library.py` | `DemoLibrary` (SQLite, demo-only, wall-clock timestamps, hash dedupe). Crop files are served at `/media/demo/<file>`; DELETE requires `confirmed=true`. |

### Frontend — React 18 + Vite kiosk (`frontend/`)

- **Exact 800×480 shell** with proportional `transform: scale()` on other viewports; 66 px masthead (wordmark left/Home, serif "Botanika" centre, Ask + diagnostics right), 414 px body with the faint 28 px grid texture; InnoHack palette preserved exactly (`#efede3`, `#272724`, `#486b51`, `#8a692e`, `#8b3028`, …); square line-icon SVG set, no emoji.
- **Home:** three cards (Scan / Library / disabled Weed Beta), bottom status strip fed by `/capabilities`, decorative foliage corners, keyboard shortcuts (1/2, A, H/Esc).
- **Scan:** 500×330 workspace with MJPEG `<img>` + `<canvas>` overlay drawing detector boxes through the backend-published transform (source→preview `scale/offset`), tap-to-select boxes (nearest-centre hit test, scaled-canvas aware), status pill (backend `state`/`hint`), 4-cell stability strip, right details panel (live quality guidance → processing → accepted/uncertain/error result with species name, confidence, DEMO DATA tag, suggestions, sources), bottom action bar: Manual capture, Local image, Capture from image/Clear image (fallback mode), Save to Library (blocked for uncertain results and unavailable storage), Retake, Another angle, Cancel while processing.
- **Local image fallback:** upload → eligible detector box or manual whole-image selection → classifier → result panel; the full frame is never persisted.
- **Library:** species-grouped demo entries, observation counts, category/sort controls, coverage panel, contained details dialog, crop history, and confirmed observation deletion.
- **Ask:** clearly disabled shell (knowledge unavailable in this build). **Weed Beta:** disabled shell.
- Toasts (auto-dismiss info, sticky errors), diagnostics popover, `prefers-reduced-motion` support, 44 px minimum touch targets, aria labels/live regions.

## Verification

- `tests/unit/test_overlay_mapping.py` — letterbox mapping pinned across wide/tall/square/exact aspect sources, corner round-trips, clamping, invalid inputs.
- `tests/integration/test_phase5_api.py` — 17 HTTPX2 ASGI contract tests (camera/detector stubbed): liveness/readiness/capabilities, scan commands, fallback upload, library contracts, problem details, logs, and frontend origin.
- `tests/unit/test_scan_service.py` — live-preview sequencing, persistent results, cooperative cancellation, fallback without a detector, one-owner shutdown, and reconnect coverage.
- `tests/unit/test_library.py` — wall-clock persistence and reopen coverage.
- `npm test` — Scan UI decision coverage for detecting/locking, processing, accepted, uncertain, error, cancellation, and fallback selection.
- `tools/verify_phase5_ui.py` — real Chromium automation at exactly 800×480, all required Scan states, no page scroll, no undersized controls, fallback visibility, disabled Weed card, and reproducible screenshots.
- Full Python suite: **71 tests OK** (`python -m unittest discover -s tests`). Frontend: **3 UI state tests OK** and production build succeeds.
- Evidence: [`home-800x480.png`](evidence/phase5/home-800x480.png) and [`scan-result-800x480.png`](evidence/phase5/scan-result-800x480.png).

## How to run

```bash
# one-time
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r config/environments/phase0-python-requirements.txt
.venv/bin/pip install -r config/environments/phase5-python-requirements.txt
cd frontend && npm install && npm run build && cd ..

# run
.venv/bin/python tools/run_api.py            # http://127.0.0.1:8000
.venv/bin/python tools/verify_phase5_ui.py   # automated Chromium UI verification
```

## Deferred / next

- Real species knowledge + Ask (Phase 6), real classifier weights (Phase 7), weed beta (Phase 8).
- On-device real-camera Chromium journey and Stage-1 operator acceptance (see `docs/DEFERRED_OPERATOR_ACCEPTANCE.md`).
- SSE reconnect backoff tuning under sustained Wi-Fi loss (reconnect currently handled by `EventSource` defaults).
