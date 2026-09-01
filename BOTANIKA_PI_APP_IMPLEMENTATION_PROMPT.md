# Botanika Pi App — Complete Implementation Prompt

Copy everything below this line into a new implementation session. This is the
authoritative build prompt for the standalone Raspberry Pi version of Botanika.

---

## Role and execution mandate

You are the implementation agent for **Botanika**, a standalone native-plant
field-intelligence kiosk running entirely on one Raspberry Pi 5.

Inspect the repository and the real hardware before changing anything, then
implement the application phase by phase. Do not stop after producing another
plan. You are authorized to implement all phases in this document sequentially,
including application code, tests, local services, and operator documentation.
Pause only for a real hardware blocker, unavailable required dataset/model, an
irreversible action, or a product decision that cannot be inferred safely.

Complete and verify each phase before starting the next. Preserve unrelated
files and existing user work. Keep every claim honest: an unavailable model or
sensor must produce an explicit unavailable state, never fabricated output.

## Fixed product boundary

Botanika runs on one Raspberry Pi and uses:

- Raspberry Pi 5 with 16 GB RAM;
- 512 GB SSD;
- Pi Camera;
- Pi-connected 800×480 screen;
- Pi-connected microphone and speaker; and
- touch, keyboard, or mouse input available on the Pi.

The Pi owns the interface, camera, model inference, botanical knowledge,
discovery library, voice pipeline, data storage, and process supervision. The
runtime must remain useful without internet access. Serve the web interface only
on loopback and display it in Chromium kiosk mode on the Pi screen.

Do not add cloud inference, accounts, fabricated coordinates, agricultural
actuation, or mandatory online services. Optional online botanical search is a
post-release enhancement and is not part of the initial definition of done.

## Product outcome

Deliver one bootable local application with these entry points:

1. **Scan for Plants** — show the Pi Camera, locate plant targets continuously,
   wait for a stable and sharp target, classify one crop, and optionally save it.
2. **Library** — show species-grouped discoveries, their cropped images, saved
   facts, observation history, categories, and any trustworthy position data.
3. **Weed Detection · Beta** — find all supported weeds in one view, show boxes,
   and never add their images to the discovery library.
4. **Ask Botanika** — answer plant questions from a sourced offline knowledge
   base using text, microphone input, on-screen output, and speaker output.

The three large homepage actions are Scan, Library, and Weed Detection. Ask
Botanika is a compact, always-visible header action rather than a fourth large
homepage card.

## Read-only design references

Use the existing InnoHack kiosk as the visual and interaction reference:

- `/home/pi/InnoHack/InnoHack/frontend/src/index.css`
- `/home/pi/InnoHack/InnoHack/frontend/src/App.jsx`
- `/home/pi/InnoHack/InnoHack/frontend/NewThemeReferences/`

Use its proven 800×480 sizing, warm e-ink palette, typography hierarchy,
one-pixel borders, compact action bars, state messaging, and camera treatment.
Do not modify InnoHack. Do not copy its medical wording or screening flow.
Botanika must feel like a botanical application built from the same design
system, not a reskinned medical screen.

For later voice implementation, inspect these read-only references as well:

- `/home/pi/InnoHack/InnoHack/backend/NewListeningLogic/`
- `/home/pi/InnoHack/InnoHack/backend/app/flows/stt.py`
- `/home/pi/InnoHack/InnoHack/backend/app/flows/tts.py`

Reuse reliable patterns, not application-specific behavior.

## Non-negotiable engineering rules

- Use a modular monolith, not microservices.
- Use FastAPI for the local backend and React/Vite for the kiosk interface.
- Use SQLite for authoritative structured data.
- Keep model files and generated runtime data outside source packages.
- One backend camera service owns the Pi Camera.
- One audio coordinator owns microphone and speaker access.
- Run real-time detection on resized frames and fine-grained classification only
  after a capture is accepted.
- Classify and persist the padded bounding-box crop, never the full camera frame.
- Drop stale live frames instead of allowing an inference backlog.
- Start with one heavy inference task at a time until Pi benchmarks justify more.
- Support an explicit `unknown` or `low confidence` result.
- Store source/license/model provenance.
- Never invent botanical facts, confidence, conservation state, or location.
- All destructive actions need confirmation.
- Every screen must fit the 800×480 target without page-level scrolling.
  Scroll only inside designated lists, conversations, or detail panels.

---

