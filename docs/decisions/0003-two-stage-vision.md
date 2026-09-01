# ADR-0003: Two-Stage Vision Pipeline

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

Live boxes must feel immediate, but fine-grained species identification is too
heavy and error-sensitive to run on every frame or depend on a video round trip.
Generic pretrained YOLO weights do not provide the required regional taxonomy.

## Decision

Run a tiny plant/organ detector and capture-quality gate on the active device.
Upload one accepted bounding-box crop to a calibrated regional species
classifier on the Pi. Keep weed detection as a separate crop/region-specific
model contract.

## Consequences

- No live video leaves the active device.
- Browser and Pi-camera detector exports must follow the same box/crop contract.
- The first box label is a target/organ; species name appears only after the Pi
  response.
- Regional data curation, unknown rejection, and model calibration are core
  product requirements rather than later polish.
