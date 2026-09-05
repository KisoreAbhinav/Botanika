import test from "node:test";
import assert from "node:assert/strict";

import {
  deriveScanPanelState,
  isValidationPendingResult,
  selectedFallbackIndex,
  shouldManualCaptureFromKey,
} from "./scanState.js";

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
  assert.equal(
    deriveScanPanelState(snapshot({ status: "uncertain", validation_pending: true })),
    "validation-pending",
  );
  assert.equal(deriveScanPanelState(snapshot({ status: "error", error: "failed" })), "error");
  assert.equal(
    deriveScanPanelState({ ...snapshot(), hint: "Scan cancelled", processing: false }),
    "guidance",
  );
});

test("validation-pending is distinct from an uncertain camera view", () => {
  assert.equal(isValidationPendingResult({ status: "uncertain", validation_pending: true }), true);
  assert.equal(isValidationPendingResult({ status: "uncertain", validation_pending: false }), false);
  assert.equal(isValidationPendingResult({ status: "accepted", validation_pending: true }), false);
});

test("fallback capture follows the operator-selected box", () => {
  assert.equal(selectedFallbackIndex({ mode: "fallback", selected_index: 2 }), 2);
  assert.equal(selectedFallbackIndex({ mode: "fallback", selected_index: null }), 0);
  assert.equal(selectedFallbackIndex({ mode: "camera", selected_index: 3 }), 0);
});

test("Space requests a manual tree frame only during idle live scanning", () => {
  const event = { code: "Space", target: { matches: () => false } };
  assert.equal(
    shouldManualCaptureFromKey(event, {
      mode: "camera",
      camera_available: true,
      processing: false,
      classification: null,
    }),
    true,
  );
  assert.equal(
    shouldManualCaptureFromKey(event, {
      mode: "fallback",
      camera_available: true,
      processing: false,
      classification: null,
    }),
    false,
  );
  assert.equal(
    shouldManualCaptureFromKey(event, {
      mode: "camera",
      camera_available: true,
      processing: true,
      classification: null,
    }),
    false,
  );
  assert.equal(
    shouldManualCaptureFromKey({ ...event, target: { matches: () => true } }, null),
    false,
  );
  const dialog = { tagName: "DIALOG", parentElement: null };
  assert.equal(
    shouldManualCaptureFromKey({ ...event, target: { tagName: "div", parentElement: dialog } }, null),
    false,
  );
});