# Part I — Exact 800×480 visual system

## 1. Fixed canvas

Use the same device-shell contract as InnoHack:

- viewport and application shell: exactly `800 × 480 px`;
- masthead: `66 px` high;
- screen body: `414 px` high;
- shell overflow: hidden;
- body overflow: hidden;
- screen content padding: normally `12–14 px` vertically and `14–18 px`
  horizontally;
- primary touch target: at least `44 × 44 px`;
- compact icon target: at least `40 × 40 px`;
- normal panel gap: `8–12 px`;
- one-pixel borders;
- corner radius: `2–3 px`, not rounded mobile-style cards.

Develop and take screenshots at exactly 800×480. At other viewport sizes, scale
the entire shell proportionally using the same approach as InnoHack. Do not
reflow the target kiosk layout into a different design.

## 2. Color tokens

Preserve InnoHack’s base palette exactly:

| Token | Value | Use |
|---|---:|---|
| Paper | `#efede3` | Main background |
| Paper deep | `#e2dfd5` | Alternating panels and active rows |
| Surface | `#f7f4e9` | Raised cards and dialogs |
| Ink | `#272724` | Primary text and strong borders |
| Muted | `#5f5e59` | Secondary text |
| Faint | `#85827b` | Disabled metadata |
| Line | `#aaa79e` | Dividers and quiet borders |
| Neutral accent | `#686762` | Scrollbars and secondary states |
| Strong neutral | `#41413d` | Primary neutral buttons |
| Botanical green | `#486b51` | Active plant state, success, native category |
| Warning ochre | `#8a692e` | Uncertain or degraded state |
| Threat rust | `#8b3028` | Threatened species and errors |

Use the InnoHack shadow `0 18px 42px rgba(39, 39, 36, 0.13)` only for dialogs,
alerts, or the outer development shell. Normal panels stay flat.

The background uses the InnoHack 28 px faint grid texture over warm paper. The
camera viewport remains black behind video. Botanical green is restrained: use
it for active boxes, success lines, focus indicators, native species, and small
accents—not as a large saturated background.

## 3. Typography and iconography

- Body and controls: Inter with the same system fallbacks as InnoHack.
- Product name and screen headings: Georgia / Times New Roman serif fallback.
- Confidence, coordinates, stage numbers, and model metrics: UI monospace.
- Body default: 17 px at the root; compact labels may use 10–12 px only when
  paired with a larger readable value.
- Eyebrows: uppercase, bold, 0.12–0.15 em tracking.
- Primary screen heading: approximately 24–30 px depending on available space.
- Do not use emoji as final product icons. Use simple inline SVG line icons with
  square geometry and approximately 1.8 px strokes.

Create a Botanika leaf mark derived from simple leaf/vein geometry. The word
`Botanika` is the main centered brand. Decorative foliage is code-native SVG
line art placed behind content at low contrast.

## 4. Masthead

Use one persistent masthead from `y=0` to `y=65`:

- three-column grid: `150 px / 1fr / 150 px`;
- center: Botanika leaf mark and serif wordmark, visually centered on the full
  800 px canvas;
- left: Back or Home control when needed, otherwise a quiet local-status label;
- right: **Ask Botanika** control plus a small capability indicator;
- bottom border: one pixel ink;
- background: nearly opaque Paper.

Do not place changing content in a way that moves the centered wordmark.
Capability problems open a compact diagnostics popover rather than cluttering
the masthead.

## 5. Homepage pixel layout

Within the body (`y=66…479`):

- centered intro lockup near the top, no more than 72 px tall;
- eyebrow: `LOCAL FIELD INTELLIGENCE`;
- one short line explaining scan, save, and learn;
- three equal action cards in one row;
- action row: approximately `x=52…748`, with three `218 px` cards and `14 px`
  gaps;
- card height: approximately `138–150 px`;
- each card contains a numbered eyebrow, 32–38 px line icon, serif label, and a
  one-line description;
- Weed card includes a small `BETA` badge;
- a quiet status strip sits above the bottom edge and reports Camera, Models,
  Knowledge, and Storage as Ready/Unavailable;
- foliage grows inward from the lower-left and lower-right corners behind the
  cards, never over text or touch targets.

The cards are the buttons. Do not put small buttons inside them. Keyboard
shortcuts may be `1`, `2`, and `3`; Ask Botanika may use `A`.

## 6. Shared interaction states

Every async action exposes a visible state:

