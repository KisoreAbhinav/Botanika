# Botanika — Phase-by-Phase Build Prompt

Copy everything below this line into a new implementation session. This is the
authoritative build prompt for Botanika. The Pi implementation is completed and
proven first; local networking is introduced only in its assigned later phase.

This file supersedes the older phase order in `docs/PI_ARCHITECTURE_AND_ROADMAP.md`
and other earlier planning notes. Those documents remain useful for Pi module,
vision, storage, and UI detail, but this file controls implementation order and
the Phase 7–8 networking/pairing scope.

---

## Role and execution mandate

You are the implementation agent for **Botanika**, a native-plant
field-intelligence system whose Raspberry Pi 5 is the permanent backend,
hardware owner, inference device, datastore, and standalone kiosk.

Inspect the repository and the real hardware before changing anything, then
implement the application exactly one phase at a time. Do not stop at planning
inside the assigned phase: implement it, test it on the real Pi, report the goal
check, and then stop for handoff. Never begin a later phase because it looks
more useful or exciting. The user will explicitly hand off the next phase.

Preserve unrelated files and existing user work. Keep every claim honest: an
unavailable model or sensor must produce an explicit unavailable state, never
fabricated output. A temporary dummy classifier is allowed only in Phase 4 and
must be visibly marked as test data.

## Fixed product boundary

Botanika runs on one Raspberry Pi and uses:

- Raspberry Pi 5 with 16 GB RAM;
- 512 GB SSD;
- Pi Camera;
- Pi-connected 800×480 screen;
- Pi-connected microphone and speaker; and
- touch, keyboard, or mouse input available on the Pi.

The Pi always owns the camera, model inference, botanical knowledge, discovery
library, voice pipeline, data storage, and process supervision. The runtime must
remain useful without internet access.

Phases 0–6 are strictly standalone: serve the interface on loopback and display
it in Chromium on the Pi screen. Do not create network modes early. Phase 7 may
turn the Pi into a local Wi-Fi access point and expose the existing application
over that private link. Phase 8 may add the responsive client, pairing, and
SOLO/NETWORKED handoff. These later phases must reuse the already-tested Pi
pipeline rather than creating a second backend.

Do not add cloud inference, accounts, fabricated coordinates, agricultural
actuation, internet exposure, or mandatory online services. Optional online
botanical search is a post-release enhancement and is not part of the initial
definition of done.

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
- Every Pi screen must fit the 800×480 target without page-level scrolling.
  Scroll only inside designated lists, conversations, or detail panels.
- Do not add responsive small-screen behavior before Phase 8.

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

If a validated position source exists, use bundled offline map assets and show
every saved observation. Before Phase 8 this can only be Pi-connected
positioning hardware. From Phase 8 onward, an explicitly paired active client
may supply a position with accuracy and source metadata. Markers use the species
priority color and a redundant icon. Nearby points may be clustered or shown as
small highlighted regions. Selecting a marker filters/highlights its species
row.

When no validated position is available, the top panel remains a useful local
coverage summary with category totals and the message `Location unavailable —
discoveries are still saved.` Do not generate coordinates from network
information. The list must remain fully functional.

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
  release, class, and confidence. A paired active client may become that source
  only after Phase 8.
- If no position is available, continue detection and show the toast:
  `Exact location could not be found. Coordinate collection was skipped.`
- Never crash because position is unavailable.
- Never control or instruct a drone or chemical applicator.
- Explain that “weed” is context-dependent and the beta recognizes only its
  declared supported classes.

---

# Part III — Technical architecture

## 11. Process topology by phase

Phases 0–6 use only the standalone path:

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

Phase 7 adds one private local transport boundary without moving any botanical
logic away from the Pi:

```text
Pi Wi-Fi access point
        │
        ▼
FastAPI application on the Pi
        │
        └── the same camera, inference, data, and library services
```

Phase 8 adds one paired browser as the active UI. SOLO keeps the Chromium kiosk
active. NETWORKED makes the paired browser active and turns the Pi screen into a
compact connection/status console. There is still one backend and one active
controller.

