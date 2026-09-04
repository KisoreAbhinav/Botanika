import test from "node:test";
import assert from "node:assert/strict";

import { containedBox, containedImageRect } from "./weedGeometry.js";

test("contained image centers a wide source with vertical letterboxing", () => {
  const rect = containedImageRect(800, 480, 1600, 900);
  assert.deepEqual(rect, {
    width: 800,
    height: 450,
    offsetX: 0,
    offsetY: 15,
    scale: 0.5,
  });
  assert.deepEqual(containedBox({ x1: 100, y1: 80, x2: 500, y2: 380 }, 800, 480, 1600, 900), {
    left: 50,
    top: 55,
    width: 200,
    height: 150,
  });
});

test("contained image centers a tall source with horizontal letterboxing", () => {
  const box = containedBox({ x1: 0, y1: 20, x2: 400, y2: 620 }, 390, 844, 800, 1600);
  assert.equal(box.left, 0);
  assert.equal(box.top, 41.75);
  assert.equal(box.width, 195);
  assert.equal(box.height, 292.5);
});
