# Web interface boundary

This directory contains the install-free responsive PWA placeholder for the
connectivity stage. It can be served directly by the supplied reverse-proxy
template or by the FastAPI development server. It lets a phone select one
small JPEG/WebP test crop, shows local dimensions and hash, uploads binary
multipart data to the same origin, and displays the Pi receipt.

The status WebSocket reconnects with bounded exponential backoff. It carries
small state events only. There is no camera stream, video element, screenshot
loop, or full-frame upload in this stage. Later scan work belongs under
`src/features/scan` and must preserve this crop-only boundary.