Run llama.cpp only in Phase 9 and only if time remains. It may be a separate
local process when that integration is more reliable, but remains supervised as
part of the same Pi appliance.

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

Do not implement alternate viewport layouts through Phase 6. In Phase 8, add a
compact portrait layout for the paired browser while keeping the Pi’s 800×480
layout unchanged.

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
quality metadata. Keep all transport on loopback through Phase 6. In Phase 7,
bind only to the controlled access-point interface and preserve the local kiosk
path. Every event includes source dimensions, preview dimensions, frame
timestamp/sequence, and box coordinates so the canvas transformation is
testable.

Do not design a second inference API for Phase 8. The paired browser calls the
same application services already proven by SOLO mode. Pairing adds exclusivity
and handoff, not a new user/account system.

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

## Phase 0 — Environment

### Work

1. Read the Botanika documentation and inspect repository/Git status.
2. Update Raspberry Pi OS using the normal supported package workflow and
   record the pre/post versions. Do not perform an unattended distribution
   upgrade.
3. Confirm the Pi Camera is enabled, detected, and accessible through the
   installed native Raspberry Pi camera tooling.
4. Open a native camera preview and capture one temporary still.
5. Confirm the display is exactly 800×480 and record desktop scaling.
6. Record architecture, Python version, free SSD space, RAM, CPU temperature,
   throttling state, and camera-stack version.
7. Create the project Python virtual environment and a pinned dependency input.
8. Install only the libraries required for the next phases: the supported Pi
   camera bindings, OpenCV, NumPy, and the selected Ultralytics/YOLO runtime.
   FastAPI, React, and UI dependencies are deliberately deferred.
9. Add a repeatable environment verification command and update the operator
   notes. Do not build application behavior yet.

### Tests and evidence

- hardware/environment readiness report;
- exact version and installation evidence;
- successful native preview and temporary still capture;
- camera release/reacquire check; and
- list of blockers or measured constraints.

### Exit gate

**You know it worked when:** the native Pi camera tool shows a live picture on
the 800×480 screen, the temporary still is valid, and the project virtual
environment imports its Phase 1/2 dependencies. Report the result and stop. Do
not start Phase 1 in the same handoff.

## Phase 1 — Raw feed in code

### Work

1. Create the smallest maintainable Python camera module and runnable script.
2. Open the Pi Camera through one explicit camera owner.
3. Convert frames into the color layout expected by OpenCV.
4. Display live frames in a normal window on the Pi’s own screen.
5. Add a visible frame counter/FPS diagnostic and a documented quit key.
6. Handle camera-open failure, dropped frames, and shutdown without leaving the
   camera busy.
7. Keep this phase independent of FastAPI, React, SQLite, classification, and
   application styling.

### Tests

- unit-test any frame conversion or configuration logic that does not require
  hardware;
- run the script on the actual Pi for at least five minutes;
- record resolution, measured FPS, memory, temperature, and dropped frames; and
- quit and reopen it to prove the camera was released.

### Exit gate

**You know it worked when:** live frames rendered by Botanika’s Python code—not
the OS preview tool—are visible on the Pi display and the script can close and
reopen cleanly. Report the result and stop.

## Phase 2 — Generic detection

### Work

1. Load one small pretrained YOLO detector through a dedicated adapter.
2. Record the model name, version, artifact source, checksum, labels, and
   license. Do not present it as a plant-species classifier.
3. Run the detector on resized camera frames and drop stale work rather than
   queueing frames.
4. Scale returned boxes back to the displayed camera frame correctly.
5. Draw class name, box, and generic detector confidence on the live OpenCV
   window for every supported detected object.
6. Keep model load outside the per-frame loop and release it cleanly at exit.
7. Record p50/p95 inference latency, visible FPS, memory, temperature, and
   throttling on the real Pi.

### Tests

- model adapter and coordinate-scaling tests;
- known-image inference smoke test;
- live camera test containing at least two ordinary detectable object types;
- missing/corrupt model behavior; and
- five-minute sustained performance measurement.

### Exit gate

