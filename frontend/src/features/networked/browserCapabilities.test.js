import test from "node:test";
import assert from "node:assert/strict";

import { cameraAccessMode, canRequestPosition, positionPayload } from "./browserCapabilities.js";

test("secure browsers use local getUserMedia and geolocation", () => {
  const scope = {
    isSecureContext: true,
    navigator: {
      mediaDevices: { getUserMedia() {} },
      geolocation: {},
    },
  };
  assert.equal(cameraAccessMode(scope), "stream");
  assert.equal(canRequestPosition(scope), true);
});

test("private HTTP uses the native still-capture input and skips location", () => {
  const scope = {
    isSecureContext: false,
    navigator: {
      mediaDevices: { getUserMedia() {} },
      geolocation: {},
    },
  };
  assert.equal(cameraAccessMode(scope), "capture-input");
  assert.equal(canRequestPosition(scope), false);
});

test("save-time position accepts accurate fixes and rejects inaccurate data", () => {
  const allowed = positionPayload({
    coords: { latitude: 19.076, longitude: 72.8777, accuracy: 12 },
    timestamp: 1788364800000,
  });
  assert.deepEqual(allowed, {
    latitude: 19.076,
    longitude: 72.8777,
    accuracy_m: 12,
    timestamp: 1788364800,
    source: "paired-browser-geolocation",
  });
  assert.equal(positionPayload({
    coords: { latitude: 19.076, longitude: 72.8777, accuracy: 1001 },
    timestamp: 1788364800000,
  }), null);
});
