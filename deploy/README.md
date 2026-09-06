# Local Pi Deployment

Deployment is intentionally local. Phase 7 adds one private access-point
boundary and Phase 8 adds the single-controller handoff; there is still one
Pi backend, one authoritative library, and no account system. An optional
Cloudflare Quick Tunnel provides a free, temporary HTTPS transport when the
phone and Pi are on different networks.

- `network/` contains hostapd, dnsmasq, and nftables templates for the stable
  `192.168.50.1/24` private link.
- `systemd/` contains the backend, AP, DHCP/DNS, firewall, and fallback service
  units.
- `kiosk/` will hold fullscreen browser/session configuration for the Pi screen.

## Pi installation outline

The commands below assume the checkout is `/opt/botanika`, a `botanika` system
user exists, and the project virtual environment is at `/opt/botanika/.venv`.
The backend unit supplies the standard Raspberry Pi `video`, `render`, `audio`,
and `gpio` groups to that otherwise unprivileged service account. Confirm those
groups exist on the target image before enabling the unit.

### Internet pairing without the private AP

Install `cloudflared` separately at a verified local path (the example uses
`/usr/local/bin/cloudflared`), then set these values in the service environment:

```text
BOTANIKA_NETWORK_ENABLED=false
BOTANIKA_HOST=127.0.0.1
BOTANIKA_LOOPBACK_ONLY=true
BOTANIKA_TUNNEL_ENABLED=true
BOTANIKA_CLOUDFLARED_PATH=/usr/local/bin/cloudflared
BOTANIKA_TUNNEL_STARTUP_TIMEOUT_SECONDS=15
```

The AP units can remain disabled. Press NETWORKED on the Pi; after a short
startup the operator console shows a QR code, raw HTTPS URL, and one-time
pairing code. The phone opens the URL from any internet-connected network and
uses polling/uploads, not SSE. The Quick Tunnel has no account, domain, or
charge, but it is a Cloudflare development/testing feature with a random
per-process URL, no SLA, a 200 in-flight request limit, and no SSE support.

1. Keep a recovery path to the Pi's existing console or wired connection. Do
   not make the AP the only administration path while configuring it.
2. Install the supported Pi OS network stack. The operator selects
   NetworkManager automatically when `nmcli` is available; otherwise install
   `hostapd` and `dnsmasq-base`. The base package supplies the daemon without
   enabling a competing global dnsmasq service.
3. Copy `config/environments/phase7-network.env.example` to
   `/etc/botanika/botanika.env`, replace the WPA passphrase, and restrict it to
   mode `0600`.
   The example keeps the SQLite database, crops, temporary files, discoveries,
   and backup archives under `/var/lib/botanika`; create that state root with
   the tracked tmpfiles rule before first start.
4. Copy `deploy/network/dnsmasq.conf.example` to
   `/etc/botanika/dnsmasq.conf`, `deploy/network/nftables.conf.example` to
   `/etc/botanika/nftables.conf`, and install the units from `deploy/systemd/`
   into `/etc/systemd/system/`.
5. If the selected image uses the hostapd fallback, keep the generated runtime
   file at `/run/botanika/hostapd.conf`; `botanika-hostapd.service` renders it
   from the machine-local passphrase at start. Do not commit that file.
6. Run the read-only plan first:

   ```sh
   python3 /opt/botanika/tools/manage_access_point.py plan enable
   ```

7. Enable the AP and backend, then inspect both paths:

   ```sh
   systemctl daemon-reload
   systemd-tmpfiles --create /etc/tmpfiles.d/botanika.conf
   systemctl enable --now botanika-access-point botanika-backend
   python3 /opt/botanika/tools/manage_access_point.py status --json
   python3 /opt/botanika/tools/verify_phase7_network.py --live --strict
   ```

The tracked defaults provide SSID `Botanika`, AP address `192.168.50.1`, local
hostname `botanika.home.arpa`, DHCP leases `192.168.50.20–200`, and no forwarded
AP traffic. The backend reads AP intent from the environment and opens its
wildcard listener only after measuring the interface, address, Wi-Fi profile,
DHCP/DNS sockets, and complete firewall boundary. Otherwise it stays on
`127.0.0.1` so the kiosk remains usable and reports degraded AP readiness.
`http://botanika.home.arpa:8000/connect` is the minimal device-independent
landing page; `/` remains the same Phase 5/6 application.

Use `manage_access_point.py disable` to remove the AP while retaining the
firewall; with the AP interface down, the existing backend becomes effectively
loopback-only. Restart the backend to select a literal `127.0.0.1` listener.
Use `recover` after a failed AP start, then restart the backend after the AP is
healthy to admit AP requests. The live phone test remains an operator
checkpoint: join the SSID with mobile data disabled, load the landing page,
confirm the local hostname, then confirm that loopback kiosk access and the
same scan/library API remain available.

## Phase 8 mode handoff

The backend starts in SOLO with GPIO outputs safe and off before publishing
the SOLO LED state. Configure the optional BCM button/LED pins in
`/etc/botanika/botanika.env`; an unavailable GPIO library or failed pin setup
falls back to the software/API toggle without blocking service startup.

Press the configured mode button, use the Pi kiosk `Mode` action, or press
`N` during development to enter NETWORKED_UNPAIRED. The Pi shows the AP
guidance and a short-lived one-use pairing code. The first phone to pair owns
the controller lease; the Pi then becomes an 800×480 status console while the
phone uses its own camera and uploads only stability-gated JPEG samples or
explicit manual photos; continuous video remains on the phone. Lease expiry,
disconnect, takeover, mode changes, and restart revoke the controller.
The code is returned only to the Pi's loopback UI; remote status and landing
responses redact it, and operator mode/takeover controls reject AP clients.

On secure origins the paired browser requests live-camera permission. The
default private-HTTP AP uses the native still-camera input instead, keeping a
clearly marked local-photo/manual crop path without relying on secure-context
stream APIs. Position permission is requested only after the user presses
`Save to Pi library`; denial or unavailable/inaccurate position never blocks
the authoritative save.

## Phase 9 extras and production hardening

Before starting the service, install only manually verified local assets under
`models/`. Rebuild the offline knowledge index with:

```sh
.venv/bin/python /opt/botanika/tools/ingest_knowledge.py --database /var/lib/botanika/database/botanika.sqlite
```

The command runs offline and records catalog, chunk, and source/license
checksums. Missing speech, camera, or weed assets do not block typed catalog
lookup or the local shell.

Install `deploy/systemd/botanika-tmpfiles.conf` as a tmpfiles rule and enable
`botanika-kiosk.service` with the backend. The kiosk waits for the local
readiness endpoint, launches Chromium at 800×480, and restarts on failure.
Runtime user data consists of the SQLite database, managed crop/thumbnail
files, temporary crop directory, and backup archives; weed results never enter
the plant library and weed image persistence is disabled.

Run `.venv/bin/python tools/verify_phase9.py --strict` for the deterministic
contract check. It deliberately leaves camera/display/audio/model, cold-boot,
backup/restore, soak, and usability gates as operator measurements.
