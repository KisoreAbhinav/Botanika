# Verification boundary

The first contract test suite is `contract/test_connectivity.py`. It verifies
the temporary receipt contract without a real network or Cloudflare account:

- liveness/readiness and the placeholder page;
- binary JPEG validation, decoded dimensions, and SHA-256 receipt;
- rejection of bytes whose magic does not match their declared MIME type;
- duplicate retry idempotency and conflicting-key rejection;
- empty application temp storage after receipt handling;
- WebSocket connection and ping/pong status events;
- signed Cloudflare Access assertion validation;
- image/rate-limit boundaries and loopback deployment configuration.

Run it from the repository root after installing `backend[test]`:

```bash
python -m pytest
```

The physical phone, different-network, Access, reboot, and latency checks in
`PHONE_PI_CONNECTIVITY_IMPLEMENTATION.md` remain deployment/e2e checks and
should be recorded outside Git.

The ordered installation and manual verification procedure is in
[`docs/STAGE0_TEST_RUNBOOK.md`](../docs/STAGE0_TEST_RUNBOOK.md).
