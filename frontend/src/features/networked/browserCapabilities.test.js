import test from "node:test";
import assert from "node:assert/strict";

import {
  attachCameraStream,
  cameraAccessMode,
  canRequestPosition,
  positionPayload,
} from "./browserCapabilities.js";

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

test("camera streams can attach after a conditional video element mounts", () => {
  let played = false;
  const stream = { id: "phone-stream" };
  const video = {
    play() {
      played = true;
      return Promise.resolve();
    },
  };
  assert.equal(attachCameraStream(video, stream), true);
  assert.equal(video.srcObject, stream);
  assert.equal(video.autoplay, true);
  assert.equal(video.muted, true);
  assert.equal(video.playsInline, true);
  assert.equal(played, true);
  assert.equal(attachCameraStream(null, stream), false);
});

test("repeated media readiness events keep the same stream attached", () => {
  let playCount = 0;
  let assignmentCount = 0;
  let attached = null;
  const stream = { id: "phone-stream" };
  const video = {
    get srcObject() { return attached; },
    set srcObject(value) { assignmentCount += 1; attached = value; },
    play() {
      playCount += 1;
      return Promise.resolve();
    },
  };
  attachCameraStream(video, stream);
  attachCameraStream(video, stream);
  assert.equal(video.srcObject, stream);
  assert.equal(assignmentCount, 1);
  assert.equal(playCount, 2);
});

test("synchronous playback failures are reported", () => {
  let reported = null;
  const video = { play: () => { throw new Error("play failed"); } };
  assert.equal(attachCameraStream(video, { id: "phone-stream" }, (error) => { reported = error; }), false);
  assert.equal(reported?.message, "play failed");
});

test("camera playback failures are reported so the UI can offer a retry", async () => {
  let reported = null;
  const video = {
    play() {
      return Promise.reject(new Error("autoplay blocked"));
    },
  };
  assert.equal(attachCameraStream(video, { id: "phone-stream" }, (error) => { reported = error; }), true);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(reported?.message, "autoplay blocked");
});

test("detached video ignores a late playback rejection", async () => {
  let reported = false;
  const video = {
    isConnected: false,
    play: () => Promise.reject(new Error("detached")),
  };
  const stream = { getTracks: () => [{ readyState: "live" }] };
  attachCameraStream(video, stream, () => { reported = true; });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(reported, false);
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