- idle;
- starting;
- live/ready;
- waiting for target;
- hold steady;
- improve light;
- move closer;
- target locked;
- capturing;
- processing;
- result;
- uncertain;
- unavailable; and
- recoverable error.

Use text plus shape/icon, never color alone. Loading indicators should resemble
InnoHack’s restrained scan line or progress strip; avoid indefinite decorative
spinners when a concrete state can be reported.

Global toast placement:

- top-right below masthead;
- maximum width `360 px`;
- one-pixel semantic border;
- Surface background;
- auto-dismiss informational messages after 4–6 seconds;
- errors remain until acknowledged;
- never cover the primary action bar.

---

# Part II — Screen-by-screen product design

## 7. Scan for Plants

### Layout

Use a two-column screen under the masthead:

- content inset: `14 px` left/right, `10 px` top, `8 px` bottom;
- left camera workspace: approximately `500 px` wide;
- gap: `12 px`;
- right status/details panel: approximately `252 px` wide;
- main work area: approximately `330 px` high;
- bottom action bar: `44–48 px` high and always visible.

The camera viewport uses `object-fit: contain` over black. Place the overlay
canvas exactly over the rendered video rectangle, not merely over its container.
Test letterboxing and coordinate scaling.

### Live overlay

- Draw all detector boxes with quiet ochre lines.
- Draw the selected box with botanical green when its target checks pass.
- Show detector labels such as Plant, Leaf, Flower, Fruit, or Bark during live
  detection—not a species name.
- Place the live status pill at the top center of the viewport.
- Show a three- or four-step stability progress strip below the status.
- Let the operator tap a different detected box.
- Keep a manual capture button available.

### Automatic capture

Select the largest stable central box by default. Capture only after calibrated
checks pass over consecutive frames:

- box intersection-over-union remains stable;
- center displacement stays below the measured threshold;
- relative size change stays below the measured threshold;
- target has sufficient pixels;
- box is not clipped at an edge;
- exposure is usable;
- crop focus/blur score passes; and
- the conditions hold for a calibrated number of checks.

The right panel initially shows concise guidance and live metrics: target type,
stability, focus, exposure, and target size. Present normalized Ready/Improve
states to users; raw calibration values belong in a collapsible diagnostic view.

### Accepted capture and classification

When capture locks:

1. Freeze the accepted preview briefly.
2. Show `Processing plant…` without removing the target context.
3. Capture one high-quality still in memory.
4. Expand the selected box with a small configured context margin.
5. Clamp it to source bounds and correct orientation exactly once.
6. Extract only that crop.
7. Release the complete still.
8. Run the species classifier once on the crop.

For an accepted classification:

- replace the live detector label above the box with common/scientific name;
- show calibrated confidence immediately below the box;
- render family, category, conservation status, and a short sourced note in the
  right panel;
- bottom actions: **Save to Library**, **Retake**, **Another angle**;
- saving must be explicit and disabled while storage is unavailable.

For low confidence:

- label the result `Not confident` rather than forcing a species;
- show top candidates only as suggestions;
- recommend a useful next view: leaf, flower, fruit, bark, or whole plant;
- actions: **Retake** and **Try another angle**;
- do not allow a guessed result to be saved as a confirmed species.

## 8. Library

### Data behavior

- One stable species ID produces one library entry.
- Repeated discoveries append observations and crop images to the same species.
- Save only the crop.
- Save observation time, confidence, classifier release, result snapshot, crop
  hash, image dimensions, and optional note.
- Deduplicate rapid accidental saves using crop hash plus a short time window.
- Each saved image remains linked to its own observation.

### 800×480 layout

Use two stacked regions as originally requested:

1. A top geographic/coverage panel approximately `132 px` high.
2. A bottom species list occupying the remaining scrollable region.

The toolbar above them contains the title, discovered-species count, category
filter, and sort control. Keep it approximately `38 px` high.

If a validated Pi positioning source exists, use bundled offline map assets and
show every saved observation. Markers use the species priority color and a
redundant icon. Nearby points may be clustered or shown as small highlighted
regions. Selecting a marker filters/highlights its species row.

The current hardware has no validated positioning source. In that state, the
top panel remains a useful local coverage summary with category totals and the
message `Location hardware unavailable — discoveries are still saved.` Do not
generate coordinates from network information. The list must remain fully
functional.

### Species list rows

Each row is approximately `58 px` high and contains:

