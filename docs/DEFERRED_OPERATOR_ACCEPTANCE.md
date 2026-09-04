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

## Phase 7 private Wi-Fi

- Confirm a recovery path remains available before enabling the AP, then record
  the pre-change network state.
- On the target Pi, enable the configured AP and verify the stable
  `192.168.50.1/24` address, SSID, WPA2/WPA3-compatible authentication, and
  `botanika.home.arpa` resolution from a phone.
- With mobile data disabled, load `/connect`, `/api/v1/health/live`, and the
  same `/` application from the phone; verify the page is served by FastAPI and
  no internet connection is required.
- Inspect listeners and firewall rules on every interface: loopback and
  `wlan0` may reach the API, unrelated interfaces may not, and AP traffic must
  not be forwarded upstream.
- Verify DHCP/DNS lease and hostname behavior, backend restart and browser
  reconnection, AP stop/start, reboot recovery, and the explicit
  `manage_access_point.py recover` path.
- Confirm the Pi kiosk still reaches `127.0.0.1`, the camera/classifier/library
  services are unchanged, and `disable` returns safely to loopback SOLO.

## Phase 8 pairing and handoff

- With the configured button and LEDs attached, cold-boot the Pi and confirm
  outputs are safe during startup, the SOLO LED mapping is correct, a debounced
  press enters NETWORKED_UNPAIRED, and cleanup turns every LED off.
- From a phone joined only to the Pi AP, load the handoff page, confirm the AP
  guidance and short code, pair one browser, and verify the Pi returns to its
  exact 800×480 status console.
- Confirm a second browser cannot become controller, then verify explicit
  disconnect, mode change, operator takeover, lease expiry, and backend restart
  revoke the old controller and expose a fresh safe pairing path.
- On a real portrait phone, check camera permission allowed, denied, and
  unavailable paths. Confirm live video stays local, the manual fallback is
  clearly labelled, and only the selected crop reaches the Pi.
- Complete the paired scan journey: local camera frame → local quality/crop
  decision → crop hash/dimensions match across upload → Pi classification →
  returned name/confidence/details/category → local result box → authoritative
  Pi library save.
- Check reconnect, stale response, interrupted crop upload, Pi-unavailable, and
  retry/cancel behavior while the pending crop remains available.
- Check location allowed, denied, unavailable, and inaccurate cases. Confirm
  position is requested only on explicit save and that latitude, longitude,
  accuracy, timestamp, and source are retained only when valid.

## Phase 9 extras and final hardening

- Ingest the reviewed knowledge corpus offline; verify the source/license
  manifest, catalog checksum, FTS5 rows, compact embedding index, and stable
  chunk citations after a rebuild.
- Ask a known botanical question by text and by voice. Confirm the answer
  shows its local citations, an unrelated question says that evidence is
  insufficient, and microphone/speaker/model failure leaves typed chat usable.
- Verify voice start timeout, short-silence endpointing, one-owner audio
  coordination, cached models, and playback interruption on the real devices.
- Create repeated and deleted library discoveries, then back up and restore;
  confirm coverage, category progress, first/repeat indicators, milestones,
  and anonymous aggregate values reproduce from active records.
- In SOLO, run Weed Beta against a real Pi frame; in NETWORKED, analyze one
  captured paired-browser still. Confirm multiple supported boxes/confidences,
  no live browser video, no plant-library/image persistence, and the exact
  missing-position message: `Exact location could not be found. Coordinate
  collection was skipped.`
- Verify the independent weed model's crop/region/license scope and accurate
  coordinate-only records, with no drone or chemical control path.
- Perform cold/offline boot, service restart, camera/audio reacquisition,
  pairing recovery, disk-full/read-only, corrupt-model, database
  backup/restore, power-loss-safe, multi-hour soak, and five structured
  usability sessions. Record CPU, RAM, latency, temperature, throttling, and
  operator findings in the Phase 9 report.

## Final evidence

For each check, record the date, command/configuration, measured result,
operator verdict, and any retained non-personal fixture reference in the
appropriate phase report. Remove this scheduling exception only after all
deferred checks pass or are explicitly rejected with a documented blocker.
