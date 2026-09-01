Task 1
initialize a git repo here first
my id is KisoreAbhinav
my email is kisoreabhinav@gmail.com
the link to my github repo is [https://github.com/KisoreAbhinav/Botanika](https://github.com/KisoreAbhinav/Botanika)

Task 2
create a folder structure and an architecture for just the Pi for now
the task to implement is given in the pasted prompt

No need for writing the code
Just design the entire architecture and then have a markdown file that consists of detailed and well explained steps that clearly explain what to do and when to do



heres exactly what i want
- a backend that classifies plants
- the UI it has an e-ink plant themed homepage, like with leaves and bushes on the bottom left and right part, 3 buttons i between which i will explain later what they do and at the top Botanika in the center in some plant theme, basically an icon
- for the 1st button its scan for plants, it opens camera and tries to locate plants in the current frame, once the boxes form it fetches the details of sharpness blur that is set and then shows processing, once there is some identification of the name of the plant, it shows the name and a confidence score, name on top of the box and confidence score under the box. have an option to save that to the app's library that saves with longitude and latitude using the phones location or gps whatever and it adds that to a list of discovered plants
- next button is library - it just shows the plants discovered by the user in a list view, on the top section theres like a google map that has areas highlighted where the user has saved/discovered a plant, it has regions highlighted on the map in green color, so its divided into 2 sections the top section consists of the map and the bottom section consists of the list of the plants the list has the name of the plants and is color coded based on different characteristics, like endangered, or generic and stuff like that, and each of those plants that are colored based on their characteristics, it shows as the same color on the map too, the bottom section that has the list of the discovered plants has the plants name and its icon on the left, like the icon can be a small image that the user captured, and on the right of that list is 3 vertical dots that when clicked opens the details of the plants, everything that there is to know about the plant, the images here are saved from the square of the YOLO box or whatever u use, like the box that detects and says that in this frame, this is the identified object, and just that frame NOT the entire camera frame, it is saved in the list by the plant name that was identfied by the backend in the pi, so if user finds multiples of the same plant, it just adds more images to the same menu instead of creating a new plant entry but if the user found it at 2 places, the map shows both the places
- 3rd button is just a beta featuree - it will detect all the weed from a given image, so the same way for the above thing, but specifically for weed plants that are of no use, it doesnt save anything, just highlights with the YOLO box and it saves the exact longitude and latitude of the weed so that can further be extended to providing details to a drone that can go to that exact spot and drop weedicides and stuff, for example if the exact coordinate couldnt be found, so lets say we are doing it on the pi, instead of crashing, it will have a small toast on the screen that says "exact location couldnt be found, skipping coordinate collection" or something like that

On the pi it can have questions and responses based on the plants, voice based input and screen and speaker based output in like a chat interface, we can ask queries regarding any plants and it has that offline dataset to answer, and if it doesnt have that answer to the specific question it can say "Could not find the details to that question, searching online for better response or something like that",

check for models like plant recognition or trees or flowers if YOLO supports it and we can have separate models for the identification of them


before we work on the backend
what i need is a way to connect my pi as the backend to the phone wirelessly and consistently
so the pi should just need an internet connection, and the phone should have the connection, and they can commute, they dont have to be on the same wifi, so keep that in mind

there will be a toggle option
not hardware buttons as of now, but just voice based config, u can check my other projects like HYDRA or InnoHack to copy the speech to text and text to speech methods

and using that we can choose whether the pi will be independent or will it be receiving input from my phone

it will be a web interface thats for sure
that i can access from my phone and from the pi itself too

everything i discussed and that is in the md
must be followed to the dot
only exceptions - whatever i said in the normal text overrides the content in the pasted text, only if there is a mismatch or conflict







PASTED TEXT
# Field Intelligence App for Native Plants — Project Skeleton

## 1. Hardware
- Raspberry Pi 5 (16GB RAM), 512GB SSD
- Pi Camera, mic, speaker, screen
- Electronics kit: button (mode toggle), LEDs (status indicators)
- Phone: acts as a display/AR client via browser (web app, no install)

---

## 2. Core Principle
- **Pi = single backend.** All species knowledge, classification, wiki/LLM, and query handling live on the Pi.
- **Detection is on-device** (phone or Pi's own camera) — cheap, per-frame, no network round trip needed.
- **Classification is backend-only** — heavier, triggered once per capture, not per-frame.
- **Only one display is "active" at a time**: Pi's own screen (SOLO) or a paired phone (NETWORKED) — toggled by a physical button.
- Fully offline-capable in SOLO mode; NETWORKED mode is still offline from the *internet*, just multi-device over local WiFi.

---

## 3. System Modes

| Mode | Pi Screen | Phone |
|---|---|---|
| **SOLO** | Full scan UI, Pi's own camera + local YOLO, server closed to connections | Placeholder: "Pi in solo mode" |
| **NETWORKED (unpaired)** | Shows QR code / short pairing code | Prompt to scan/enter code |
| **NETWORKED (paired)** | Status console: connected device, live scan log | Full scan UI, driving the session |

- Physical button = master toggle between SOLO ↔ NETWORKED.
- LEDs reflect state (e.g. green = SOLO, blue = NETWORKED).
- Pairing is a lightweight token tied to a WebSocket session — not real user auth, just an exclusivity/handoff mechanism.

---

## 4. Data Layers

### A. Species Knowledge Base (Pi, static, shared)
- Master DB: scientific name, common name, family, category, conservation status, ecology notes, known GPS locations
- Built once during setup, offline, SQLite

### B. Aggregate Discovery Log (Pi, anonymous, shared)
- `{species_id, timestamp, approx_location, device_hash}` — no user identity
- Powers a "community" view: total species found, endangered spottings, etc.

### C. Personal Discovery Log (Phone, local, per-device)
- Browser-local storage of this device's saved scans/images/details
- Powers gamification: coverage %, categories found, progress

### Categories
- **Generic** — broadly found, not region-restricted
- **Region-specific/native** — characteristic of local region (ties to NGCPR alignment criterion)
- **Endangered/threatened** — IUCN-flagged, visually distinct in UI

---

## 5. Detection & Classification Pipeline

```
Phone/Pi camera → local YOLO (on-device, every frame)
   → live bounding box overlay (instant, no network)
   → local stability check + Laplacian blur score
   → once stable + sharp: crop image locally
   → POST cropped image → Pi backend
Pi: run classifier → return {name, family, status, notes, category}
Client: render result in details panel, save to local library
Pi: log {species, timestamp, anon id} to aggregate discovery log
```

- No live video streamed to the Pi — only single cropped images per capture event.
- Pi's SOLO mode runs the identical local-YOLO + capture logic in Python/OpenCV.

---

## 6. Frontend — Web App (phone & Pi, same codebase)

**Theme:** e-ink style, green accents

### Home Screen
1. Scan for Plants
2. Library
3. Weed Detection (beta, agriculture — build last)

### Scan Screen
- **Top square:** live camera feed + YOLO box overlay, auto-capture on lock (stability + blur check)
- **Bottom section:** plant details panel (empty → populates on identification)

### Library Screen
- **Top:** scrollable preview grid of saved plant images
- **Bottom:** list view — name (right), hamburger menu → expands full saved details from scan time

---

## 7. Pi Screen — Wiki Chat Interface

- Chat UI, mic input (Whisper STT offline), TTS response (Piper)
- Default: answers grounded ONLY in offline wiki/RAG knowledge base
- Trigger phrase `"search..."` → routes query to live internet search instead
- Also mirrors the scan/library web app for SOLO mode standalone use

---

## 8. Backend Stack (Pi)

| Component | Purpose |
|---|---|
| FastAPI | REST endpoints: classify image, wiki query, mode/pairing state |
| WebSocket | Mode/pairing broadcasts only (not video) |
| Classifier (MobileNet/EfficientNet-Lite, TFLite/ONNX) | Species ID from cropped image |
| Local LLM (Llama 3.2 3B / Phi-3-mini via llama.cpp) | Botanical guide, RAG-grounded |
| Whisper.cpp + Piper | STT / TTS |
| SQLite | Species knowledge base + aggregate discovery log |
| GPIO handler (gpiozero) | Button → mode toggle, LED control |
| QR code generator | Pairing code display |

---

## 9. Build Stages

1. **Stage 1 — Core loop:** Pi server + SOLO mode camera/YOLO/classify working locally; button+LED toggle; pairing via QR; phone can connect and drive detection
2. **Stage 2:** Classification endpoint fully wired, library storage (local), details panel
3. **Stage 3:** Wiki chat (offline RAG) + voice on Pi screen
4. **Stage 4:** Gamification (personal + aggregate logs, categories, coverage tracking)
5. **Stage 5 (stretch):** Weed detection beta, online `"search..."` fallback, comparison features

---

## 10. Submission Requirement Mapping

| Requirement | Covered By |
|---|---|
| AI-Powered Plant Identification | On-device YOLO + Pi classifier |
| AR Species Visualization | Live box overlay + details panel |
| AI Botanical Guide | Pi wiki chat (LLM + RAG + voice) |
| Conservation Awareness | Category system + knowledge base content |
| User Experience & Feedback | Web app UX, 5-user feedback (to collect separately) |
| Alignment with NGCPR Vision | Region-specific category, min. 2 native species focus |
| Innovation | Mode toggle (SOLO/NETWORKED), offline-first design, gamification |