# Phase 8 Implementation Report — Responsive Pairing and Mode Handoff

**Started:** 2026-09-03
**Last verified:** 2026-09-03
**Scope:** BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md → Phase 8
**Status:** implementation delivered; physical/operator exit gate deferred

## Outcome delivered

- Added a thread-safe SOLO, NETWORKED_UNPAIRED, NETWORKED_PAIRED state machine.
- Added short-lived single-use pairing invitations and one active bearer lease.
  Mode changes, disconnect, expiry, takeover, and restart revoke the lease.
- Added one debounced GPIO adapter with configurable BCM pins, safe SOLO boot
  mapping, LED updates, idempotent cleanup, and NullGPIO/software fallback.
- Added mode/status, pairing, heartbeat, disconnect, takeover, and bounded
  controller-crop API routes. The raw controller token is returned only during
  pairing; status retains only redacted lease data.
- Restricted Pi operator actions to loopback, redacted the pairing code from
  remote status/landing responses, and required the active controller lease for
  network feature, library, crop, and discovery-media access.
- Bound crop publication and authoritative save to the same live lease, request
  ID, and crop hash so takeover, expiry, mode changes, and stale responses fail
  closed without publishing or saving the wrong crop.
- Kept the Pi as the only classifier and library authority. The paired browser
  owns its camera/capture surface, performs local still-image quality/manual-crop handling,
  and sends a hash-checked crop rather than a live stream.
- Added returned classification details, local result-box display, explicit
  retry/cancel retention, lease-loss/reconnect handling, and save-time optional
  browser geolocation. Location denial, unavailability, and inaccurate fixes do
  not block saving.
- Added a separate responsive portrait shell while retaining the Pi’s exact
  800×480 shell and a Pi status console for paired mode.
- Added a secure-context-aware camera path: HTTPS-capable browsers use local
  `getUserMedia`; private-HTTP clients use the native still-camera file input.
  Geolocation is skipped on insecure origins and never blocks saving.
- Connection health now uses heartbeat freshness, and configured production AP
  mode cannot leave SOLO unless the measured private network is available.

## Files changed

Backend and runtime:

- backend/src/botanika/mode/
- backend/src/botanika/hardware/gpio.py
- backend/src/botanika/api/routes/mode.py
- backend/src/botanika/api/app.py
- backend/src/botanika/api/runtime.py
- backend/src/botanika/api/schemas.py
- backend/src/botanika/core/settings.py
- backend/src/botanika/core/capabilities.py
- backend/src/botanika/core/errors.py
- backend/src/botanika/storage/discoveries.py
- backend/src/botanika/vision/quality/capture.py
- backend/src/botanika/vision/services/scan.py

Frontend:

- frontend/src/app/App.jsx
- frontend/src/features/mode/
- frontend/src/features/networked/NetworkedScanPage.jsx
- frontend/src/features/scan/ScanPage.jsx
- frontend/src/platform/api.js
- frontend/src/theme/theme.css
- frontend/package.json and frontend/package-lock.json

Verification, configuration, deployment, and documentation:

- tests/unit/test_phase8_mode.py
- tests/integration/test_phase5_api.py
- frontend/src/features/mode/modeState.test.js
- tools/verify_phase8.py
- tools/verify_phase8_ui.py
- config/environments/phase7-network.env.example
- README.md, backend/README.md, frontend/README.md, config/README.md
- deploy/README.md, tests/README.md, tools/README.md
- docs/DEFERRED_OPERATOR_ACCEPTANCE.md and docs/REPOSITORY_STRUCTURE.md
- docs/evidence/phase8/ (local Chromium layout evidence)

## Commands and results

- PYTHONPATH=backend/src .venv/bin/python -m unittest discover -s tests -p
  'test_*.py' — 122 tests passed.
- PYTHONPATH=backend/src .venv/bin/python tools/verify_phase8.py --strict —
  19 deterministic/static checks passed.
- npm test — 3 frontend test files passed.
- npm run build — Vite production build passed; 46 modules transformed.
- PYTHONPATH=backend/src .venv/bin/python tools/verify_phase8_ui.py — local
  Chromium rendered all three 800×480 Pi states and the portrait pairing,
  paired-client, camera-fallback, and manual-crop states.
- PYTHONPATH=backend/src python -m compileall -q backend/src
  tools/verify_phase8.py tools/verify_phase8_ui.py — passed.
- git diff --check — passed.

The Phase 8 integration test covers operator/remote separation, remote pairing
code redaction, local-only takeover and scan commands, anonymous library/media
rejection, same-site controller-cookie access, one-controller rejection,
uploaded crop hash/dimensions, stale-save rejection, classification/save with
position, repeated-species saves, disconnect, takeover, and return to SOLO.
Unit coverage also exercises heartbeat health and takeover during inference.
The UI smoke check writes `solo-800x480.png`,
`networked-unpaired-800x480.png`, `networked-paired-800x480.png`,
`pairing-browser-390x844.png`, `paired-browser-home-390x844.png`,
`paired-camera-390x844.png`, and `paired-manual-crop-390x844.png`.

## Real Pi measurements

No new real Pi measurements were available in this workspace. The physical
GPIO button/LEDs, Pi Camera, AP/DHCP/DNS stack, 800×480 hardware display,
paired phone camera permissions, thermal/latency behaviour, and reboot/recovery
journey were not exercised. No result is claimed for those checks.

## Screenshots and evidence

The generated screenshots are local Chromium renders with mocked API responses;
they verify viewport dimensions, shell sizing, responsive overflow, and visible
fallback/manual-crop UI. They are not hardware or phone captures. The physical
button, AP, camera-permission, and touch/reboot checks remain in the deferred
operator checklist.

## Exit-gate verdict

The Phase 8 implementation contract is present and automated checks pass, but
the Phase 8 exit gate is **not passed** because the required physical journey
has not been observed: mode-button press → private Wi-Fi join → pairing →
phone camera → local stable crop → crop-only upload → Pi classification →
authoritative save → Pi status-console update → safe return to SOLO.

Phase 9 is not eligible yet. Complete and record the deferred Phase 8 Pi and
phone checks in docs/DEFERRED_OPERATOR_ACCEPTANCE.md before advancing.
