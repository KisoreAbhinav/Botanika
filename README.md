# Botanika

Botanika is a standalone Raspberry Pi 5 field-intelligence application for
identifying native plants, keeping a local discovery library, detecting weeds,
and answering botanical questions through an offline voice-enabled interface.

The project follows a **Pi-only architecture baseline** and is delivered one
verified local capability at a time. The current implementation covers the
camera owner, generic detector, lock-on/crop gate, and the Phase 4 classifier
pipeline stub; no production species model is included.

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
- [Deferred final operator acceptance](docs/DEFERRED_OPERATOR_ACCEPTANCE.md)
- [Repository structure](docs/REPOSITORY_STRUCTURE.md)
- [Architecture decisions](docs/decisions/README.md)

## Current scope

- Raspberry Pi 5, Pi Camera, screen, microphone, speaker, and SSD
- One locally hosted web interface displayed in a Pi kiosk browser
- Local plant detection, crop-quality checks, and species classification
- Local SQLite knowledge and discovery data
- Local cropped discovery images
- Offline botanical RAG, speech-to-text, and text-to-speech
- Weed detection as the final beta stage
