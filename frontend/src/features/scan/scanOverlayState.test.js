import test from "node:test";
import assert from "node:assert/strict";

import { overlayAriaLabel, recognitionOverlayLabels } from "./scanOverlayState.js";

test("accepted Pi recognition uses Name and Confidence labels", () => {
  assert.deepEqual(
    recognitionOverlayLabels({
      status: "accepted",
      common_name: "Indian banyan",
      confidence: 0.937,
      is_stub: false,
    }),
    { top: "Name- Indian banyan", bottom: "Confidence- 94%" },
  );
});

test("live and uncertain overlays retain detection-state wording", () => {
  assert.equal(recognitionOverlayLabels({ status: "uncertain", confidence: 0.4 }), null);
  assert.match(overlayAriaLabel({ detections: [{ label: "plant" }] }), /1 live box/);
  assert.match(
    overlayAriaLabel({
      detections: [{ label: "plant" }],
      classification: { result: { status: "accepted", common_name: "Neem", confidence: 0.81 } },
    }),
    /Name- Neem\. Confidence- 81%/,
  );
});
