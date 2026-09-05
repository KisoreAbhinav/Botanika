# Botanika kiosk runtime

`botanika-kiosk.service` waits for the local `/api/v1/health/ready` endpoint
before launching Chromium with a fixed 800×480 window. A degraded response is
still launchable: camera, audio, classifier, and weed-beta availability are
shown in the application while typed catalog lookup and local fallback paths
remain usable.

The unit assumes the Pi desktop user is `pi`, the checkout is `/opt/botanika`,
and X11 is available on `:0`. Adjust `User`, `DISPLAY`, and `XAUTHORITY` in a
machine-local unit override when the desktop session uses another account or
Wayland.

The browser has no remote URL or update channel. Chromium recovery is bounded
by systemd restart/backoff, and journald rate limits the launcher output.
