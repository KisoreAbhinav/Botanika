# Demo readiness handoff

This handoff was verified on the Raspberry Pi deployment on 2026-09-06.

## Operator start

The enabled service is `botanika-backend.service`. The kiosk uses the local
build at `http://127.0.0.1:8000/`; the optional Quick Tunnel remains disabled
until the operator selects NETWORKED. Check the service and local readiness
before presenting the demo:

```sh
sudo systemctl is-active botanika-backend.service
curl http://127.0.0.1:8000/api/v1/health/live
curl http://127.0.0.1:8000/api/v1/health/ready
```

The deployed bundle includes the interactive discovery map, walking-directions
links, phone crop flow, and independent weed-beta view. The phone flow shows
possible matches as provisional suggestions; only an accepted production
result can be saved.

## Model status

The campus index is deliberately provisional. It has enrollment-only evidence,
no independent held-out or unknown images, and therefore remains unavailable
for library saves. The runtime still provides suggestions and displays the
validation reason. The weed model is a broadleaf visual cue trained/evaluated
on Wisconsin lawn imagery; it reports no species identity and has no Indian
crop or Botanika camera validation. Treat it as an experimental beta result.

Run the bounded visual smoke check against the included demo images when
needed:

```sh
sudo -u pi /opt/botanika/.venv/bin/python /opt/botanika/tools/verify_models.py \
  --images /opt/botanika/data/demo --skip-llm --skip-voice
```

## Rollback

Each deployment creates a timestamped backup under
`/opt/botanika/.demo-backups/`. To roll back, stop the backend, copy the files
from the selected backup back to their matching paths, and start the service:

```sh
sudo systemctl stop botanika-backend.service
# restore only the backed-up application/model files from the chosen directory
sudo systemctl start botanika-backend.service
```

The deployment procedure leaves the SQLite database, discovery media,
environment file, and unrelated LLM/voice assets in place.
