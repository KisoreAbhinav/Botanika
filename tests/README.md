# Verification Boundary

Tests will be organized by:

- API, data, and model contracts;
- module/database/model integration;
- local kiosk end-to-end flows;
- actual Pi camera/audio/display hardware;
- latency, memory, thermal, and soak performance;
- licensed or synthetic fixtures.

Phase 1 begins the executable test boundary with hardware-independent camera
configuration, Picamera2 RGB888/OpenCV byte-order validation, lifecycle,
dropped-frame, and partial-startup cleanup tests. Phase 2 adds detector
contract/coordinate tests; Phase 3 adds deterministic tracking, quality,
cooldown, rearming, appearance, and crop-only filesystem tests. Hardware checks
remain separate and are run on the Pi. Phase 4 adds classifier schema,
deterministic stub, crop-path handoff, timing/result association, accepted,
uncertain, error, cancellation, malformed-image, and full camera-to-stub
integration coverage. Phase 4 regressions also cover exact low-confidence
reporting, malformed NumPy dtypes, contradictory result fields, and fail-closed
stub provenance.
Phase 5 adds FastAPI service contract coverage (liveness, readiness,
capabilities, scan state/commands, local-image fallback, demo library CRUD,
problem-detail errors, diagnostics logs, frontend-at-origin) plus the preview
letterbox overlay mapping tests across source aspect ratios. ScanService tests
cover preview sequencing, result hold, cancellation, fallback, ownership, and
reconnect. API tests run through HTTPX2's ASGI transport with hardware stubbed;
frontend state tests use Node's built-in test API. `tools/verify_phase5_ui.py`
drives local Chromium through every required UI state and reproduces the exact
800×480 evidence screenshots.

Phase 6 adds catalog/model integrity, migration, FTS citation and abstention,
compact-classifier unknown rejection and deployment gating, normal-runtime
non-stub selection, exact species citations, species-scoped FTS, versioned
catalog reseeding, crop-only persistence, position/note/category metadata,
thumbnail recovery, grouped repeated observations, quota, failure-atomic
export/delete/restore, and simultaneous knowledge/library access coverage.
`tools/verify_phase6_ui.py` verifies baseline abstention,
grouped-library/details, and grounded-Ask states at exactly 800×480.

Phase 8 adds `tests/unit/test_phase8_mode.py` for explicit mode transitions,
single-use/expiring controller leases, GPIO debounce and LED mapping, and
crop-only upload hash preservation. It also covers heartbeat staleness, AP
transition gating, and takeover during inference. Integration coverage checks
loopback/remote separation, pairing-code redaction, anonymous rejection,
cookie-backed controller access, lease/request/hash-bound save, media access,
position persistence, and repeated-species saves. Browser mode and secure-
context fallback contracts are covered by Node tests; real camera permission
and interrupted physical-network paths remain operator checks because this
environment has no paired phone or camera permission surface.

Phase 7 adds private-network configuration and operator contracts: loopback
defaults, stable AP/DHCP/DNS values, secret redaction, idempotent dry-run
plans, safe disable/recovery, AP-independent SOLO startup, verified firewall
configuration markers, interface-specific DHCP/DNS/API sockets, local DNS
answers, safe loopback fallback, measured AP capability state, the same-origin
network status endpoint, and the device-independent `/connect` landing page.
The repository verifier checks tracked deployment assets without claiming that
a Wi-Fi interface, systemd stack, or phone test passed. Run
`tools/verify_phase7_network.py --live --strict` on the configured Pi for those
operator checks.

Phase 8 adds explicit SOLO/NETWORKED_UNPAIRED/NETWORKED_PAIRED mode, one active
controller lease, debounced GPIO mapping, crop-only pairing API coverage,
browser-owned camera/local quality and save-time location boundaries, and
responsive browser-mode state tests. `tools/verify_phase8_ui.py` uses local
Chromium with mocked API responses to capture the three fixed Pi consoles and
portrait pairing/client evidence; it does not claim the physical Pi/AP/phone
journey.
