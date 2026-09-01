# Named Cloudflare Tunnel

Create the named tunnel and Cloudflare Access application in the dashboard
before installing the Pi service. Replace the example hostname and UUID in a
machine-local copy of [`config.yml.example`](config.yml.example).

The production connector is token-based in the supplied systemd unit. Store the
token in `/etc/botanika/cloudflared.env` with mode `0600`:

```text
TUNNEL_TOKEN=the-secret-from-cloudflare
```

Install the official ARM64 `cloudflared` package, copy the unit from
`deploy/systemd/botanika-cloudflared.service` to `/etc/systemd/system/`, then
run `systemctl daemon-reload`, `systemctl enable --now botanika-cloudflared`.
Never put the token, tunnel JSON, or a private deployment record in the repo.

The published application service must be `http://127.0.0.1:8080`; it must not
point at a LAN address or a public/home-router address.
