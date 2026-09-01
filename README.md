# Botanika

Botanika is a Raspberry Pi 5 field-intelligence system for identifying native
plants, recording discoveries, mapping conservation context, detecting weeds,
and answering botanical questions by voice. The Pi is the single backend and
knowledge source; the same e-ink-themed web interface is intended to run on the
Pi screen and in a phone browser.

This repository is currently in its **architecture-only phase**. It contains no
application code or model binaries yet.

## Start here

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
