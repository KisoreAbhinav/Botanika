# ADR-0003: Local Two-Stage Vision Pipeline

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

The Pi kiosk needs responsive live target boxes, while fine-grained species
classification is too heavy and error-sensitive to run on every video frame.
Generic detector weights also do not provide the required regional taxonomy.

## Decision

Run both stages locally on the Pi:

1. A tiny detector locates a plant or useful organ in live Pi Camera frames.
2. Stability and focus checks accept one target and construct a bounding-box
   crop from a transient still.
3. A regional species classifier runs once on that crop.

Weed detection remains a separate crop/region-specific model built after the
main plant workflow.

## Consequences

- No video or image leaves the Pi.
- Detection latency and classification latency are measured independently.
- The initial box label is a target/organ; species appears only after the second
  stage.
- Full frames remain transient; only accepted crops may enter the library.
- Regional data curation, calibration, and unknown rejection are required.
- Specialist organ classifiers are added only after measured evidence justifies
  them.
