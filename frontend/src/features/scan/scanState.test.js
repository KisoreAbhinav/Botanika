import test from "node:test";
import assert from "node:assert/strict";

import { deriveScanPanelState, selectedFallbackIndex } from "./scanState.js";

function snapshot(result = null, processing = false) {
  return {
    processing,
    classification: result ? { result } : null,
    mode: "camera",
    selected_index: null,
  };
}

test("scan panel covers detection, lock, and processing states", () => {
  assert.equal(deriveScanPanelState(null), "guidance");
  assert.equal(deriveScanPanelState({ ...snapshot(), state: "Locked" }), "guidance");
  assert.equal(deriveScanPanelState(snapshot(null, true)), "processing");
});

test("scan panel exposes accepted, uncertain, error, and cancelled outcomes safely", () => {
  assert.equal(deriveScanPanelState(snapshot({ status: "accepted" })), "result");
  assert.equal(deriveScanPanelState(snapshot({ status: "uncertain" })), "uncertain");
  assert.equal(deriveScanPanelState(snapshot({ status: "error", error: "failed" })), "error");
  assert.equal(
    deriveScanPanelState({ ...snapshot(), hint: "Scan cancelled", processing: false }),
    "guidance",
  );
});

test("fallback capture follows the operator-selected box", () => {
  assert.equal(selectedFallbackIndex({ mode: "fallback", selected_index: 2 }), 2);
  assert.equal(selectedFallbackIndex({ mode: "fallback", selected_index: null }), 0);
  assert.equal(selectedFallbackIndex({ mode: "camera", selected_index: 3 }), 0);
});
