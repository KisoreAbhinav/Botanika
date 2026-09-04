from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from botanika.core.settings import AppSettings
from botanika.hardware.gpio import (
    GPIOPinConfig,
    MemoryGPIO,
    ModeGPIOAdapter,
    create_mode_gpio,
)
from botanika.mode import Mode, ModeError, ModeStateMachine, PairingAuthenticationError, PairingError
from botanika.vision.classification import DummyClassifier
from botanika.vision.services import ScanService


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class Phase8ModeTests(unittest.TestCase):
    def test_solo_unpaired_paired_solo_and_one_controller(self):
        clock = FakeClock()
        settings = AppSettings(pairing_ttl_seconds=30, pairing_code_length=8)
        service = ModeStateMachine(
            settings,
            clock=clock,
            token_factory=lambda: "T" * 32,
            code_factory=lambda length: "23456789",
        )
        self.assertEqual(service.mode, Mode.SOLO)
        self.assertEqual(service.toggle(), Mode.NETWORKED_UNPAIRED)
        invitation = service.status()["pairing"]
        self.assertEqual(invitation["code"], "23456789")
        paired = service.pair(invitation["code"], device_name="Field phone")
        self.assertEqual(service.mode, Mode.NETWORKED_PAIRED)
        self.assertEqual(paired["session_token"], "T" * 32)
        self.assertNotIn("session_token", service.status())
        with self.assertRaisesRegex(PairingError, "another controller"):
            service.pair("23456789", device_name="Second phone")
        self.assertEqual(service.authenticate(paired["session_token"]).device_name, "Field phone")
        service.set_mode(Mode.SOLO)
        with self.assertRaises(PairingAuthenticationError):
            service.authenticate(paired["session_token"])

    def test_expiry_revokes_lease_and_issues_a_new_invitation(self):
        clock = FakeClock()
        service = ModeStateMachine(
            AppSettings(pairing_ttl_seconds=5),
            clock=clock,
            token_factory=lambda: "U" * 32,
            code_factory=lambda length: "ABCDEFGH",
        )
        service.toggle()
        token = service.pair("ABCDEFGH")["session_token"]
        clock.advance(6)
        status = service.status()
        self.assertEqual(status["mode"], Mode.NETWORKED_UNPAIRED.value)
        self.assertIsNotNone(status["pairing"])
        self.assertEqual(status["controller_count"], 0)
        with self.assertRaises(PairingAuthenticationError):
            service.authenticate(token)

    def test_connection_health_uses_last_seen_and_heartbeat(self):
        clock = FakeClock()
        service = ModeStateMachine(
            AppSettings(pairing_ttl_seconds=30, controller_health_timeout_seconds=2),
            clock=clock,
            token_factory=lambda: "H" * 32,
            code_factory=lambda length: "HEALTHYY",
        )
        service.toggle()
        token = service.pair("HEALTHYY")["session_token"]
        self.assertTrue(service.status()["connection"]["healthy"])
        clock.advance(3)
        self.assertFalse(service.status()["connection"]["healthy"])
        service.heartbeat(token)
        self.assertTrue(service.status()["connection"]["healthy"])

    def test_networked_transition_fails_closed_when_configured_ap_is_unavailable(self):
        service = ModeStateMachine(
            AppSettings(network_enabled=True, loopback_only=True),
            network_available=lambda: False,
        )
        with self.assertRaisesRegex(ModeError, "access point"):
            service.toggle()
        self.assertEqual(service.mode, Mode.SOLO)

    def test_gpio_boot_debounce_led_mapping_and_cleanup(self):
        backend = MemoryGPIO()
        mode = Mode.SOLO

        def toggle():
            nonlocal mode
            mode = Mode.NETWORKED_UNPAIRED if mode is Mode.SOLO else Mode.SOLO
            return mode

        adapter = ModeGPIOAdapter(
            GPIOPinConfig(mode_button_pin=4, solo_led_pin=17, networked_led_pin=18, paired_led_pin=27, debounce_ms=250),
            on_toggle=toggle,
            backend=backend,
        )
        adapter.start()
        self.assertEqual(adapter.led_state, {"solo": True, "networked": False, "paired": False})
        self.assertTrue(adapter.button_pressed(now=1.0))
        self.assertEqual(adapter.led_state, {"solo": False, "networked": True, "paired": False})
        self.assertFalse(adapter.button_pressed(now=1.1))
        self.assertTrue(adapter.button_pressed(now=1.3))
        adapter.set_mode(Mode.NETWORKED_PAIRED)
        self.assertEqual(adapter.led_state, {"solo": False, "networked": True, "paired": True})
        adapter.cleanup()
        self.assertTrue(backend.cleaned)
        self.assertEqual(adapter.led_state, {"solo": False, "networked": False, "paired": False})

    def test_external_crop_preserves_uploaded_hash_and_never_needs_pi_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = AppSettings(
                database_path=root / "database.sqlite",
                demo_discoveries_dir=root / "demo",
                temp_crops_dir=root / "temp",
            )
            service = ScanService(settings, classifier=DummyClassifier())
            image = np.full((48, 64, 3), 120, dtype=np.uint8)
            ok, encoded = cv2.imencode(".png", image)
            self.assertTrue(ok)
            payload = encoded.tobytes()
            run = service.classify_external_crop(payload, image=image, request_id="browser-1")
            self.assertEqual(run.crop_hash, hashlib.sha256(payload).hexdigest())
            self.assertEqual(run.capture.width, 64)
            self.assertEqual(run.capture.height, 48)
            self.assertEqual(run.capture.path.read_bytes(), payload)
            self.assertEqual(service.latest_snapshot().mode, "controller")

    def test_takeover_during_classification_prevents_publish_and_discards_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = AppSettings(
                database_path=root / "database.sqlite",
                demo_discoveries_dir=root / "demo",
                temp_crops_dir=root / "temp",
            )
            mode = ModeStateMachine(
                settings,
                token_factory=lambda: "R" * 32,
                code_factory=lambda length: "RACE2345",
            )
            mode.toggle()
            paired = mode.pair("RACE2345")
            lease_id = paired["lease"]["lease_id"]
            scan = ScanService(settings, classifier=DummyClassifier())
            image = np.full((48, 64, 3), 120, dtype=np.uint8)
            ok, encoded = cv2.imencode(".png", image)
            self.assertTrue(ok)

            def revoke_then_commit(action):
                mode.takeover_controller()
                mode.commit_for_lease(lease_id, action)

            with self.assertRaises(PairingAuthenticationError):
                scan.classify_external_crop(
                    encoded.tobytes(),
                    image=image,
                    request_id="stale-browser-request",
                    controller_lease_id=lease_id,
                    commit_guard=revoke_then_commit,
                )
            self.assertIsNone(scan.latest_snapshot())
            self.assertEqual(list(settings.temp_crops_dir.glob("*")), [])

    def test_paired_mode_pauses_pi_camera_owner_for_browser_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = AppSettings(
                database_path=root / "database.sqlite",
                demo_discoveries_dir=root / "demo",
                temp_crops_dir=root / "temp",
            )
            service = ScanService(settings, classifier=DummyClassifier())
            service.set_application_mode(Mode.NETWORKED_PAIRED)
            waiting = service.latest_snapshot()
            self.assertEqual(waiting.mode, "controller")
            self.assertFalse(waiting.camera_available)
            self.assertIn("paired browser", waiting.hint)
            service.set_application_mode(Mode.SOLO)
            self.assertEqual(service.latest_snapshot().mode, "camera")

    def test_gpio_failure_falls_back_without_blocking_safe_startup(self):
        class BrokenGPIO(MemoryGPIO):
            def setup_output(self, _pin):
                raise RuntimeError("GPIO permission denied")

        settings = AppSettings(
            mode_button_pin=4,
            solo_led_pin=17,
            networked_led_pin=18,
            paired_led_pin=27,
        )
        adapter = create_mode_gpio(settings, lambda: Mode.NETWORKED_UNPAIRED, backend=BrokenGPIO())
        self.assertFalse(adapter.available)
        self.assertTrue(adapter.started)
        self.assertEqual(adapter.mode, Mode.SOLO)
        adapter.cleanup()

    def test_gpio_constructor_failure_also_falls_back_to_safe_solo(self):
        settings = AppSettings(
            mode_button_pin=4,
            solo_led_pin=17,
            networked_led_pin=18,
            paired_led_pin=27,
        )
        with patch(
            "botanika.hardware.gpio.RPiGPIOBackend.try_create",
            side_effect=OSError("GPIO library unavailable"),
        ):
            adapter = create_mode_gpio(settings, lambda: Mode.NETWORKED_UNPAIRED)
        self.assertFalse(adapter.available)
        self.assertTrue(adapter.started)
        self.assertEqual(adapter.mode, Mode.SOLO)
        adapter.cleanup()

    def test_environment_includes_phase8_limits_and_pins(self):
        settings = AppSettings.from_environment(
            {
                "BOTANIKA_MODE_BUTTON_PIN": "4",
                "BOTANIKA_SOLO_LED_PIN": "17",
                "BOTANIKA_NETWORKED_LED_PIN": "18",
                "BOTANIKA_PAIRED_LED_PIN": "27",
                "BOTANIKA_PAIRING_TTL_SECONDS": "45",
                "BOTANIKA_PAIRING_CODE_LENGTH": "10",
                "BOTANIKA_CONTROLLER_HEALTH_TIMEOUT_SECONDS": "35",
                "BOTANIKA_MAX_REMOTE_CROP_UPLOAD_BYTES": "4096",
            }
        )
        self.assertEqual(settings.mode_button_pin, 4)
        self.assertEqual(settings.pairing_ttl_seconds, 45.0)
        self.assertEqual(settings.pairing_code_length, 10)
        self.assertEqual(settings.controller_health_timeout_seconds, 35.0)
        self.assertEqual(settings.max_remote_crop_upload_bytes, 4096)


if __name__ == "__main__":
    unittest.main()
