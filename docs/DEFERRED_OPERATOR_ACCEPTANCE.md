# Deferred Final Operator Acceptance

**Status:** intentionally deferred by the project owner; none of the checks in
this document are currently recorded as passed.

This checklist contains only verification that requires human judgment,
physical scene setup, or an approved reboot. Automated implementation may
continue, but Botanika is not release-accepted until every applicable item has
measured evidence and an operator result.

## Camera, display, and audio

- Confirm the native camera preview is live, correctly oriented, naturally
  colored, and able to autofocus at expected working distances.
- Confirm the Botanika/OpenCV preview has natural red and blue colors after the
  Picamera2 RGB888 byte-order correction.
- Confirm the display returns at exactly 800×480 with the intended scaling and
  orientation after an approved reboot.
- Record a short spoken microphone sample, confirm intelligibility and absence
  of unacceptable clipping/noise, then delete the sample.
- Confirm speaker tone and later speech output are audible and clear.

## Generic detector scene

- Run the live detector for at least five minutes with at least two ordinary
  COCO object types in view.
- Confirm the visible labels, confidence values, and boxes follow both objects.
- Confirm box colors align with the physical objects after the camera
  byte-order correction.
- Record FPS, p50/p95 inference latency, memory, temperature, and throttling.

## Lock-on calibration and physical trials

- Capture representative sharp, blurry, dark, bright, saturated, edge-clipped,
  small, moving, and stable Pi Camera samples without retaining personal media.
- Calibrate focus, exposure, saturation, size, edge, movement, and appearance
  thresholds from those samples; replace the `baseline_unvalidated` status.
- With one eligible target, observe `Tracking → Hold steady → Checking
  sharpness → Locked → Capturing → Captured` and verify exactly one crop file.
- Keep that target visible beyond cooldown and verify it does not save again.
- Remove the target for the disappearance tolerance, return it, and verify
  exactly one new capture can occur.
- Verify moving, blurry, clipped, too-small, dark, bright, and saturated targets
  do not auto-save.
- Verify disappearance and multi-target scenes select/rearm predictably.
- Inspect saved pixels to confirm only the padded crop is present, colors are
  natural, and no full-frame file was written.

## Phase 4 classifier display

- With an eligible target held steady, confirm the accepted crop automatically
  reaches the Phase 4 diagnostic and that the result visibly says `DEMO DATA`,
  `stub-phase-4`, and fake/demo rather than implying a real identification.
- Confirm an uncertain demo result is shown as `Not confident` and does not
  offer a confirmed-species save action.

## Final evidence

For each check, record the date, command/configuration, measured result,
operator verdict, and any retained non-personal fixture reference in the
appropriate phase report. Remove this scheduling exception only after all
deferred checks pass or are explicitly rejected with a documented blocker.
