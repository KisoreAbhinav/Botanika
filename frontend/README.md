# Local Kiosk Interface (Phase 6)

Standalone React 18 + Vite interface served on loopback by the backend FastAPI
service and displayed by a fullscreen browser on the Pi screen. The backend
remains authoritative for hardware, classification, botanical knowledge, and
discovery data; the frontend owns presentation, local interaction, overlay
rendering, and accessibility.

## Layout

- `src/app/App.jsx` — 800×480 shell, masthead, routing, toasts, diagnostics.
- `src/features/home` — three-card home screen with capability status strip.
- `src/features/scan` — camera workspace, canvas overlay (backend transform),
  status pill, stability strip, details panel, action bar, local-image fallback.
- `src/features/library` — species-grouped real discovery list with coverage,
  category filters, observation details, thumbnails, and confirm-delete.
- `src/features/ask` — grounded offline catalog chat with citations and explicit
  evidence abstention. Voice remains deferred.
- `src/features/weeds` — clearly disabled beta shell.
- `src/platform/api.js` — the only module that talks to `/api/v1`.
- `src/components/icons.jsx` — inline square line-icon SVG set.
- `src/theme/theme.css` — exact InnoHack palette tokens and 800×480 layout.

## Commands

```bash
npm install          # once
npm test             # deterministic Scan UI-state decisions
npm run build        # production build into dist/ (served by the API at /)
npm run dev          # dev server on :5173, proxies /api and /media to :8000
```

Run the whole service with `../tools/run_api.py`. The kiosk expects the built
`dist/` directory; without it the API answers but `/` shows a build hint.

## Conventions

- Fixed 800×480 design; `App` scales the whole shell proportionally on other viewport sizes.
- All colors/fonts come from CSS custom properties in `theme.css` (palette is
  locked to the InnoHack baseline; do not introduce new hues).
- Overlay geometry always comes from the snapshot's published transform; the
  frontend never re-derives letterbox math.
- Results are labelled DEMO DATA whenever `result.is_stub` is true. Normal
  Phase 6 runtime results use the catalog classifier and never carry that flag;
  the current unvalidated release abstains and disables Save to Library until
  measured deployment evidence is recorded.
