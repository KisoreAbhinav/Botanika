# Botanika UI refresh — 2026-09-04

This evidence records the InnoHack-derived kiosk interaction and layout pass.
The read-only references used were:

- `/home/pi/InnoHack/InnoHack/frontend/src/index.css`
- `/home/pi/InnoHack/InnoHack/frontend/src/App.jsx`
- `/home/pi/InnoHack/InnoHack/frontend/NewThemeReferences/`

## Interaction contract

The fixed kiosk shell remains 800×480 with a 66px masthead and 414px body.
The shell scales down around its true centre when a smaller landscape viewport is
used; it does not upscale or reflow the Pi canvas. Portrait paired browsers keep
their responsive layout.

On the kiosk or an explicitly paired browser:

| Key | Action |
| --- | --- |
| `1` | Scan for Plants |
| `2` | Library |
| `3` | Weed Detection when the beta detector is ready |
| `A` | Ask Botanika |
| `H` | Home |
| `Esc` | Home, close help/diagnostics, or cancel an in-progress scan |
| `F1` | Keyboard shortcut help |
| `D` | Capability diagnostics |
| `N` | Toggle SOLO/NETWORKED mode on the local operator kiosk |

Contextual controls advertise their own key only while that control is on the
current page:

| Key | Action |
| --- | --- |
| `Space` | Manual capture (or phone capture) |
| `L` | Local image / choose weed frame |
| `C` | Capture from image / apply phone crop |
| `X` | Clear local-image scan |
| `S` | Save an accepted result to the library |
| `R` | Retake / try another view |
| `G` | Another angle |
| `Esc` | Cancel an in-progress scan; otherwise home/close |
| `W` | Analyze the weed frame |
| `P` | Pause/resume live weed scanning |
| `E` | Export the library or weed coordinates |
| `Y` | Show captured plants |
| `V` | Show the Vellore regional checklist |
| `I` | Identify a paired-phone crop |

Shortcuts ignore modified keys, auto-repeat, text inputs, selects,
textareas/contenteditable regions, open dialogs, and page-root events while an
overlay is open. Contextual controls are resolved from the current page, so a
key never activates a hidden control from another screen. The help panel and
home quick-key strip make the available actions discoverable.

## Visual changes

- Masthead columns now use equal flexible side rails with an intrinsic centre,
  keeping the Botanika mark and wordmark centred when controls change width.
- Home card typography and icons are larger, copy is shorter and wraps cleanly,
  cards have more useful vertical presence, and the formerly empty middle band
  carries a readable quick-key strip.
- Result details use compact, readable metrics so provenance and demo status
  remain visible in the 330px scan side panel; unusually long details still
  scroll inside their designated panel.
- Long status, category, file-name, label, and result strings wrap instead of
  being hard-clipped. The mobile home quick-key strip participates in normal
  page flow so it cannot overlap the status row.

## Automated evidence

Screenshots are in `docs/evidence/ui-refresh-2026-09-04/`:

- `phase5/home-800x480.png`, `phase5/scan-result-800x480.png`
- `phase8/solo-800x480.png`, all three network handoff states, and paired
  browser 390×844 views
- `phase9/ask-800x480.png`, `phase9/weeds-800x480.png`, and the paired weed
  browser view

The updated Phase 5 verifier checks real keyboard navigation, overlay blocking,
dialog blocking, fixed-canvas dimensions, control sizes, and persistent
masthead branding/controls. Phase 6/8/9 verifiers cover the remaining kiosk and
portrait screens. Exact-state captures also wait for two compositor frames and
check the raster pixels for the brand, Ask control, and diagnostics control, so
the evidence cannot pass on DOM visibility alone.
