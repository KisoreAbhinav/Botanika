# Botanika — Pi-Only Build Prompt

Use this prompt as the authoritative starting point for the next implementation
session.

---

## Role

You are implementing Botanika as a standalone Raspberry Pi application. Work in
small, verified stages. Inspect the repository and hardware before making
changes, preserve unrelated user files, and finish each stage with tests and a
short operator procedure.

Do not redesign the project into a distributed system. The Raspberry Pi is the
only computer, backend, camera host, datastore, inference device, and display
host in this phase.

## Hardware

- Raspberry Pi 5 with 16 GB RAM
- 512 GB SSD
- Pi Camera
- Pi-connected screen
- Microphone
- Speaker
- Keyboard/mouse or touchscreen for development and recovery

Physical mode buttons, LEDs, external GPS, drones, and agricultural actuators
are not part of the initial build.

## Hard scope boundary

Build and verify everything locally on the Pi.

Do not implement:

- cloud inference;
- user accounts;
- drone or herbicide control.

The UI may use web technology, but it must be served on loopback and displayed
by a kiosk browser running on the Pi itself.

## Product objective

Create a reliable local field-intelligence application with four connected
capabilities:

1. Identify a plant from the Pi Camera.
2. Save an accepted identification into a local discovery library.
3. Answer botanical questions from an offline sourced knowledge base using text
   and voice.
4. Detect supported weeds as an explicitly marked beta feature built last.

The system must continue working without internet access. Optional online search
may be added only after the complete offline application is stable.

## User interface

Run one responsive local web application in a fullscreen kiosk browser on the Pi
screen.

### Visual direction

- E-ink-inspired warm paper background
- Near-black text
- Restrained botanical-green accents
- Botanika plant/leaf wordmark centered at the top
- Decorative leaves and bushes in the lower-left and lower-right corners
- Large touch-friendly controls
- High contrast and readable typography
- Minimal animation
- Clear focus states and keyboard/touch support
- Reduced-motion support

### Homepage

Show three primary actions centered between the wordmark and corner foliage:

1. **Scan for Plants**
2. **Library**
3. **Weed Detection · Beta**

Also provide a visible route to the botanical chat interface without crowding
the three main actions. A compact “Ask Botanika” control or persistent navigation
item is acceptable.

## Plant scan behavior

### Live detection

1. Open the Pi Camera locally.
2. Run a small plant/organ detector on resized frames on the Pi.
3. Draw live bounding boxes over the preview.
4. At first, labels describe the target (`Plant`, `Leaf`, `Flower`, or similar),
   not a species name.
5. If several boxes exist, select the largest stable central target by default
   and allow the user to choose another target.

Do not run fine-grained species classification on every video frame.

### Automatic capture gate

Track the selected box across consecutive frames. Capture becomes eligible only
when:

- box overlap is stable;
- center movement is low;
- size change is low;
- the target occupies enough pixels;
- the target is not clipped by the image edge;
- exposure is usable;
- a Laplacian or equivalent focus score passes a calibrated threshold;
- the conditions pass for several consecutive checks.

Thresholds must be calibrated on the actual Pi Camera. Do not present arbitrary
constants as validated settings. Keep a manual capture button as a fallback.

### Crop-only classifier input

When capture is accepted:

1. Capture one still frame in Pi memory.
2. Expand the selected box by a small configurable context margin.
3. Clamp the crop to frame bounds.
4. Correct orientation.
5. Extract only the bounding-box crop.
6. Release the complete frame.
7. Run the species classifier on the crop once.

The classifier must not receive a long video sequence. The discovery library
must not save the complete frame.

### Classification result

The classifier returns calibrated top candidates and supports an explicit
unknown/low-confidence result.

For an accepted result:

- show the common/scientific plant name above the selected box;
- show calibrated confidence below the box;
- populate a details panel with family, conservation status, category, ecology,
  and sourced notes;
- provide **Save to Library**, **Retake**, and **Try another angle** actions.

For an uncertain result, say that Botanika is not confident and suggest another
view such as leaf, flower, fruit, bark, or the whole plant. Never force a species
label just to complete the interaction.

## Model strategy

Use a two-stage local vision pipeline:

1. A tiny detector for real-time boxes.
2. A regional species classifier for the accepted crop.

Generic pretrained YOLO weights do not provide reliable regional botanical
species identification. Use them only as a starting point for the detector if
their license is acceptable. Train or fine-tune with a deliberately bounded
regional dataset.

Start with one regional general classifier, using a compact backbone such as
MobileNetV3 or EfficientNet-Lite. Benchmark model formats supported efficiently
on the Pi, such as TFLite or ONNX Runtime. Add specialist flower/tree/leaf models
only if the confusion matrix proves a specific need and the system can route to
them reliably.

