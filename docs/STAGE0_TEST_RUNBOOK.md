# Stage 0 — Raspberry Pi Hardware Readiness Runbook

This runbook is the first execution step for Botanika. Its purpose is to prove
that the target Raspberry Pi can reliably provide every required hardware
capability before application or model work begins.

Do not install plant models, build the interface, or create application APIs in
this stage. Record evidence first so later design choices use measured limits.

## 1. Record the baseline

Create a short dated test report outside the runtime data directories. Record:

- Raspberry Pi model and RAM capacity;
- operating-system name, version, architecture, and kernel;
- free space on the SSD and the filesystem holding application data;
- Python and Node.js versions, if already installed;
- available memory before starting any tests;
- CPU temperature at idle; and
- connected display resolution and scaling.

The report must distinguish facts measured on this Pi from targets proposed in
the architecture.

## 2. Verify the camera

1. Confirm the camera appears through the supported Raspberry Pi camera stack.
2. Preview the camera on the Pi display for at least five minutes.
3. Capture several still images at the intended scan resolution.
4. Test a close leaf, a whole plant, a cluttered background, low light, and
   backlighting.
5. Record resolution, frame rate, autofocus behavior, capture latency, and any
   dropped frames or warnings.
6. Confirm the camera is released cleanly after the test so another process can
   acquire it.

**Pass condition:** repeatable preview and still capture with no persistent
device lock, crash, or corrupted image.

## 3. Verify the display and kiosk assumptions

1. Record the physical resolution, effective browser viewport, orientation, and
   input method.
2. Open a simple local page in the intended browser.
3. Check fullscreen behavior, touch or pointer input, text legibility, and
   whether the on-screen keyboard is usable.
4. Reboot once and verify that the desktop/display session returns normally.

**Pass condition:** the Pi can show and control a fullscreen local interface at
a known viewport size.

## 4. Verify microphone input

1. Enumerate audio capture devices and identify the intended microphone.
2. Record a short spoken sample without retaining unnecessary personal audio.
3. Check the recording for clipping, silence, excessive noise, and incorrect
   sample rate.
4. Record the stable device identifier and working format.

**Pass condition:** intelligible local speech can be captured repeatedly using
the same documented device selection.

## 5. Verify speaker output

1. Enumerate playback devices and identify the intended speaker.
2. Play a short test tone or spoken sample at low volume first.
3. Check volume control, intelligibility, and the selected default device.
4. Verify playback stops and releases the device cleanly.

**Pass condition:** clear local playback works repeatedly through the documented
output device.

## 6. Check audio coordination

Test capture followed by playback, then repeat the sequence several times.
Record whether the audio stack changes devices, deadlocks, or leaves a device
busy. Full duplex is not required; Botanika may use an explicit listen-then-speak
state machine.

## 7. Measure storage and thermal behavior

1. Confirm application data will reside on the SSD rather than temporary media.
2. Measure available capacity and basic read/write health using non-destructive
   tools.
3. Run the camera preview and ordinary system load for at least fifteen minutes.
4. Record peak CPU temperature, throttling state, and available memory.
5. Note the cooling hardware and ambient conditions.

**Pass condition:** no throttling, storage error, or unexplained resource loss
during the baseline workload.

## 8. Produce the readiness report

For each subsystem, record:

- detected device and configuration;
- exact test performed;
- observed result and measurement;
- pass, fail, or blocked;
- corrective action, if needed; and
- evidence location, without committing sensitive recordings.

End the report with one of these decisions:

- **Ready:** all required devices passed; proceed to the local application
  foundation.
- **Ready with constraints:** proceed only with the documented resolution,
  sample rate, thermal limit, or device choice.
- **Not ready:** stop and correct failed hardware or drivers before application
  development.

## Exit gate

Stage 0 is complete only when camera, display, microphone, speaker, SSD, and
thermal behavior have a recorded result and no unresolved failure blocks the
Pi-local application loop.
