# Repository Structure

This skeleton is intentionally organized around ownership and runtime boundaries
before code exists. Empty leaf directories contain `.gitkeep` so Git preserves
the planned shape.

```text
Botanika/
├── backend/
│   └── src/botanika/
│       ├── api/                 # HTTP/WS adapters and schemas
│       ├── core/                # settings, errors, lifecycle, inference budget
│       ├── modes/               # SOLO/NETWORKED state and policy
│       ├── pairing/             # ticket, session, lease, heartbeat
│       ├── vision/
│       │   ├── detection/       # Pi-camera detector adapter
│       │   ├── classification/  # species model registry and ranking
│       │   ├── quality/         # server validation/calibration contracts
│       │   └── weeds/           # independent weed-beta inference
│       ├── knowledge/           # retrieval, citations, online fallback
│       ├── voice/               # STT/TTS/audio ownership and voice intents
│       ├── discoveries/         # aggregate and weed observations
│       ├── storage/             # SQLite repositories/migrations/backups
│       └── observability/       # health, metrics, redacted events
├── frontend/
│   ├── public/
│   │   ├── brand/               # Botanika logo and decorative foliage
│   │   ├── models/              # browser detector artifacts/manifests
│   │   └── maps/                # regional tile/style assets
│   └── src/
│       ├── app/                 # routes, boot, capability/profile selection
│       ├── components/          # accessible shared UI primitives
│       ├── features/
│       │   ├── home/            # three-action e-ink homepage
│       │   ├── scan/            # live boxes, lock, crop, result, save
│       │   ├── library/         # map/list/details and species grouping
│       │   ├── weeds/           # beta camera/upload and coordinates
│       │   ├── chat/            # Pi botanical guide UI
│       │   └── pairing/         # placeholder, code, controller console
│       ├── platform/
│       │   ├── camera/          # browser/Pi camera capability adapter
│       │   ├── geolocation/     # permission, accuracy, timeout
│       │   ├── inference/       # ONNX Runtime Web worker adapter
│       │   ├── storage/         # IndexedDB schema and migrations
│       │   └── realtime/        # WebSocket state/reconnect
│       └── theme/               # e-ink tokens, responsive/accessibility rules
├── config/
│   ├── environments/            # versioned non-secret defaults
│   └── models/                  # runtime model contracts and registry
├── data/
│   ├── seed/                    # small curated/reproducible seed inputs
│   ├── knowledge/               # source manifests and prepared corpus
│   ├── vectors/                 # generated embedding index (ignored)
│   ├── database/                # generated SQLite state (ignored)
│   └── media/
│       ├── discoveries/         # reserved opt-in Pi media state (ignored)
│       └── temp/                # short-lived uploads (ignored)
├── models/
│   ├── detectors/               # local plant/organ detector contract
│   ├── plant_classifier/        # regional classifier contract
│   ├── weed_detector/           # crop/region-specific detector contract
│   ├── stt/                     # Vosk/Whisper assets and provenance
│   ├── tts/                     # Piper assets and provenance
│   ├── llm/                     # GGUF guide model and license
│   └── embeddings/              # retrieval encoder contract
├── deploy/
│   ├── cloudflared/             # tunnel templates; never credentials
│   ├── reverse_proxy/           # local ingress/static proxy configuration
│   ├── systemd/                 # services, ordering, sandboxing
│   └── kiosk/                   # Pi display/browser session
├── tests/
│   ├── contract/                # API/model/data contract verification
│   ├── integration/             # module/database/model composition
│   ├── e2e/                     # phone and kiosk browser journeys
│   ├── hardware/                # Pi camera/audio/network checks
│   ├── performance/             # latency, memory, thermal, soak tests
│   └── fixtures/                # licensed synthetic/test-only assets
├── tools/                       # preparation, benchmark, backup, verification
├── docs/
│   ├── PI_ARCHITECTURE_AND_ROADMAP.md
│   ├── REPOSITORY_STRUCTURE.md
│   └── decisions/               # short architecture-decision records
├── prompt.md                    # original brief and precedence context
├── .gitignore
└── README.md
```

## Boundary rules

1. `backend` is runtime code; large artifacts live in `models` or generated
   `data`, not inside Python packages.
2. `frontend` owns per-frame detection and the personal browser library. It does
   not contain species facts or authoritative model decisions.
3. `config` is versioned and non-secret. Credentials and local overrides are
   deployment state.
4. `data/seed` and source manifests are reproducible inputs. Database, vectors,
   temporary images, and personal data are generated outputs.
5. `models` requires a complete model contract before weights are enabled.
6. `deploy` contains templates and units, never tunnel credentials or private
   keys.
7. `tools` may prepare runtime assets but is not imported by request handlers.
8. `tests/fixtures` may not contain a user’s real discovery image or location.
