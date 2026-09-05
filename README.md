# Botanika

Botanika is a standalone Raspberry Pi 5 field-intelligence application for
identifying native plants, keeping a local discovery library, detecting weeds,
and answering botanical questions through an offline voice-enabled interface.

The project follows a **Pi-only architecture baseline** and is delivered one
verified local capability at a time. The current implementation covers the
camera owner, generic detector, lock-on/crop gate, the Phase 6 local catalog
classifier baseline, provenance-first knowledge retrieval, grouped discovery
storage, the 800×480 kiosk interface, the Phase 7 private transport boundary,
and the Phase 8 responsive paired-client/mode handoff. An optional zero-cost
Cloudflare Quick Tunnel now adds internet reachability for a phone on a
different network while the Pi remains authoritative. Phase 9 adds the
provenance-first offline guide/voice boundary, reproducible catalog progress,
and an independent weed-beta/deployment boundary. The shipped classifier
is a compact CPU baseline with explicit unknown rejection; production
acceptance stays disabled until field-held-out reliability and a Pi benchmark
satisfy the deployment gate.

## Start here

- [Complete phase-by-phase implementation prompt](BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md)
- [Build prompt entry point](prompt.md)
- [Pi architecture and implementation roadmap](docs/PI_ARCHITECTURE_AND_ROADMAP.md)
- [Stage 0 hardware-readiness runbook](docs/STAGE0_TEST_RUNBOOK.md)
- [Stage 0 readiness report](docs/STAGE0_READINESS_REPORT_2026-09-01.md)
- [Phase 1 raw-feed report](docs/PHASE1_RAW_FEED_REPORT_2026-09-01.md)
- [Phase 2 generic detection report](docs/PHASE2_GENERIC_DETECTION_REPORT_2026-09-01.md)
- [Phase 3 lock-on report](docs/PHASE3_LOCK_ON_REPORT_2026-09-01.md)
- [Phase 4 classifier report](docs/PHASE4_CLASSIFIER_REPORT_2026-09-01.md)
- [Phase 5 service and kiosk report](docs/PHASE5_SERVICE_AND_KIOSK_REPORT_2026-09-02.md)
- [Phase 6 species, knowledge, and library report](docs/PHASE6_SPECIES_KNOWLEDGE_LIBRARY_REPORT_2026-09-02.md)
- [Phase 7 private Wi-Fi report](docs/PHASE7_PRIVATE_WIFI_REPORT_2026-09-03.md)
- [Phase 8 pairing and responsive client report](docs/PHASE8_RESPONSIVE_PAIRING_REPORT_2026-09-03.md)
- [Phase 9 extras and hardening report](docs/PHASE9_EXTRAS_AND_HARDENING_REPORT_2026-09-03.md)
- [Cross-network Quick Tunnel and phone weed evidence](docs/PHASE9_CROSS_NETWORK_QUICK_TUNNEL_AND_PHONE_WEEDS.md)
- [Deferred final operator acceptance](docs/DEFERRED_OPERATOR_ACCEPTANCE.md)
- [Repository structure](docs/REPOSITORY_STRUCTURE.md)
- [Architecture decisions](docs/decisions/README.md)

## Current scope

- Raspberry Pi 5, Pi Camera, screen, microphone, speaker, and SSD
- One locally hosted web interface displayed in a Pi kiosk browser
- Local plant detection, crop-quality checks, and compact species classification
- Local SQLite species knowledge, provenance, and discovery data
- Local cropped discovery images
- Private Pi Wi-Fi handoff with one paired browser controller
- Optional no-account Cloudflare Quick Tunnel handoff over HTTPS (AP remains a fallback)
- Responsive phone camera flow with crop-only upload and optional save-time location
- Offline botanical RAG, speech-to-text, and text-to-speech
- Weed detection as the final beta stage

## Optional internet pairing (free Quick Tunnel)

The default remains loopback-only and offline. To let a phone reach the Pi
through the public internet, install `cloudflared` locally and set
`BOTANIKA_NETWORK_ENABLED=false`, `BOTANIKA_HOST=127.0.0.1`,
`BOTANIKA_LOOPBACK_ONLY=true`, and `BOTANIKA_TUNNEL_ENABLED=true` in the service
environment. Press NETWORKED on the Pi; Botanika starts `cloudflared tunnel
--config /dev/null --no-autoupdate --url http://127.0.0.1:8000` in the
background, displays its HTTPS URL as a QR
code, and keeps the pairing code on the Pi screen only. The phone opens the
temporary URL, prefills the code from the QR deep link, and explicitly submits
pairing. Polling and crop uploads are used instead of SSE.

Cloudflare Quick Tunnels require no account, domain, or charge, but Cloudflare
documents them for development/testing: the URL is random per process, there
is no SLA, the service has a 200 in-flight request limit, and SSE is not
supported. Keep the private AP as a local fallback when internet service is
unavailable.
