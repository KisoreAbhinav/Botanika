# Pi-Only Repository Structure

The repository is intentionally an empty implementation skeleton. `.gitkeep`
files preserve the planned module boundaries until each stage is authorized.

```text
Botanika/
├── backend/
│   └── src/botanika/
│       ├── api/                 # Local API adapters and schemas
│       ├── core/                # Settings, lifecycle, errors, capabilities
│       ├── hardware/            # Camera/audio/display adapters (future)
│       ├── vision/
│       │   ├── detection/       # Plant/organ detector
│       │   ├── quality/         # Stability, focus, exposure, crop
│       │   ├── classification/  # Regional species classifier
│       │   └── weeds/           # Dedicated beta detector
│       ├── knowledge/           # Retrieval, citations, grounded chat
│       ├── voice/               # STT, TTS, audio ownership
│       ├── discoveries/         # Save/group/export/delete behavior
│       ├── storage/             # SQLite migrations/repositories/backups
│       └── observability/       # Health, metrics, redacted logging
├── frontend/
│   ├── public/
│   │   ├── brand/               # Wordmark and decorative foliage
│   │   ├── models/              # Only if browser runtime is later justified
│   │   └── maps/                # Reserved; no map without GNSS
│   └── src/
│       ├── app/                 # Routes, boot, capabilities
│       ├── components/          # Accessible shared primitives
│       ├── features/
│       │   ├── home/            # E-ink three-action homepage
│       │   ├── scan/            # Pi Camera preview and scan flow
│       │   ├── library/         # Local list/details/history
│       │   ├── chat/            # Offline botanical guide
│       │   └── weeds/           # Final beta UI
│       ├── platform/
│       │   ├── camera/          # Local camera UI adapter
│       │   ├── inference/       # Local UI/model adapter if needed
│       │   └── storage/         # UI cache/preferences, not authority
│       └── theme/               # E-ink tokens and accessibility
├── config/
│   ├── environments/            # Versioned non-secret local defaults
│   └── models/                  # Runtime model registry/contracts
├── data/
│   ├── seed/                    # Small reproducible seed inputs
│   ├── knowledge/               # Source manifests/prepared corpus
│   ├── vectors/                 # Generated embedding index
│   ├── database/                # Generated SQLite files
│   └── media/
│       ├── discoveries/         # Saved crop-only library images
│       └── temp/                # Transient capture/crop work
├── models/
│   ├── detectors/
│   ├── plant_classifier/
│   ├── weed_detector/
│   ├── stt/
│   ├── tts/
│   ├── llm/
│   └── embeddings/
├── deploy/
│   ├── systemd/                 # Local backend/maintenance units
│   └── kiosk/                   # Fullscreen Pi browser session
├── tests/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   ├── hardware/
│   ├── performance/
│   └── fixtures/
├── tools/                       # Calibration, preparation, backup, benchmark
├── docs/
│   ├── PI_ARCHITECTURE_AND_ROADMAP.md
│   ├── REPOSITORY_STRUCTURE.md
│   ├── STAGE0_TEST_RUNBOOK.md
│   └── decisions/
├── prompt.md                    # Authoritative next-session instructions
├── BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md
│                                # Complete dependency-ordered build prompt
├── .gitignore
└── README.md
```

## Boundary rules

1. The backend owns hardware, authoritative data, and inference decisions.
2. The frontend is a local kiosk and never becomes the source of botanical facts.
3. Generated data and large models remain outside source packages and normal Git
   history.
4. Every model needs a complete contract and Pi benchmark before activation.
5. `tools` prepares or verifies assets but is not imported by request handlers.
6. Runtime services bind to loopback during the Pi-only phase.
7. Tests use synthetic/licensed fixtures, never real personal discovery data.