**You know it worked when:** generic live boxes visibly track objects in the Pi
camera window and no unbounded inference backlog develops. A plant box is not a
required outcome unless the chosen generic label set actually contains one.
Report what the pretrained model can and cannot detect, then stop.

## Phase 3 — Lock-on logic and crop capture

### Work

1. Select one candidate box, preferring the largest central eligible detection.
2. Track it across frames using class, intersection-over-union, center movement,
   relative size change, appearance, and disappearance rules.
3. Implement explicit lock states: Searching, Tracking, Hold steady, Checking
   sharpness, Locked, Captured, and Cooldown.
4. Calculate blur/focus on the candidate crop, not the whole frame. Add simple
   exposure, minimum-size, and edge-clipping checks so a technically sharp but
   unusable crop is rejected.
5. Calibrate thresholds using actual Pi Camera samples rather than declaring
   arbitrary constants correct.
6. Require stable and usable conditions for several consecutive checks.
7. When the gate passes, pad/clamp the selected box and save only that crop to a
   temporary Phase 3 output directory. Do not save the full frame.
8. Add a cooldown/deduplication guard so one steady object does not create many
   files.
9. Keep a manual capture path for debugging.

### Tests

- deterministic tracking/stability tests with recorded box sequences;
- blur, exposure, size, and edge fixture tests;
- crop coordinate and exact-pixel tests;
- stable/sharp, moving, blurry, clipped, disappeared, and multi-box hardware
  trials;
- duplicate cooldown test; and
- filesystem proof that only crops are created.

### Exit gate

**You know it worked when:** point the camera at an eligible object, hold it
still, and exactly one sharp cropped image file appears. Moving or blurry targets
must not auto-save. Report the result and stop.

## Phase 4 — Classifier stub and complete pipeline shape

### Work

1. Define the real classifier input/output interface before selecting the final
   model.
2. Implement a deterministic dummy classifier behind that interface. It accepts
   a crop path or image object and returns hardcoded but schema-valid data:
   stable species ID, common name, scientific name, family, category,
   conservation status, confidence, short notes, sources, and classifier version.
3. Mark every dummy response with `is_stub: true` and the classifier version
   `stub-phase-4`; expose `DEMO DATA` visibly wherever it is displayed or logged.
4. Pass each accepted Phase 3 crop directly into the classifier interface.
5. Print or render a small local diagnostic result and preserve the crop path,
   timing, and result association.
6. Exercise accepted, low-confidence, classifier-error, cancellation, and
   malformed-image responses even though the values are deterministic.
7. Do not download, train, or pretend to validate a species model in this phase.

### Tests

- schema and deterministic-output tests;
- crop → classifier invocation test;
- stub accepted/uncertain/error path tests;
- full camera → detection → stable/quality gate → crop → stub result integration
  test; and
- visible proof that stub data cannot be mistaken for a real identification.

### Exit gate

**You know it worked when:** holding an eligible object steady creates one crop,
the crop automatically enters the stub classifier, and a complete clearly
labelled fake species result appears. This phase proves the end-to-end pipeline
shape before real species AI. Report the result and stop.

## Phase 5 — Pi’s standalone 800×480 UI (SOLO)

### Work

1. Add the FastAPI modular-monolith foundation, lifecycle, settings, liveness,
   readiness, capability reporting, error schemas, and bounded logs.
2. Add the React/Vite application and serve it with the API from one loopback
   origin.
3. Implement the exact InnoHack-derived 800×480 visual system in Parts I–II:
   fixed shell, 66 px masthead, centered Botanika wordmark, warm paper palette,
   three-card homepage, foliage, Scan, Library shell, Ask shell, and Weed Beta
   disabled shell.
4. Move the Phase 1–4 camera/detection/lock/crop/stub pipeline behind reusable
   backend services without changing its proven behavior.
5. Publish the backend-owned preview and timestamped box/quality events to the
   local Scan screen.
6. Implement the 500 px camera workspace, exact overlay transformation, quality
   prompts, processing state, stub name above the accepted box, stub confidence
   below it, and details panel.
7. Add Save to Library, Retake, Another angle, manual capture, cancellation, and
   local image fallback. Until Phase 6, a saved stub record must remain clearly
   marked demo-only and kept separate from real discoveries.
