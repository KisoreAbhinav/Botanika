# ADR-0002: Modular Monolith on the Pi

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

Classification, RAG, voice, camera, storage, pairing, and web APIs share one Pi.
They need coordinated CPU/RAM budgets and exclusive camera/audio ownership.

## Decision

Implement one FastAPI process boundary with explicit internal modules and one
inference coordinator. Run infrastructure concerns such as the reverse proxy,
tunnel, and kiosk browser as separate supervised processes.

## Consequences

- Deployment, tracing, and resource control stay simple.
- Domain boundaries remain testable without network hops.
- A module may be extracted later if profiling proves isolation is necessary.
- Module dependency rules and bounded queues are mandatory to prevent a single
  process from becoming an unstructured monolith.