- 44 px square newest crop thumbnail on the left;
- common name and smaller scientific name;
- observation/image count;
- category color bar and redundant category symbol;
- three-vertical-dot button on the right with a 44 px target.

Priority styling:

1. Threatened/endangered: Threat Rust plus warning symbol.
2. Region-specific/native: Botanical Green plus leaf symbol.
3. Generic: Strong Neutral plus circle symbol.

If a plant is both threatened and native, threat color wins and the native leaf
symbol remains visible.

The details action opens a right-side drawer or contained dialog that stays
within the 800×480 shell. It shows all saved crops, observation timestamps,
confidence at capture time, sourced botanical details, category/conservation
information, notes, export, and confirmed delete. Its content may scroll
internally; the page underneath must not scroll.

## 9. Ask Botanika

Use a full kiosk screen with:

- conversation region approximately `520 px` wide;
- evidence/voice panel approximately `232 px` wide;
- 12 px gap;
- bottom text composer always visible;
- microphone, send, stop-speaking, and clear-conversation controls;
- live transcript shown before submission;
- visible citations attached to each factual answer.

The guide retrieves evidence before generation. It may use the current scanned
or selected library species as context. If local evidence is insufficient, it
must say: `I could not find enough reliable offline information to answer that.`
Do not silently improvise or start an online search.

Voice behavior:

- text input must always work;
- push-to-talk is the dependable initial interaction;
- show Listening, Transcribing, Thinking, Speaking, and Stopped states;
- use bounded speech turns and silence endpointing;
- allow speech output to be interrupted immediately;
- keep STT/TTS models loaded when memory measurements allow;
- do not download models at runtime;
- support local voice navigation commands such as Open Scan, Open Library, Ask
  Botanika, Open Weed Detection, Go Home, Save Plant, Retake, and Stop Speaking;
- never open the microphone invisibly.

## 10. Weed Detection · Beta

Use the Scan screen’s camera and overlay structure, but load an independent weed
detector and show all supported weed boxes simultaneously.

- Clearly state the supported crop, region, and weed classes.
- Show class and confidence on every accepted box.
- Provide one `Analyze frame` action plus an optional stable auto-capture path.
- Do not send weed results to the plant discovery library.
- Do not persist the camera image or crops after inference.
- If a validated positioning source is available, store a coordinate-only weed
  observation with latitude, longitude, accuracy, source, timestamp, detector
  release, class, and confidence.
- If no position is available, continue detection and show the toast:
  `Exact location could not be found. Coordinate collection was skipped.`
- Never crash because position is unavailable.
- Never control or instruct a drone or chemical applicator.
- Explain that “weed” is context-dependent and the beta recognizes only its
  declared supported classes.

---

# Part III — Technical architecture

## 11. Local process topology

Use these runtime boundaries:

```text
Chromium kiosk at 127.0.0.1
        │
        ▼
FastAPI modular monolith
  ├── static React application and local API
  ├── camera owner and preview publisher
  ├── detector / quality / classifier coordinator
  ├── discovery and knowledge repositories
  ├── offline retrieval and local LLM adapter
  ├── STT/TTS audio coordinator
  └── weed detector
        │
        ├── Pi Camera / microphone / speaker
        ├── SQLite
        ├── managed crop storage
        ├── local model registry
        └── local knowledge/vector assets
```

Run llama.cpp as a separate local process only if its runtime integration is
more reliable that way. It still binds to loopback and remains supervised as
part of the same appliance.

## 12. Backend module ownership

Organize `backend/src/botanika/` around these boundaries:

| Module | Responsibility |
|---|---|
| `api` | Local routes, schemas, validation, errors, request IDs |
| `core` | Settings, lifecycle, capabilities, resource budgets |
| `hardware` | Camera, audio devices, display and optional positioning adapters |
| `vision/detection` | Live plant/organ detector and tracking |
| `vision/quality` | Stability, blur, exposure, crop geometry |
| `vision/classification` | Species preprocessing, inference, calibration, rejection |
| `vision/weeds` | Independent beta detector and ephemeral results |
| `discoveries` | Save, group, list, export, and delete workflows |
| `knowledge` | Ingestion, search, embeddings, citations, grounded answers |
| `voice` | STT, TTS, silence detection, audio ownership, cancellation |
| `storage` | SQLite migrations, transactions, filesystem media, backup |
| `observability` | Health, metrics, bounded redacted logs |