8. Add keyboard/touch input, reduced motion, internal-only scrolling, and clear
   unavailable states.
9. Keep the service on loopback. Do not add hotspot, pairing, alternate device
   layouts, physical mode controls, or network exposure.

### Tests

- API and pipeline contract tests;
- camera ownership/reconnect tests after the service refactor;
- overlay/crop coordinate tests across source aspect ratios;
- UI tests for detecting, locking, processing, result, uncertain, error, and
  cancellation states;
- exactly 800×480 screenshots for Home and Scan;
- no page-level scrollbar, clipping, or undersized primary control; and
- real Pi end-to-end browser run using the stub classifier.

### Exit gate

**You know it worked when:** open Chromium on the Pi, enter Scan from the real
Botanika homepage, see live boxes and lock feedback, hold an object steady, and
see the Phase 4 demo result populate the designed details panel. Everything must
work standalone at 800×480. Report the result and stop.

## Phase 6 — Real species data, classifier, and library

### Work

1. Freeze the first region and a minimum catalog of seven supported plant
   species, including at least two region-specific/native species and any
   carefully supported threatened/endangered examples.
2. Curate licensed images and botanical facts. Record dataset/source/license
   provenance, deduplicate by observation, and split without observation or
   location leakage.
3. Build the normalized SQLite species knowledge tables: stable IDs, names,
   aliases, family, category, conservation assessment, ecology, sources, and
   model-release metadata.
4. Select or train a real compact classifier, export it to a Pi-efficient
   runtime, benchmark it on the actual Pi, calibrate confidence, and implement
   explicit unknown rejection. Training may happen off-Pi; all runtime inference
   remains on the Pi.
5. Replace the Phase 4 implementation behind the unchanged classifier interface.
   Delete or disable every stub path in normal runtime.
6. Join labels to stable species IDs and render real accepted/uncertain results.
7. Implement the authoritative species-grouped discovery library with explicit
   crop-only save, deduplication, multiple observations/images per species,
   thumbnails, details, notes, category filters, export, confirmed delete,
   quota, backup, and restore.
8. Implement the exact stacked coverage/list layout. Without a trustworthy
   position source, show the designed local coverage summary and save without
   coordinates.

### Tests

- immutable label-map/species join and migration tests;
- held-out macro/per-class metrics and out-of-catalog trials;
- confidence calibration and unknown rejection tests;
- preprocessing parity and Pi latency/memory/thermal benchmarks;
- proof that no normal runtime result carries `is_stub: true`;
- repeated species creates one group with multiple observations;
- only cropped pixels persist;
- duplicate and failed file/database transaction recovery;
- export/delete/backup/restore with image linkage;
- unavailable-position behavior; and
- 800×480 Scan, Library, and details screenshots with real data.

### Exit gate

**You know it worked when:** SOLO mode identifies the supported real plants with
the declared measured reliability, rejects unsupported/uncertain inputs, saves
only accepted crops, groups repeat findings under one species, and restores the
library after restart. Report the catalog, metrics, limitations, and goal check,
then stop.

## Phase 7 — Private Pi Wi-Fi networking

### Work

1. Preserve the working SOLO mode unchanged and create a recovery plan before
   altering network configuration.
2. Configure the Pi as a private WPA2/WPA3 Wi-Fi access point using the network
   stack supported by the installed Pi OS. Use hostapd/dnsmasq only when they are
   the appropriate supported choice for that OS image.
3. Give the Pi a stable private access-point address and local hostname.
4. Configure DHCP/DNS so a connected browser can reach the Botanika page without
   internet access. A simple local landing redirect may be added if reliable.
5. Install FastAPI/network dependencies if not already present and expose the
   same Phase 5/6 application on the access-point interface. Do not duplicate
   camera, classifier, library, or knowledge logic.
6. Keep loopback access working for the Pi kiosk.
7. Add firewall/interface restrictions so Botanika is reachable from the private
   access point but is not exposed on unrelated interfaces or the internet.
