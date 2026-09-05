# Botanika Pi demo evidence

These captures use the real built Botanika React UI at the Pi kiosk contract of **800 × 480**. The browser API is deterministic replay data so the walkthrough is repeatable without pretending that a live camera or GPS receiver was active during capture.

## Walkthrough

- `video/botanika-pi-demo-slow.mp4` — 25.9-second slow Pi walkthrough
- `video/botanika-pi-demo-slow.webm` — browser-native recording
- `screenshots/01-pi-home.png` through `13-pi-capability-diagnostics.png` — individual Pi screenshots
- `Botanika_Field_Intelligence_Pi_Deck.pptx` — six-slide deck using the Pi screenshots and the Botanika palette

The plant walkthrough loads the saved `Mimusops elengi` campus image, accepts the catalog match, saves it to the library, opens the saved record, and places a synthetic demonstration point at **12.96930, 79.15650**. This is an east-side R-block demo coordinate derived from a VIT Vellore campus reference; it is labelled synthetic and is not a device GPS fix.

The weed walkthrough uses the installed detector result in `data/demo/weed-in-maize-field-result.json` against the openly licensed maize-field image in `data/demo/weed-in-maize-field.jpg`. It reports one generic `weed` cue; it does not claim species-level identification.

The user-experience opinions in the deck are labelled illustrative. They are a demo narrative, not a completed five-person validation study.