API handlers validate and delegate. They do not contain SQL, model
preprocessing, or direct hardware access.

## 13. Frontend module ownership

Organize the React application around:

- app shell, routes, capability state, and error boundary;
- reusable masthead, action bar, panel, badge, toast, dialog, empty state, and
  focusable icon button;
- Home feature;
- Scan feature and overlay canvas;
- Library feature and species details drawer;
- Ask Botanika conversation/voice feature;
- Weed feature;
- camera preview adapter;
- inference event adapter;
- local preferences only; and
- exact InnoHack-derived theme tokens and 800×480 layout rules.

The frontend is not the botanical source of truth and does not perform
authoritative persistence.

## 14. Local API contracts

Use versioned same-origin endpoints with typed request/response schemas. The
exact path names may be refined, but cover:

- liveness, readiness, and capability reporting;
- camera start, stop, preview, status, and still capture;
- live detector boxes and quality state;
- accepted-crop classification and cancellation;
- species facts and search;
- library species list, observations, save, export, and confirmed delete;
- grounded text chat with citations;
- STT session start/stop/status and TTS speak/cancel/status;
- weed analysis and optional coordinate-only record; and
- application diagnostics suitable for the local UI.

Use a backend-owned preview stream plus a lightweight event channel for box and
quality metadata. Keep all transport on loopback. Every event includes source
dimensions, preview dimensions, frame timestamp/sequence, and box coordinates
so the canvas transformation is testable.

## 15. Vision state machine

Implement an explicit per-scan state machine:

```text
IDLE
  → STARTING_CAMERA
  → DETECTING
  → TRACKING_TARGET
  → QUALITY_LOCKING
  → CAPTURING
  → CLASSIFYING
  → RESULT_ACCEPTED | RESULT_UNCERTAIN | RECOVERABLE_ERROR
  → SAVED | RETAKE | DETECTING
```

Cancellation must release transient images and return safely to detection.
Starting a new scan invalidates late events from the previous scan.

### Two-stage inference contract

The detector answers where the useful plant region is. The classifier answers
which supported species the accepted crop resembles.

The detector initially supports broad targets such as plant, leaf, flower,
fruit, and bark. Generic pretrained YOLO weights are not sufficient evidence for
regional species identification. Benchmark compact YOLO-family, TFLite, ONNX,
or NCNN candidates on the real Pi and record license, latency, memory, sustained
FPS, temperature, and target recall.

Start the classifier with a bounded regional catalog and a compact backbone
such as MobileNetV3 or EfficientNet-Lite. Add specialist flower/tree/leaf
classifiers only when the confusion matrix demonstrates a real improvement and
routing to that specialist is reliable.

Every activated model needs:

- immutable model ID and version;
- checksum and label map;
- dataset/source/license provenance;
- supported geography, taxa, and image views;
- preprocessing and output contract;
- held-out macro and class-wise metrics;
- confidence calibration and unknown-rejection threshold;
- Pi p50/p95 latency, peak memory, temperature, and throttling result; and
- known failure cases.

Never present a placeholder/random classifier as a working plant identifier.
If a production species model is unavailable, keep the real camera/detection
flow usable and mark classification honestly unavailable until the artifact and
catalog pass their gate.

## 16. Storage model

Use migrations from the beginning. At minimum model these concepts:

- `species`;
- scientific/common-name aliases;
- categories and region/native assignments;
- conservation assessments;
- ecology notes;
- sources and licenses;
- knowledge chunks and embedding references;
- model releases;
- one `library_species` row per stable species ID;
- discovery observations;
- discovery crop images;
- optional observation notes;
- optional positioning samples with accuracy and source; and
- coordinate-only weed observations, separate from the discovery library.

One service owns the SQLite-plus-filesystem save transaction. Write the crop to
a temporary managed path, verify it, commit the record, and finalize the file in
a recoverable order. Prevent orphan files and broken rows. Back up the database
and referenced crops together, then test restoration.

## 17. Offline knowledge and botanical guide

Build a provenance-first corpus using reviewed sources appropriate to the chosen
region. Candidate source classes include regional floras/herbaria, IUCN
assessments, GBIF occurrence data, and licensed Wikipedia/Wikidata extracts.
Review licenses. Do not infer native status from occurrence points alone.

Use:

- normalized facts in SQLite;
- FTS5 for exact names and keywords;
- a compact embedding index for semantic retrieval;
- chunks linked to species and sources; and
- a small quantized local model through llama.cpp for evidence-grounded wording.

