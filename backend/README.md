# Backend boundary

This directory contains the first FastAPI slice of the modular monolith. The
connectivity placeholder is intentionally small: it proves the origin boundary
and crop transport before model, database, pairing, or classification modules
are introduced.

## Local run

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e 'backend[test]'
uvicorn botanika.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> and run `python tools/verify_connectivity.py` in
another terminal. Production settings are in
`config/environments/connectivity.env.example`.

The receipt endpoint is `POST /api/v1/connectivity/receipt` with a multipart
`image` part and optional JSON `metadata` part. It accepts only binary JPEG or
WebP, validates magic bytes and a full decode, and stores only a bounded
idempotency receipt. The image cap is 5 MiB and the whole multipart envelope is
6 MiB, leaving room for metadata and multipart framing. `Idempotency-Key` (or
`X-Request-ID`) makes a retry return the original receipt without processing the
image a second time.

Status events are available at `/ws/status` (with `/ws/session` retained as a
contract-compatible alias). They contain connection, heartbeat, and receipt
events only; no camera frames are sent over the socket.

The development default does not require Cloudflare credentials. Production
must set `BOTANIKA_ACCESS_REQUIRED=true`, the Cloudflare Access team domain,
application audience, and allowed owner email. The origin verifies the signed
`CF-Access-JWT-Assertion`; it does not trust a user-supplied email header.

The authoritative module ownership and dependency rules are documented in
[`docs/PI_ARCHITECTURE_AND_ROADMAP.md`](../docs/PI_ARCHITECTURE_AND_ROADMAP.md).
