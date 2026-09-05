# Local Kiosk Interface (Phase 6/7/8/9)

Standalone React 18 + Vite interface served by the same backend FastAPI service
on loopback in SOLO, the private Phase 7 AP link, or an optional Cloudflare
Quick Tunnel, and displayed by a
fullscreen browser on the Pi screen. The backend remains authoritative for
hardware, classification, botanical knowledge, and discovery data; the
frontend owns presentation, local interaction, overlay rendering, and
accessibility.

In Phase 8 the same React features have two layout contracts. The Pi keeps its
exact 800×480 shell. A portrait paired browser uses the responsive shell,
opens its own camera, performs local manual-crop quality checks, and sends only
the accepted crop to the Pi. The browser never streams live video to the
backend. A short-lived controller token is held as a browser session/cache;
the Pi remains authoritative for classification and library persistence.

When the operator enables the free no-account Quick Tunnel and selects
NETWORKED, the Pi console displays a locally generated QR code and HTTPS URL.
The phone can be on any internet-connected network; the QR deep link prefills
the one-time code without automatically submitting it. Quick Tunnel URLs are
random per process and intended for development/testing (no SLA, 200
in-flight request limit, no SSE), so the remote flow uses polling and uploads.

## Layout

- `src/app/App.jsx` — 800×480 shell, masthead, routing, toasts, diagnostics.
- `src/features/home` — three-card home screen with capability status strip.
- `src/features/scan` — camera workspace, canvas overlay (backend transform),
  status pill, stability strip, details panel, action bar, local-image fallback.
- `src/features/library` — species-grouped real discovery list with coverage,
  category filters, observation details, thumbnails, and confirm-delete.
- `src/features/ask` — grounded offline catalog chat with citations, explicit
  evidence abstention, and Pi-local voice controls.
- `src/features/weeds` — independent multi-box weed-beta workflow for SOLO and
  the paired browser. Secure phone origins own a live camera preview and send
  bounded, non-overlapping JPEG samples; insecure origins retain the native
  still-capture fallback. Image persistence stays disabled.
- `src/platform/api.js` — the only module that talks to `/api/v1`.
- `qrcode` — open-source local QR rendering; no third-party QR image API is
  contacted.
- `src/components/icons.jsx` — inline square line-icon SVG set.
- `src/theme/theme.css` — exact InnoHack palette tokens, fixed Pi layout, and
  responsive paired-browser layout.

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

- The Pi shell is exactly 800×480; only the paired portrait browser uses the
  separate responsive shell.
- All colors/fonts come from CSS custom properties in `theme.css` (palette is
  locked to the InnoHack baseline; do not introduce new hues).
- Overlay geometry always comes from the snapshot's published transform; the
  frontend never re-derives letterbox math.
- Results are labelled DEMO DATA whenever `result.is_stub` is true. Normal
Phase 6 runtime results use the catalog classifier and never carry that flag;
  the current unvalidated release abstains and disables Save to Library until
  measured deployment evidence is recorded.
- Browser geolocation is requested only for an explicit paired-browser save or
  a live weed sample. Unavailable, denied, or inaccurate coordinates never
  block inference, and weed persistence is skipped unless a validated fix is
  available.