Test retrieval separately from generation. An answer passes only when every
important botanical claim can be traced to retrieved local evidence.

## 18. Resource coordination

- The camera loop drops stale detector work.
- Classification receives priority over chat generation.
- Weed inference and species classification do not run concurrently initially.
- Chat generation may be cancelled or paused when scanning begins.
- Background indexing runs only while interactive features are idle.
- STT and TTS share one explicit audio coordinator.
- TTS stops before microphone capture begins.
- All queues are bounded.
- Capability status reflects actual loaded models/devices, not configuration
  intent.

## 19. Failure behavior

| Failure | Required behavior |
|---|---|
| Camera missing or busy | Explain the problem and offer local image selection |
| Detector unavailable | Keep manual image capture/selection; disable automatic boxes |
| Blurry or unstable target | Keep preview live and show one actionable hint |
| Classifier unavailable | Keep Scan visible and mark identification unavailable |
| Low confidence | Ask for another view and abstain |
| Database unavailable | Block save but retain the unsaved crop in memory temporarily |
| Disk full/read-only | Stop persistence safely and show a recovery instruction |
| Knowledge unavailable | Keep species scan usable; disable Ask Botanika clearly |
| Microphone unavailable | Keep typed chat fully usable |
| TTS unavailable | Keep transcript/answer visible and disable speech |
| Position unavailable | Save plant without coordinates; skip weed coordinate record |
| Weed model unavailable | Disable the beta card with supported-scope explanation |
| Backend restart | Kiosk reconnects and returns to a safe screen |

---

# Part IV — Phase-by-phase implementation plan

## Phase 0 — Hardware and repository baseline

### Work

1. Read the existing Botanika documentation and inspect repository status.
2. Run the hardware-readiness checks in `docs/STAGE0_TEST_RUNBOOK.md`.
3. Record OS, kernel, architecture, camera stack, screen resolution, audio
   devices, SSD filesystem/free space, Python/Node versions, temperature,
   throttling, and available memory.
4. Prove the screen reports 800×480 and document any desktop scaling.
5. Prove one Pi Camera preview and still capture.
6. Prove microphone capture and speaker playback without leaving recordings.
7. Inspect InnoHack only as a read-only reference.

### Tests and evidence

- hardware readiness report;
- exact commands and summarized outputs;
- camera and audio release/reacquire checks; and
- list of blockers or measured constraints.

### Exit gate

Camera, screen, audio, SSD, and thermal facts are measured. Any unavailable
device has an explicit development fallback. Continue automatically if there is
no blocking hardware failure.

## Phase 1 — Local application foundation

### Work

1. Pin supported Python, Node.js, and package-manager versions based on the Pi.
2. Create the FastAPI package, settings, lifecycle, error schema, request IDs,
   liveness, readiness, and capability endpoints.
3. Create the React/Vite application shell.
4. Serve the built interface and API from one loopback origin.
5. Add SQLite migrations and managed runtime directories.
6. Add structured, rotating, privacy-safe logs.
7. Add development commands and environment examples without secrets.

### Tests

- backend unit/contract tests;
- migration upgrade/downgrade or forward-recovery test;
- same-origin shell smoke test;
- truthful readiness with missing models/devices; and
- clean start/stop with no orphan process.

### Exit gate

The Pi browser opens a local shell, backend health is truthful, and failures are
diagnosable.

## Phase 2 — InnoHack-derived 800×480 Botanika shell

### Work

1. Implement the exact visual tokens and shell dimensions in Part I.
2. Build the fixed masthead and centered Botanika leaf wordmark.
3. Build the three-card homepage and lower-corner foliage.
4. Build shared buttons, badges, panels, action bars, dialogs, toasts, loading,
   unavailable states, keyboard focus, and capability popover.
5. Add empty route shells for Scan, Library, Ask Botanika, and Weed Detection.
6. Add keyboard/touch navigation and reduced-motion behavior.

### Tests

- screenshots at exactly 800×480 for every shell route;
- no page-level scrollbar or clipped touch target;
- keyboard focus order and Escape/Back behavior;
- contrast and non-color semantic indicators; and
- screenshot comparison against approved Botanika baselines.

### Exit gate

The kiosk visually matches InnoHack’s design language and all Botanika routes
fit 800×480 before camera/model complexity is added.

