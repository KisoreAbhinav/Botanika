import test from "node:test";
import assert from "node:assert/strict";
import {
  getTunnelState,
  MODES,
  isNetworked,
  modeLabel,
  pairingCodeFromLocation,
  pairingDeepLink,
  tunnelConnectUrl,
  tunnelState,
} from "./modeState.js";

test("mode labels distinguish SOLO, unpaired, and paired states", () => {
  assert.equal(modeLabel(MODES.SOLO), "Solo");
  assert.equal(modeLabel(MODES.NETWORKED_UNPAIRED), "Networked · waiting to pair");
  assert.equal(modeLabel(MODES.NETWORKED_PAIRED), "Networked · paired");
  assert.equal(isNetworked(MODES.SOLO), false);
  assert.equal(isNetworked(MODES.NETWORKED_PAIRED), true);
});

test("tunnel helpers select the secure URL and preserve loading/failure states", () => {
  const status = {
    tunnel: { enabled: true, state: "starting", url: null, connect_url: null },
  };
  assert.equal(getTunnelState(status), status.tunnel);
  assert.equal(tunnelState(status), "starting");
  assert.equal(tunnelConnectUrl(status), null);
  status.tunnel = {
    enabled: true,
    state: "ready",
    url: "https://fern.trycloudflare.com",
    connect_url: "https://fern.trycloudflare.com",
  };
  assert.equal(tunnelState(status), "ready");
  assert.equal(tunnelConnectUrl(status), "https://fern.trycloudflare.com");
  assert.equal(pairingDeepLink({ pairing: { deep_link: "https://fern.trycloudflare.com/?pair=23456789" } }), "https://fern.trycloudflare.com/?pair=23456789");
});

test("pairing query helper accepts only the bounded invitation alphabet", () => {
  assert.equal(
    pairingCodeFromLocation({ search: "?pair=2345ABCD" }),
    "2345ABCD",
  );
  assert.equal(pairingCodeFromLocation({ search: "?pair=not-a-code" }), null);
  assert.equal(pairingCodeFromLocation({ search: "?pair=2345" }), null);
});
