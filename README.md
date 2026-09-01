# Botanika

Botanika is a Raspberry Pi 5 field-intelligence system for identifying native
plants, recording discoveries, mapping conservation context, detecting weeds,
and answering botanical questions by voice. The Pi is the single backend and
knowledge source; the same e-ink-themed web interface is intended to run on the
Pi screen and in a phone browser.

This repository now contains the first connectivity-stage application slice:
the loopback-bound FastAPI origin, crop receipt contract, status WebSocket, and
dependency-free browser placeholder. Model binaries and the later botanical
application stages are not included yet.

## Start here

- [Phone ↔ Pi connectivity implementation guide](PHONE_PI_CONNECTIVITY_IMPLEMENTATION.md)
- [Stage 0 deployment and test runbook](docs/STAGE0_TEST_RUNBOOK.md)
- [Pi architecture and implementation roadmap](docs/PI_ARCHITECTURE_AND_ROADMAP.md)
- [Repository structure](docs/REPOSITORY_STRUCTURE.md)
- [Architecture decisions](docs/decisions/README.md)
- [Original project brief](prompt.md)

## Current scope

The current design covers the Pi-hosted backend, the Pi-served web application,
Pi camera/kiosk behavior, internet-routable phone access, offline botanical
knowledge, voice control, storage, deployment, and verification boundaries.
Training pipelines and drone actuation are deliberately outside the first
implementation scope.
