# Deployment boundary

The connectivity-stage deployment assets are grouped by responsibility:

- `cloudflared/`: stable remote HTTPS ingress and access policy notes
- `reverse_proxy/`: local TLS/proxy headers, body limits, and static assets
- `systemd/`: backend, tunnel, kiosk, and maintenance units
- `kiosk/`: Pi screen session and browser launch configuration

No credentials or machine-specific tunnel files may be committed.

## Pi installation outline

The commands below assume the checkout is `/opt/botanika`, a `botanika` system
user exists, and a Python virtual environment is at `/opt/botanika/.venv`.

1. Install the backend into the virtual environment with
   `python -m pip install -e '/opt/botanika/backend'`.
2. Copy `config/environments/connectivity.env.example` to
   `/etc/botanika/botanika.env`, replace placeholders, and restrict it to mode
   `0600`.
3. Install Nginx and copy `reverse_proxy/botanika.conf.example` to the Nginx
   site configuration. Keep its listener at `127.0.0.1:8080`.
4. Install the backend and cloudflared units in `systemd/`. The tunnel unit
   requires both the backend and Nginx, so the public connector does not run
   against an absent origin. Create the
   machine-local `/etc/botanika/cloudflared.env` containing only the tunnel
   token, and run `systemctl daemon-reload` followed by
   `systemctl enable --now botanika-backend botanika-cloudflared`.
5. Confirm local readiness with `python tools/verify_connectivity.py
   http://127.0.0.1:8080` before testing the public hostname.

Cloudflare account setup, Access allowlisting, DNS route creation, and the
mobile-data test remain operator checkpoints because they require the project
owner's domain, account, and one-time PIN. The repository supplies the
loopback-safe templates and does not contain those secrets.
