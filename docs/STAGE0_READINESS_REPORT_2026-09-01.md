# Botanika Stage 0 Readiness Report — 2026-09-01

**Decision:** Ready with operator checks pending — automated and process-level
hardware checks pass, but a person at the Pi must still confirm that the camera
preview is visually correct, the microphone recording is intelligible, and the
speaker output is audible and clear.

This report records measured facts from the Pi host and distinguishes them from
the product targets in the architecture documents. No camera image, spoken
sample, or other personal media was retained.

## Baseline

| Item | Measured result | Status |
| --- | --- | --- |
| Board | Raspberry Pi 5 Model B Rev 1.1; `aarch64` | Pass |
| OS | Debian GNU/Linux 13 (trixie), version `13.6` after supported `apt-get upgrade` | Pass; 7 packages kept back by ordinary upgrade policy |
| Kernel | `6.12.62+rpt-rpi-2712` | Pass |
| RAM | `15.8 GiB` total, `13.9 GiB` available at post-upgrade probe, `2.0 GiB` swap | Pass against 16 GB target |
| Application storage | `/home/pi/Botanika` on `/dev/nvme0n1p2`; `468 GiB` total, `396.3 GiB` free | Pass |
| Python | `3.13.5` | Pass |
| Node.js | `v20.19.2` | Informational |
| Temperature | `44.4–49.9 °C` during an operator-stopped sustained preview | Partial; no throttling observed |
| Throttling | `vcgencmd get_throttled` reports `0x0` | Pass |
| Display | X11 `:0`; HDMI-1 primary, `800×480 @ 60 Hz`, inverted orientation, 108×68 mm | Pass; visual/operator check pending |
| Camera stack | `rpicam-apps 1.13.0`; `libcamera 0.7.2+rpt20260817-1`; `libpisp 1.7.0` | Pass |
| Camera | Sony IMX708, 4608×2592; native preview and still capture work | Pass at process level; visual/operator check pending |
| Audio | USB PnP Audio Device at card 0 for capture/playback; HDMI playback also enumerated | Pass at device level; intelligibility/audibility pending |

The filesystem target is the mounted NVMe volume, not temporary media. The
project path is writable.

## Package and environment preparation

The project virtual environment was created at `.venv` with
`--system-site-packages`, so the native Picamera2/libcamera bindings remain
available. The following imports succeeded from the project environment:

| Import | Version/result |
| --- | --- |
| `numpy` | `2.5.1` |
| `cv2` | `5.0.0` |
| `picamera2` | available |
| `libcamera` | available |
| `onnxruntime` | `1.27.0` |

ONNX Runtime is the selected YOLO-compatible runtime for Phase 2. No model
artifact was downloaded or activated. The exact dependency inputs are:

- [`phase0-native-packages.txt`](../config/environments/phase0-native-packages.txt)
- [`phase0-python-requirements.txt`](../config/environments/phase0-python-requirements.txt)

The observed post-upgrade native package versions are recorded in the first
file. The Python pins match the already available runtime packages; no PyPI
download was needed for this baseline.

The verifier now compares the exact direct distribution pins as a scoped
environment-health gate. A generic `pip check` is not authoritative here
because `--system-site-packages` exposes unrelated Debian Python metadata; its
typing-package/debconf findings are outside Botanika's direct dependency set.

## Supported OS update

The pre-update system reported Debian version `13.3`, `rpicam-apps 1.11.1`,
`libcamera 0.7.0+rpt20260205-1`, and Picamera2 `0.3.34`. The following supported
workflow was used; no distribution upgrade or autoremove was performed:

```text
sudo apt-get update
sudo apt-get upgrade -y
```

The ordinary upgrade completed successfully and upgraded 404 packages. It kept
back seven packages: the two Pi kernel images, two matching header packages,
`rpd-common`, `rpd-preferences`, and `rpi-eeprom`. A post-upgrade simulation
reported `0 upgraded, 0 newly installed, 0 to remove and 7 not upgraded`.
`dpkg --audit` returned no findings, and `/var/run/reboot-required` was absent.

## Tests and evidence