Every activated model requires:

- version and artifact checksum;
- immutable label map;
- dataset and license provenance;
- geographic and taxonomic scope;
- preprocessing and output contract;
- class-wise metrics;
- calibration method and rejection threshold;
- held-out field-test results;
- Pi latency, memory, temperature, and throttling results;
- known unsupported classes and views.

## Local discovery library

Store the authoritative personal library on the Pi using SQLite plus a managed
local media directory.

### Save rules

- Save only the classifier crop, never the full frame.
- Group records by stable species ID.
- If the same species is found again, append another observation and crop to the
  existing species entry.
- Do not create duplicate species rows for repeated discoveries.
- Save capture time, classifier version, result snapshot, confidence, crop hash,
  and any optional operator note.
- Prevent accidental duplicate saves using crop hash and a short time window.

The Pi does not currently have a location source. Do not invent coordinates or
derive them from network information. The local library should work without a
map. If external GNSS is added later, store latitude, longitude, accuracy, and
source explicitly and add the map as a separate stage.

### Library screen

Show:

- a scrollable species list;
- newest crop thumbnail on the left;
- common and scientific names;
- color/symbol based on conservation/category priority;
- a vertical three-dot details action;
- expanded view containing every saved crop and observation for that species;
- full saved botanical details and source references;
- export and delete controls with confirmation.

Initial visual priority:

1. Threatened/endangered: muted rust plus warning symbol.
2. Region-specific/native: deep green plus leaf symbol.
3. Generic: graphite plus circle symbol.

If a species is both native and threatened, threat color wins and the native
symbol remains.

## Botanical knowledge and chat

Build an offline, provenance-first botanical guide.

### Knowledge storage

- Normalized species facts in SQLite
- Source record for every conservation/ecology claim
- SQLite FTS5 for names and keywords
- Compact local embedding index for semantic retrieval
- Knowledge chunks linked to species and sources
- Small quantized local language model through llama.cpp

Candidate sources may include curated regional floras/herbaria, IUCN data, GBIF
occurrences, and licensed Wikipedia/Wikidata extracts. Review license and
geographic scope before ingestion. Do not infer “native” from occurrence points
alone.

### Answer policy

- Retrieve evidence before generating an answer.
- Prefer the currently scanned/selected species when relevant.
- Show source citations with the response.
- If local evidence is insufficient, say so explicitly.
- Do not let the language model invent missing facts.
- Keep optional internet search disabled until the offline path passes its tests.

### Voice interface

Use the Pi microphone and speaker only.

Reuse the reliable architectural patterns from the local HYDRA/InnoHack work:

- one explicit audio owner;
- cached speech models;
- streaming capture and silence endpointing;
- maximum turn duration;
- interruption/cancellation of speech output;
- no implicit model download during offline use;
- Piper voice cached in process;
- visible transcript and response alongside audio.

Benchmark Vosk Indian-English and Whisper.cpp/faster-whisper on the Pi. A useful
initial split is Vosk for small deterministic commands and a tiny/base Whisper
variant for free-form botanical questions. Use Piper for offline speech output.

## Weed Detection beta

Build this only after plant scanning, classification, library, and chat are
stable.

“Weed” depends on crop and region. Define the supported field context and weed
species before training. Use a dedicated bounding-box detector and clearly show
unsupported scope.

The beta should:

- accept the Pi Camera or one locally selected image;
- draw all supported weed boxes and confidence values;
- avoid adding weeds to the plant discovery library;
- discard temporary images after the result;
- show a notice that coordinates are unavailable when no GNSS device exists;
- never issue commands to a drone or chemical applicator.

## Backend architecture

Use one FastAPI modular monolith rather than microservices. The Pi needs shared
control of camera, audio, CPU, RAM, and model inference.

Suggested internal modules:

- API and response schemas
- settings and lifecycle
- hardware/camera adapter
- inference coordinator
- detection
- image quality and crop processing
- species classification
- knowledge retrieval and chat
- voice/audio ownership
- discoveries/library
- SQLite storage and migrations
- weed detection
- health, metrics, and redacted logging

Give interactive scanning higher priority than chat generation or background
indexing. Start with one heavy inference job at a time until Pi benchmarks prove
safe concurrency.

## Runtime and deployment

- Bind the development/local production service to loopback.
- Serve the built frontend and local API from the same origin.
- Launch a fullscreen kiosk browser after backend readiness.
- Supervise backend and kiosk through systemd once local development is stable.
- Store generated databases/media outside the source packages.
- Keep secrets and machine-local environment files outside Git.
- Use bounded rotating logs without image data or raw voice transcripts by
  default.
- Back up SQLite and discovery crops and test restoration.

## Failure behavior

The application must degrade clearly instead of crashing:

| Failure | Required behavior |
|---|---|
| Pi Camera absent/busy | Explain problem and offer local image upload |
| Detector missing | Disable automatic boxes; keep manual image path |
| Frame blurry/unstable | Keep preview and show one actionable hint |
| Classifier missing | Mark identification unavailable; preserve camera UI |
| Low confidence | Ask for another angle; do not claim a species |
| Database unavailable | Block saves, keep unsaved crop in memory, show recovery action |
| Disk full | Stop saves safely and explain required cleanup |
| Microphone unavailable | Keep text chat fully usable |
| Piper unavailable | Keep on-screen answer; mark speech unavailable |
| Offline knowledge lacks answer | Say evidence is insufficient |
| Location unavailable | Continue normally without map/coordinates |
| Weed model absent | Disable beta feature with supported-scope message |

## Required build order

Implement only one stage at a time.

### Stage 0 — Hardware and performance baseline

1. Record OS, Python, camera stack, display resolution, audio devices, storage,
   CPU temperature, and available RAM.
2. Verify Pi Camera capture through the supported Raspberry Pi camera stack.
3. Verify microphone capture and speaker playback independently.
4. Decide the kiosk resolution and development input method.
5. Establish repeatable health checks.

**Gate:** camera, display, microphone, speaker, SSD, and thermal readings are
known and reproducible.

### Stage 1 — Local application foundation

1. Pin Python/Node/package-manager versions.
2. Create the minimal FastAPI and frontend shells.
3. Serve both on loopback from one origin.
4. Add settings, structured logs, request IDs, liveness, readiness, and
   capability reporting.
5. Add SQLite migration and backup foundations.
6. Add local development tests.

**Gate:** Pi browser opens the local shell and reboot/dependency failures are
diagnosable.

### Stage 2 — E-ink kiosk UI and camera

1. Build the themed homepage and navigation.
2. Add the Pi Camera adapter and preview.
3. Add permission/device/error states and local image fallback.
4. Add kiosk launch and resolution checks.

**Gate:** the Pi can start the UI and show a stable local camera preview.

### Stage 3 — Detection and quality-controlled crop

1. Define detector classes and model contract.
2. Benchmark tiny model candidates on the Pi.
3. Add live boxes, target selection, stability, exposure, blur, and manual
   capture.
4. Verify crop coordinate conversion using test patterns.
5. Prove the full frame is never saved.

**Gate:** the actual Pi Camera meets measured latency and false-capture targets.

### Stage 4 — Regional species classifier

1. Freeze the first region and supported species list.
2. Curate and deduplicate datasets by observation.
3. Train off-Pi if necessary, then export and benchmark on Pi.
4. Add calibration, unknown rejection, and species database join.
5. Render name/confidence/details around the existing box.

**Gate:** held-out regional field tests and Pi thermal/latency targets pass.

### Stage 5 — Local library

1. Add SQLite schema and managed crop storage.
2. Implement explicit save and species grouping.
3. Build list/details/history UI.
4. Add export, delete, quota, backup, restore, and migration tests.

**Gate:** one species remains one entry with multiple crops/observations, and no
full frame persists.

### Stage 6 — Offline botanical chat and voice

1. Curate and ingest sourced knowledge.
2. Add FTS, embeddings, and retrieval tests.
3. Benchmark a small quantized LLM.
4. Add grounded text chat and citations.
5. Add STT, Piper TTS, cancellation, and audio ownership.

**Gate:** factual answers are traceable to retrieved sources and missing answers
abstain.

### Stage 7 — Weed beta

1. Define crop/region and supported weeds.
2. Train/validate a dedicated detector.
3. Add local multi-box UI and temporary-image cleanup.
4. Add safety and unsupported-scope messaging.

**Gate:** no weed image/library entry persists and unsupported classes are not
claimed.

### Stage 8 — Hardening and feedback

1. Run performance, thermal, soak, disk-full, restart, and recovery tests.
2. Conduct at least five structured user evaluations.
3. Record changes resulting from feedback.
4. Complete model/data/source/license registers and submission traceability.

## First task for the next session

Start with **Stage 0 only**.

Inspect the actual Pi and produce a short hardware/readiness report covering:

- OS and architecture;
- Pi Camera detection and one still-capture verification;
- microphone input device and a short non-persistent level/capture check;
- speaker output device and a short test tone or spoken test;
- connected screen resolution;
- SSD free space and filesystem;
- CPU temperature and throttling state;
- Python/Node versions already installed;
- missing packages or hardware blockers.

Do not build the UI or install models during that first task. Do not modify
HYDRA or InnoHack. Use them only as read-only references for later voice design.
Return the hardware report, recommended pinned runtime versions, and the exact
Stage 1 plan. Stop there for review.