8. Add honest network capability/health reporting and an operator command to
   enable, disable, and recover the access point.
9. Show a minimal device-independent landing page. Do not build the final
   responsive scan UI, pairing, modes, or controller handoff yet.

### Tests

- SOLO regression test for camera, classifier, and library;
- access-point start/stop/reboot/recovery test;
- DHCP, DNS/local hostname, and page-load tests;
- firewall/listener inspection on every interface;
- phone connected to only the Pi access point with mobile data disabled;
- backend restart and browser reconnection test; and
- proof that the same FastAPI services handle Pi and access-point requests.

### Exit gate

**You know it worked when:** a phone joins the Pi’s private Wi-Fi and loads a
Botanika page served by FastAPI while the Pi’s standalone application still
works. No pairing, remote camera, or mode switching is required yet. Report the
network configuration and goal check, then stop.

## Phase 8 — Responsive client, pairing, and SOLO/NETWORKED handoff

### Work

1. Add an explicit mode state machine: SOLO, NETWORKED_UNPAIRED, and
   NETWORKED_PAIRED.
2. Keep the Pi as the only backend and authoritative datastore.
3. Add the physical mode-toggle button and status LEDs through one debounced GPIO
   adapter. Define pins in configuration, safe boot defaults, cleanup, and a
   keyboard/software fallback for development.
4. In SOLO, the Pi screen retains the full 800×480 application and Pi Camera.
5. In NETWORKED_UNPAIRED, the Pi screen shows access-point name, connection
   guidance, QR/short pairing code, expiration, and return-to-SOLO action.
6. Use a standard Wi-Fi QR for joining the private access point when useful, then
   a short-lived single-use application token for controller pairing. This is a
   handoff mechanism, not an account system.
7. In NETWORKED_PAIRED, the Pi screen becomes an 800×480 status console showing
   paired device, current scan state, recent result log, connection health, and
   disconnect/return-to-SOLO controls.
8. Enforce exactly one active paired controller. Revoke the prior lease on mode
   change, explicit disconnect, expiry, or operator takeover.
9. Add a responsive portrait layout for the same React feature set. Preserve the
   exact Pi layout separately; do not shrink the 800×480 shell into the mobile
   viewport.
10. On the paired browser, open its camera locally. Run the generic detector,
    stability checks, blur/exposure checks, and crop construction on that active
    device when performance permits. Send only the accepted padded crop to the
    Pi classifier; never stream live video to the Pi.
11. If browser-side detection is unsupported, retain a clearly marked manual
    crop/capture fallback rather than sending continuous video.
12. Return classifier name, confidence, details, and category from the Pi and
    draw the accepted result around the corresponding local box.
13. With permission, obtain latitude, longitude, accuracy, timestamp, and source
    from the paired browser only when saving a discovery. A denied or unavailable
    position never blocks identification or saving.
14. Save authoritative discoveries/crops to the Pi library. If a personal
    per-browser view is retained, treat it as a cache/preferences layer rather
    than the only copy.
15. Add reconnect, lease loss, mode change, stale response, interrupted crop
    upload, and Pi-unavailable states. Keep the crop available for explicit retry
    or cancel until the request resolves.

### Tests

- GPIO debounce, boot state, LED mapping, and cleanup tests;
- pairing token expiry, single use, revocation, and one-controller tests;
- SOLO → unpaired → paired → SOLO state-machine tests;
- 800×480 screenshots of all three Pi mode states;
- portrait browser screenshots and touch-target checks;
- browser camera permission denied/manual fallback;
- proof that no live video reaches the Pi;
- crop hash/dimensions equivalence before and after upload;
- classification/save/repeated-species flow from the paired browser;
- location allowed, denied, inaccurate, and unavailable cases; and
- disconnect/reconnect, interrupted upload, backend restart, and mode-takeover
  trials.

### Exit gate

**You know it worked when:** press the mode button, join/pair from the Pi screen,
run a complete camera → stable box → crop-only upload → Pi classification → save
flow from the paired browser, see the Pi status console update, and return safely
to SOLO. Report the result and stop.

## Phase 9 — Extras and final hardening, only if time remains

