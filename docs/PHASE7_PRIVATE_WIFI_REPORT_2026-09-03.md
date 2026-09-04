# Phase 7 Implementation Report — Private Pi Wi-Fi

**Started:** 2026-09-03
**Last verified:** 2026-09-03
**Scope:** `BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md` → Phase 7
**Status:** transport boundary implemented; physical AP exit gate remains deferred

## Delivered

### Transport and runtime

- `AppSettings()` remains loopback-only and is unchanged for imported SOLO
  callers.
- The backend starts the same FastAPI modular monolith with a wildcard listener
  only after the complete AP/firewall boundary passes a live preflight. A
  failed AP falls back to loopback while degraded network readiness stays
  visible.
- The stable defaults are `wlan0`, `192.168.50.1/24`, SSID `Botanika`, local
  hostname `botanika.home.arpa`, DHCP leases `192.168.50.20–200`, and API port
  `8000`.
- `GET /api/v1/network/status` and the `network` capability report measured
  interface, address, AP stack, DHCP/DNS sockets on the AP address, required
  firewall rules, and API listeners on both AP and loopback. AP mode makes
  network readiness required; SOLO readiness does not depend on an optional AP.
- `/connect` (with `/network` as a short alias) is a small no-JavaScript,
  device-independent landing page. The existing `/` application and all scan,
  classification, knowledge, and library routes remain shared.

### Pi deployment and recovery

- NetworkManager is selected when `nmcli` is available; hostapd plus dnsmasq is
  the fallback. The AP manager uses argv-based bounded commands and supports
  `plan`, `enable`, `disable`, `recover`, and `render-hostapd`.
- AP failure is not a hard dependency of the backend. Disable and recovery keep
  the firewall installed, preventing a wildcard backend from becoming exposed
  through an unrelated interface.
- WPA secrets are read only from machine-local environment state, redacted from
  plans/status, rendered into a root-only runtime hostapd file, and never kept
  in Git.
- Tracked templates provide hostapd WPA2/WPA3 transition settings, isolated
  DHCP/local DNS, and nftables rules that allow only AP DHCP/DNS/FastAPI traffic
  and drop AP forwarding. Unrelated interfaces cannot reach the wildcard API
  port through the supplied firewall boundary.
- `verify_phase7_network.py` performs the repository/static contract check
  anywhere and adds AP, loopback, landing-page, and status HTTP checks with
  `--live --strict` on the Pi.

## Verification

- Phase 7 unit and existing API contracts: **42 tests passed**.
- Full Python suite after implementation: **110 tests passed**.
- Frontend Node state suite: **3 tests passed**.
- Repository network verifier: **all static checks passed**.
- Frontend production build: verified with `npm run build` after the Phase 7
  header/client change.

## Goal check and remaining operator gate

The same application, settings boundary, status API, landing page, operator
recovery path, deployment templates, secret handling, and AP-only firewall
contract are implemented. The physical Phase 7 exit gate is not claimed yet:
this workspace does not expose a `wlan0` AP, does not have `hostapd` available,
and has not run the required reboot, DHCP/DNS, per-interface listener, or
phone-with-mobile-data-disabled tests. Those checks belong on the target Pi and
remain recorded for final operator acceptance; no network reachability is
fabricated by the application.
