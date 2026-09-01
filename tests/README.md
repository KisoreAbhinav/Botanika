# Verification Boundary

Tests will be organized by:

- API, data, and model contracts;
- module/database/model integration;
- local kiosk end-to-end flows;
- actual Pi camera/audio/display hardware;
- latency, memory, thermal, and soak performance;
- licensed or synthetic fixtures.

Phase 1 begins the executable test boundary with hardware-independent camera
configuration, RGB888-to-BGR conversion, lifecycle, dropped-frame, and partial
startup cleanup tests. Phase 2 adds detector contract/coordinate tests; Phase 3
adds deterministic tracking, quality, cooldown, and crop-only filesystem tests.
Hardware checks remain separate and are run on the Pi.