### Work

Implement these in order. Each extra has its own gate; do not sacrifice the
working scan/classify/library/mode flow for them.

### 9A — Offline botanical chat and Pi voice

1. Build source/license manifests, SQLite FTS5, a compact embedding index,
   citations, and reproducible knowledge ingestion.
2. Benchmark a suitable quantized local LLM and llama.cpp settings.
3. Implement grounded typed chat with explicit insufficient-evidence behavior.
4. Reuse proven InnoHack patterns for bounded STT, silence endpointing, one audio
   owner, cached Piper TTS, and interruption.
5. Add visible transcript, answer, citations, and local voice navigation.

**Goal check:** a typed and spoken botanical question receives a sourced offline
answer; missing evidence causes an explicit abstention; voice failure leaves
typed chat usable.

### 9B — Gamification and aggregate discovery summaries

1. Add coverage percentage against the supported catalog, category progress,
   first/repeat discovery indicators, and non-manipulative milestones.
2. Keep the personal discovery library authoritative on the Pi. If paired-browser
   preferences are stored locally, document their non-authoritative role.
3. Build anonymous aggregate summaries from discovery observations without
   inventing community scale or exposing personal data.

**Goal check:** progress derives reproducibly from real saved discoveries and
remains correct after repeat findings, deletion, backup, and restore.

### 9C — Weed Detection beta

1. Define the crop context, region, and supported weed species.
2. Curate/train/validate an independent multi-box detector.
3. Support the Pi Camera in SOLO and one captured frame from the paired browser
   in NETWORKED. Do not stream live browser video.
4. Draw all supported weed boxes and confidence values.
5. Do not add weed results or images to the plant library; delete temporary
   images after inference.
6. When accurate position is available, store only the coordinate observation
   and model metadata. Otherwise show: `Exact location could not be found.
   Coordinate collection was skipped.`
7. Never connect this beta to a drone or chemical applicator.

**Goal check:** multiple supported weeds are boxed, no image/library entry
persists, and missing coordinates produce the toast without breaking detection.

### 9D — Kiosk deployment and final hardening

1. Create production builds and explicit runtime/data directories.
2. Add systemd services, readiness-aware 800×480 Chromium launch, safe GPIO
   startup, access-point supervision, bounded logs, and a recovery path.
3. Test cold boot, offline boot, service crash/restart, camera/audio reacquisition,
   pairing recovery, disk full/read-only, corrupt models, database backup/restore,
   and power-loss-safe behavior where practical.
4. Run multi-hour scan/idle/chat soak tests and record CPU, RAM, latency,
   temperature, and throttling.
5. Conduct five structured usability sessions and record resulting changes.
6. Complete model, dataset, source, license, limitation, privacy, operator, and
   demonstration documentation.

### Tests

- each selected extra’s goal check;
- complete SOLO regression journey;
- complete paired-controller regression journey;
- boot/recovery/soak evidence; and
- end-to-end demonstration checklist.

### Exit gate

**You know the final build worked when:** the Pi boots into Botanika, SOLO still
performs scan → lock → crop → real identification → grouped save, NETWORKED still
performs the paired crop-only flow, and every selected extra passes its own goal
without weakening the core application.

## Final acceptance journeys

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

At the end of the assigned phase, report:

1. outcome delivered;
2. files changed;
3. commands/tests run and their results;
4. real Pi measurements;
5. known limitations or unavailable artifacts;
6. screenshots/evidence produced;
7. exit-gate verdict; and
8. the next phase that is now eligible, without starting it.

Commit coherent verified work with descriptive messages. Do not claim a phase
complete because the UI renders if its hardware, data, model, persistence, or
recovery gate has not passed.

# Start now

Begin with Phase 0 only. Implement it, perform its goal check, report the result,
and stop. On a later handoff, inspect the evidence and begin only the next
incomplete phase. Use the existing repository structure unless a measured
implementation need justifies a documented change. Phases 7 and 8 may not begin
until the complete real-species SOLO pipeline in Phase 6 passes. Phase 9 is
optional and may not begin until the core flow selected by the user is stable.
