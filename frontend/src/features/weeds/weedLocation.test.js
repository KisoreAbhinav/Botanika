import test from "node:test";
import assert from "node:assert/strict";

import { createLocationSampler } from "./weedLocation.js";

test("location sampler reuses a valid fix between bounded refreshes", async () => {
  let now = 1000;
  let calls = 0;
  const first = { latitude: 12.1, longitude: 77.5, accuracy_m: 8 };
  const second = { latitude: 12.2, longitude: 77.6, accuracy_m: 9 };
  const sample = createLocationSampler(
    async () => (++calls === 1 ? first : second),
    { clock: () => now, refreshIntervalMs: 10_000, maxAgeMs: 30_000 },
  );

  assert.deepEqual(await sample(), first);
  now += 5_000;
  assert.deepEqual(await sample(), first);
  assert.equal(calls, 1);
  now += 6_000;
  assert.deepEqual(await sample(), second);
  assert.equal(calls, 2);
});

test("location sampler shares refreshes, retains a recent fix, then expires it", async () => {
  let now = 0;
  let resolve;
  let calls = 0;
  const pending = new Promise((finish) => { resolve = finish; });
  const sample = createLocationSampler(
    () => { calls += 1; return calls === 1 ? pending : null; },
    { clock: () => now, refreshIntervalMs: 1_000, maxAgeMs: 2_000 },
  );
  const first = sample();
  const second = sample();
  assert.equal(first, second);
  assert.equal(calls, 0); // the getter is scheduled in a microtask
  resolve({ latitude: 18.5, longitude: 73.8, accuracy_m: 10 });
  assert.deepEqual(await first, { latitude: 18.5, longitude: 73.8, accuracy_m: 10 });
  assert.equal(calls, 1);

  now += 1_500;
  // A failed refresh while the last fix is still within its age bound keeps
  // that fix, so a live positive frame does not lose a usable coordinate.
  assert.deepEqual(await sample(), { latitude: 18.5, longitude: 73.8, accuracy_m: 10 });
  assert.equal(calls, 2);

  now += 2_100;
  // The cached fix is now older than maxAgeMs. A failed refresh must return
  // null, making the caller skip coordinate persistence rather than retain
  // stale GPS data.
  assert.equal(await sample(), null);
  assert.equal(calls, 3);
  now += 500;
  assert.equal(await sample(), null);
  assert.equal(calls, 3);
});