Commands run:

```text
python3 -m py_compile tools/verify_phase0.py
python3 tools/verify_phase0.py --json
DISPLAY=:0 XAUTHORITY=/home/pi/.Xauthority \
  .venv/bin/python tools/verify_phase0.py --probe-capture --strict --json
rpicam-hello --timeout 300000 --fullscreen --width 800 --height 480
rpicam-still --nopreview --timeout 1000 --output /tmp/botanika-stage0-reacquire-1.jpg
rpicam-still --nopreview --timeout 1000 --output /tmp/botanika-stage0-reacquire-2.jpg
arecord --dump-hw-params -D plughw:0,0 -d 1 -f S16_LE -r 16000 -c 1 /dev/null
speaker-test -D plughw:0,0 -t sine -f 440 -c 1 -s 1 -l 1
apt-get -s upgrade
.venv/bin/python tests/hardware/test_verify_phase0.py -v
```

Observed results:

- The post-upgrade strict verifier returned exit code `0` with every automated
  check passing.
- Camera enumeration reports the IMX708 and its 1536×864, 2304×1296, and
  4608×2592 modes.
- A five-minute X/EGL native preview completed with exit code `0`.
- A temporary post-upgrade still was a valid 897,849-byte JPEG and was deleted.
- Two immediate 4608×2592 captures after the preview were 894,401 and 895,331
  bytes. Their hashes differed, both commands succeeded, and both files were
  deleted; this proves release and reacquisition at the process level.
- XRandR reports the exact required 800×480 mode at 60 Hz. The screen is
  configured with inverted orientation; this is a measured configuration, not
  an application transform.
- The USB microphone opened at 16 kHz mono S16_LE and released without retaining
  audio. The USB speaker accepted one bounded 440 Hz mono test cycle.
- The verifier regression suite passed 3/3 tests, including invalid and missing
  capture failures.
- Post-preview temperature was 46.6 °C and throttling remained `0x0`.
- A longer sustained preview was stopped at the operator's request after about
  11 minutes. It peaked at 49.9 °C, used about 7.1% CPU and 116 MiB RSS at one
  sample, and never reported throttling during the observed interval.

No camera image, screenshot, microphone recording, or other personal media was
retained.

## Managed-shell limitation discovered

Initial verifier runs inside the managed filesystem/device sandbox could not see
`/dev/media*`, `/dev/dma_heap`, `/dev/vcio`, `/dev/snd`, or the X11 environment.
Those runs correctly reported blocked capabilities, but they did not describe
the host hardware. Repeating the probes with host-device access and explicit
`DISPLAY=:0`/Xauthority proved the hardware paths above. Future hardware runs
must use the local desktop or equivalent host-device access.

## Deferred final operator acceptance

1. A person at the Pi must confirm the native preview shows a correctly
   oriented, live image with usable autofocus.
2. A person at the Pi must make a short spoken recording, confirm it is
   intelligible without clipping or excessive noise, delete it, and confirm the
   speaker tone/output is audible and clear.
3. Reboot once during an operator-approved maintenance window and confirm the
   desktop returns at 800×480. No automatic reboot was performed in this
   session.

These checks are now consolidated in
[`DEFERRED_OPERATOR_ACCEPTANCE.md`](DEFERRED_OPERATOR_ACCEPTANCE.md). The owner
has deferred them until final acceptance; they remain open and must not be
reported as passed in the meantime.

## Automated-gate verdict

**Phase 0 automated readiness passes; final operator acceptance remains open.**
All automated checks and the native preview/capture process pass. Under the
owner-approved scheduling exception, later automated implementation may proceed
while the human-observed visual/audio checks and reboot recovery confirmation
remain explicitly deferred.

### Post-audit automated rerun

After the verifier gained exact direct-pin validation, a direct-device strict
run again passed camera enumeration, active 800×480 display mode, microphone and
speaker enumeration, writable storage, required imports, exact NumPy/OpenCV/ONNX
Runtime pins, and throttling (`0x0`). No preview judgment, audio playback or
recording, image capture, or reboot was performed as part of that rerun.
