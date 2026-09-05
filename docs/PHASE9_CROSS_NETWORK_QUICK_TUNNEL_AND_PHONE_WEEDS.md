# Cross-network phone access and live weed sampling

## Contract

The phone does not need to join the Pi's private Wi-Fi. With the optional
Cloudflare Quick Tunnel enabled, the Pi keeps FastAPI on loopback and
`cloudflared` publishes a temporary HTTPS `trycloudflare.com` origin. The Pi
operator enters NETWORKED mode, waits for the tunnel to report `ready`, and
shows the generated HTTPS URL/QR code plus the one-time pairing code. The
phone opens that URL from any internet-connected network and pairs there.

The frontend uses same-origin `/api/v1` URLs, so the public tunnel origin
reaches the same Pi data and classifier without a LAN address assumption. If
the tunnel is `starting`, `failed`, or unavailable, the operator console
shows the failure and retry/fallback action; a phone is never silently told
that a LAN-only URL will work over the internet.

Recommended loopback-only environment:

```text
BOTANIKA_NETWORK_ENABLED=false
BOTANIKA_HOST=127.0.0.1
BOTANIKA_LOOPBACK_ONLY=true
BOTANIKA_TUNNEL_ENABLED=true
BOTANIKA_CLOUDFLARED_PATH=/usr/local/bin/cloudflared
BOTANIKA_TUNNEL_STARTUP_TIMEOUT_SECONDS=15
```

Quick Tunnels are temporary development/testing transport. They have no SLA,
use a random URL per process, and do not support SSE. The paired browser
therefore uses polling and bounded requests/uploads.

## Trust and data boundaries

- A valid `CF-Connecting-IP` plus `CF-Ray` marker makes the local
  cloudflared hop remote for authorization; loopback alone cannot grant Pi
  operator access through a tunnel.
- Pairing consumes a one-time code and returns one bearer lease. Controller
  routes require that lease; takeover, expiry, disconnect, SOLO, and restart
  revoke it.
- Plant classification remains crop-only and preserves the request ID and
  SHA-256 crop hash through classification and save. Continuous plant video
  is never uploaded.
- Phone weed detection owns a local `getUserMedia` preview. It samples one
  JPEG at a bounded interval, never uploads a MediaStream, and refuses to
  overlap a request while a previous Pi inference is running.
- Weed samples are decoded and discarded in memory. Only a positive supported
  weed detection with a validated, accurate device coordinate creates a
  coordinate-only observation. No weed image, chemical recommendation, drone
  command, or other operational action is persisted.
- `/api/v1/weeds/runs` returns coordinate-only map data and
  `/api/v1/weeds/export` downloads the same data as JSON. Both require the
  local operator or active controller lease.

## Deterministic evidence

The integration test
`Phase5ApiContractTest.test_cloudflare_proxy_headers_keep_tunnel_callers_remote`
uses an ASGI loopback peer with genuine Cloudflare headers to model the
cloudflared local hop. It proves remote status redaction, rejection of
operator/takeover and unpaired data access, successful paired library access,
successful same-origin classifier crop access, and lease-protected weed run
access. It deliberately does not claim a live Cloudflare DNS/phone journey.

The weed storage tests prove that accurate positive detections expose a
location in `list_runs()` while image persistence remains disabled. The real
Pi/operator acceptance still needs a phone on a second internet connection:
open the displayed HTTPS URL, pair, allow camera/location, confirm live weed
boxes, download the JSON export, then take the Pi back to SOLO.
