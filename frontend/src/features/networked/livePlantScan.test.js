import test from "node:test";
import assert from "node:assert/strict";

import {
  advanceStability,
  frameSignature,
  highestConfidenceMatch,
  signatureDifference,
} from "./livePlantScan.js";

function solidFrame(value, width = 8, height = 8) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let index = 0; index < data.length; index += 4) {
    data[index] = value;
    data[index + 1] = value;
    data[index + 2] = value;
    data[index + 3] = 255;
  }
  return { data, width, height };
}

test("stable camera frames build a bounded lock-on count", () => {
  const first = frameSignature(solidFrame(100));
  const second = frameSignature(solidFrame(104));
  const initial = advanceStability(null, first, 0);
  const stable = advanceStability(first, second, initial.stableChecks);
  assert.equal(initial.stableChecks, 1);
  assert.equal(stable.stableChecks, 2);
  assert.equal(stable.difference, 4);
});

test("a changed scene resets stability and can be distinguished from camera noise", () => {
  const first = frameSignature(solidFrame(80));
  const moved = frameSignature(solidFrame(150));
  const update = advanceStability(first, moved, 3);
  assert.equal(update.stableChecks, 1);
  assert.equal(signatureDifference(first, moved), 70);
});

test("the displayed live match is always the highest-confidence result", () => {
  assert.deepEqual(highestConfidenceMatch({
    status: "accepted",
    common_name: "Neem",
    scientific_name: "Azadirachta indica",
    confidence: 0.91,
  }), {
    common_name: "Neem",
    scientific_name: "Azadirachta indica",
    confidence: 0.91,
    accepted: true,
  });
  assert.deepEqual(highestConfidenceMatch({
    status: "uncertain",
    suggestions: [
      { common_name: "Banyan", scientific_name: "Ficus benghalensis", confidence: 0.42 },
      { common_name: "Neem", scientific_name: "Azadirachta indica", confidence: 0.68 },
    ],
  }), {
    common_name: "Neem",
    scientific_name: "Azadirachta indica",
    confidence: 0.68,
    accepted: false,
  });
});