## Phase 3 — Pi Camera and preview ownership

### Work

1. Implement one Picamera2/libcamera-backed camera adapter.
2. Add lifecycle, supported resolution, autofocus/exposure status, reconnect,
   and release behavior.
3. Publish the local preview plus timestamped source-dimension metadata.
4. Render it in the 500 px Scan workspace with correct contain/letterbox math.
5. Add backend and frontend capture cancellation.
6. Add local file selection as a degraded fallback.

### Tests

- real camera preview soak;
- busy/missing/reconnect cases;
- source-to-preview coordinate fixtures;
- camera released after route exit/backend stop; and
- 800×480 screenshot with 4:3 and alternate source ratios.

### Exit gate

The Scan screen shows a stable local preview for at least 15 minutes, exits
cleanly, and never has two competing camera owners.

## Phase 4 — Plant detector, tracking, quality lock, and crop

### Work

1. Define the detector model registry and labels.
2. Benchmark compact detector/runtime candidates on the real Pi.
3. Implement a bounded live detector loop that drops stale frames.
4. Draw all boxes and support target selection.
5. Implement tracking, stability, edge, size, exposure, and focus checks.
6. Create a calibration tool/runbook using real plant fixtures and lighting.
7. Implement automatic and manual capture.
8. Implement padded crop geometry, clamping, orientation, metadata stripping,
   hashing, and immediate full-frame release.

### Tests

- detector contract and label-map tests;
- box tracking tests;
- blur/exposure fixture tests;
- coordinate conversion for letterbox/resize/orientation;
- crop pixel-content test, not only overlay alignment;
- proof that no full frame persists; and
- Pi FPS, p50/p95 latency, temperature, and throttling measurements.

### Exit gate

Real plants produce usable boxes and one correct crop only after measured
quality/stability checks, with a working manual fallback.

## Phase 5 — Regional species classifier and species knowledge

### Work

1. Freeze the initial geographic region and supported species catalog.
2. Collect licensed datasets, deduplicate by observation, and split without
   observation/site leakage.
3. Prepare the normalized species/alias/category/conservation/source database.
4. Train off-device if needed, export candidate compact models, and benchmark
   them on the Pi.
5. Calibrate confidence and implement unknown rejection.
6. Join classifier labels to stable species IDs and sourced details.
7. Implement accepted/uncertain result UI around the selected box.
8. Record the full model contract and limitations.

### Tests

- immutable label-map/species join tests;
- held-out macro and per-class results;
- out-of-scope/unknown tests;
- calibration reliability test;
- crop preprocessing parity test;
- Pi latency/memory/thermal benchmark; and
- UI tests for accepted, uncertain, unavailable, and cancelled results.

### Exit gate

The model meets declared regional accuracy/calibration targets, abstains outside
confidence, and runs within the measured Pi performance budget. Do not call the
classifier complete without a real validated artifact.

## Phase 6 — Local species-grouped library

### Work

1. Implement the discovery schema and SQLite/filesystem transaction service.
2. Implement explicit save, deduplication, species grouping, observation
   history, thumbnail generation, notes, export, confirmed delete, quota,
   backup, and restore.
3. Build the exact stacked coverage/list layout.
4. Build category colors/symbols and filters.
5. Build the details drawer with all crops and saved-time facts.
6. Add optional positioning capability handling without fabricated data.

### Tests

- repeated species creates one group and several observations;
- only cropped pixels persist;
- duplicate-save behavior;
- failed file/database transaction recovery;
- export/delete confirmation;
- backup/restore with image linkage;
- unavailable-position UI; and
- list/detail screenshots at 800×480 with empty, normal, and long data.

### Exit gate

Saved discoveries survive restart, group correctly, restore correctly, and
never persist a full camera frame.

## Phase 7 — Offline botanical guide and voice

### Work

1. Build source/license manifests and reproducible knowledge ingestion.
2. Add FTS5, embeddings, retrieval, citations, and species-context boosting.
3. Benchmark a suitable quantized local LLM and llama.cpp settings.
4. Implement grounded typed chat and explicit insufficient-evidence behavior.
5. Reuse the reliable InnoHack audio patterns for microphone ownership,
   silence-ended STT, cached Piper TTS, and cancellation.
6. Benchmark Indian-English Vosk and suitable Whisper.cpp/faster-whisper
   variants; select based on measured latency/accuracy.
7. Implement push-to-talk, visible transcript, spoken answer, stop action, and
   local voice navigation commands.

