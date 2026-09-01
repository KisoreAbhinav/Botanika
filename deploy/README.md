# Deployment boundary

Future deployment assets are grouped by responsibility:

- `cloudflared/`: stable remote HTTPS ingress and access policy notes
- `reverse_proxy/`: local TLS/proxy headers, body limits, and static assets
- `systemd/`: backend, tunnel, kiosk, and maintenance units
- `kiosk/`: Pi screen session and browser launch configuration

No credentials or machine-specific tunnel files may be committed.
