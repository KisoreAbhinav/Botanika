# Local Pi Deployment

Deployment is intentionally local:

- `systemd/` will hold backend, maintenance, and readiness-aware service units.
- `kiosk/` will hold fullscreen browser/session configuration for the Pi screen.

Deployment files should be added only after the local development flow passes
its relevant tests.
