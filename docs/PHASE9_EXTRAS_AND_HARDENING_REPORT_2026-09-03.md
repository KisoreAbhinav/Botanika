# Phase 9 — Extras and final hardening report

Date: 2026-09-03
Status: software hardening complete; physical/model release gate deferred

## Outcome

Phase 9 is implemented as capability-gated local functionality:

- Offline knowledge ingestion now validates a tracked source/license manifest,
  seeds SQLite FTS5, builds a deterministic versioned 256-dimensional compact
  embedding index, and retains chunk-level citations. Typed answers use exact
  reviewed retrieval and explicitly abstain when evidence is insufficient.
- An optional llama.cpp/GGUF adapter accepts generated wording only when every
  factual sentence cites an allowed retrieved chunk ID. It never downloads a
  model. Vosk/Piper voice operations share one bounded audio coordinator with
  silence endpointing, cached models, real capture/playback interruption, and
  typed-chat fallback. Blocking audio, LLM, and weed inference work is kept
  off the FastAPI event loop. Voice navigation can open Home, Scan, Library,
  or Weed Beta locally.
- Library progress is derived from active saved discoveries: supported-catalog
  coverage, category progress, first/repeat indicators, milestones, and an
  anonymous local aggregate summary are exposed in the API and UI.
- Weed Beta has a separate manifest, detector/service boundary, SOLO camera
  endpoint, one captured paired-browser-frame endpoint, multi-box/confidence
  rendering, exact no-position messaging, coordinate-only persistence, and no
  image or plant-library persistence. Drone and chemical actions are absent.
- Production runtime support includes explicit data/runtime directory creation,
  bounded systemd logging/restart policy, a readiness-gated 800×480 Chromium
  launcher, and deployment/runbook documentation.

## Main files added or changed

Backend/API: `knowledge/embeddings.py`, `knowledge/llm.py`,
`voice/coordinator.py`, `api/concurrency.py`, `storage/weeds.py`,
`vision/weeds/service.py`, the
voice/weed routes, capability/runtime wiring, schema migration 4, and library
progress methods.

Frontend: Ask Botanika transcript/citation/voice controls, local voice
navigation, catalog progress/milestones, the independent Weed Beta screen,
transient SOLO analyzed-frame rendering, and tested contained-box geometry.

Configuration and tools: `config/knowledge/source-license-manifest.json`,
`config/llm/phase9-llama.example.json`, `config/weed/phase9-beta.json`,
`tools/ingest_knowledge.py`, `tools/benchmark_local_llm.py`,
`tools/verify_phase9.py`, `tools/verify_phase9_ui.py`, and
`tools/launch_kiosk.py`.

Deployment/docs: `deploy/systemd/botanika-kiosk.service`,
`deploy/systemd/botanika-tmpfiles.conf`, `deploy/kiosk/README.md`, and the
Phase 9 updates to the configuration, deployment, backend, frontend, and tool
runbooks.

## Verification and evidence

- `PYTHONPATH=backend/src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'` — 128 tests passed, including six maintainable Phase 9 regression tests for progress restore/delete, weed persistence safety, voice interruption, LLM grounding, production paths, and the bounded blocking bridge.
- `PYTHONPATH=backend/src .venv/bin/python tools/verify_phase9.py --strict` — all deterministic checks passed, including 14 indexed chunks, 256-dimensional embeddings, grounded abstention, progress derivation, voice WAV/endpoint bounds, and accurate-coordinate-only weed persistence.
- `npm run build` — production Vite build passed; final bundle was 209.67 kB JavaScript (65.40 kB gzip) and 28.86 kB CSS (6.12 kB gzip).
- `npm test` — 4 frontend tests passed, including contained image/box geometry at kiosk and phone aspect ratios.
- `PYTHONPATH=backend/src .venv/bin/python tools/verify_phase8_ui.py` — existing mode/paired UI smoke test passed.
- `PYTHONPATH=backend/src .venv/bin/python tools/verify_phase9_ui.py` — chat and Weed Beta UI smoke test passed at 800×480 and 390×844 (fixture smoke only; the detector asset remains unavailable).
- `tools/ingest_knowledge.py` — 11 sources and 14 chunks indexed; manifest digest `a52ee3f215f03104893118453ce94995ea76a1ef2d2b27b5f417ef99450e6bbe`.
- `tools/benchmark_local_llm.py` — deliberately returned exit 2 (`blocked`): `/home/pi/Botanika/models/llm/botanika.gguf` is not installed. The blocked result is recorded in `docs/evidence/phase9/llm-benchmark.json`.

Browser evidence is in:

- `docs/evidence/phase9/ask-800x480.png`
- `docs/evidence/phase9/weeds-800x480.png`
- `docs/evidence/phase9/weeds-browser-390x844.png`
- `docs/evidence/phase9/knowledge-manifest.json`

These are deterministic local fixtures and do not represent a physical Pi
acceptance journey.

## Pi measurements and limitations

The read-only host probe measured Raspberry Pi 5 Model B Rev 1.1, aarch64,
Debian trixie, 45.2 °C, and approximately 395.4 GiB free SSD space. Chromium,
systemd, OpenCV, NumPy, FastAPI, ONNX Runtime, sounddevice, Vosk, Piper, and
related Python bindings were discoverable. No usable camera/display capture or
microphone/speaker device was available from this session. Botanika has no
installed Vosk model, Piper voice, llama executable/GGUF, or independent weed
ONNX artifact, so those capabilities correctly report unavailable.

The Phase 6 species model remains explicitly field/thermal/unknown-rejection
unvalidated, and the Phase 8 report still has a deferred physical/operator
gate. Consequently, no claim is made for cold boot, audio reacquisition, real
camera Weed Beta inference, llama latency/RAM/temperature, AP pairing recovery,
disk-full/read-only recovery, multi-hour soak, or five structured usability
sessions.

## Gate verdict and next eligible work

The Phase 9 deterministic implementation and UI gates pass. The final Phase 9
exit gate is **deferred**, because the required real-Pi core scan journey,
optional model benchmarks, voice journey, Weed Beta model validation, boot /
recovery / soak checks, and operator acceptance could not be run with the
available devices and artifacts.

There is no numbered phase after Phase 9. The next eligible work is the final
operator acceptance run on the actual Pi after installing and verifying the
manual model/data assets; it must cover the deferred Phase 8 core journey and
the Phase 9 final-acceptance checklist before release.