### Tests

- retrieval gold questions;
- source/citation integrity;
- unsupported-question abstention;
- prompt-injection resistance for ingested text;
- microphone/speaker ownership and cancellation;
- STT latency/noise/accent samples with consent-safe fixtures;
- no model download during offline startup; and
- 800×480 long-conversation/citation screenshots.

### Exit gate

Botanical answers are usable offline, important claims are traceable, missing
facts abstain, and text remains usable when voice is unavailable.

## Phase 8 — Weed Detection beta

### Work

1. Define the agricultural context, region, and supported weed species.
2. Curate/train/validate an independent multi-box detector.
3. Reuse camera ownership and overlay primitives without mixing model labels.
4. Build multi-box result UI and confidence display.
5. Ensure temporary images/crops are deleted after inference.
6. Add optional coordinate-only storage through a validated Pi positioning
   adapter and the exact unavailable-coordinate toast.
7. Add clear safety, beta, and unsupported-scope copy.

### Tests

- supported and unsupported weed fixtures;
- multi-box overlay coordinates;
- no discovery-library entry or image persistence;
- absent/invalid positioning behavior;
- coordinate accuracy/source validation when hardware exists; and
- Pi performance/thermal measurements.

### Exit gate

The beta identifies only declared weeds, handles several boxes, leaves no image
behind, and never fails because coordinates are unavailable.

## Phase 9 — Kiosk deployment and recovery

### Work

1. Create production builds and explicit runtime/data directories.
2. Add hardened systemd units for backend and optional local LLM.
3. Add readiness-aware Chromium kiosk launch at 800×480.
4. Add boot recovery, service restart, bounded logs, and on-screen diagnostics.
5. Keep a documented keyboard/terminal recovery path.
6. Add backup scheduling only after manual backup/restore has passed.

### Tests

- cold boot to usable homepage timing;
- service crash/restart;
- camera/audio reacquisition after restart;
- power-loss-safe SQLite behavior where practical;
- kiosk relaunch and no desktop chrome;
- offline boot; and
- recovery instructions executed on the real Pi.

### Exit gate

The Pi boots directly into Botanika, recovers from local process failures, and
remains usable without internet access.

## Phase 10 — Hardening, feedback, and release evidence

### Work

1. Run multi-hour scan/idle/chat soak tests.
2. Test disk-full, database read-only, missing model, corrupt model, camera busy,
   audio missing, and knowledge-index failure.
3. Profile memory, CPU, latency, heat, and throttling for every main journey.
4. Conduct at least five structured usability sessions on the 800×480 screen.
5. Record findings and the changes made because of them.
6. Complete model, dataset, source, license, limitation, and privacy registers.
7. Produce an operator runbook and final end-to-end demonstration checklist.

### End-to-end acceptance journeys

1. Boot → Home → Scan → stable box → crop → accepted identification.
2. Accepted result → Save → Library → same species grouped with later capture.
3. Uncertain result → another-angle guidance → no false confirmed save.
4. Library → category filter → details → all crops and sources.
5. Typed question → retrieved evidence → cited offline answer.
6. Spoken question → visible transcript → cited response → interruptible speech.
7. Weed Beta → several boxes → no image/library persistence.
8. Missing coordinate source → exact toast → uninterrupted weed result.
9. Missing camera/model/audio/storage capability → clear degraded behavior.
10. Reboot → kiosk returns → saved library remains consistent.

### Final exit gate

All journeys pass on the actual Pi at 800×480, the application survives the
defined failure cases, model/data claims have provenance, and the operator can
install, start, stop, back up, restore, and diagnose Botanika from the written
runbook.

---

# Required reporting after every phase

At the end of each phase, report:

1. outcome delivered;
2. files changed;
3. commands/tests run and their results;
4. real Pi measurements;
5. known limitations or unavailable artifacts;
6. screenshots/evidence produced;
7. exit-gate verdict; and
8. the next phase about to begin.

Commit coherent verified work with descriptive messages. Do not claim a phase
complete because the UI renders if its hardware, data, model, persistence, or
recovery gate has not passed.

# Start now

Begin at Phase 0. If its exit gate passes, continue through the phases in order
without returning to architecture-only work. Use the existing repository
structure unless a measured implementation need justifies a documented change.
The desired endpoint is the complete standalone Pi kiosk described here—not a
mockup or collection of placeholder screens.
