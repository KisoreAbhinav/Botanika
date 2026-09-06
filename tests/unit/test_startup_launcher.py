from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import startup


class StartupLauncherTests(unittest.TestCase):
    def test_fresh_backend_environment_enables_phone_qr_tunnel(self):
        with patch.object(
            startup.shutil,
            "which",
            return_value="/usr/local/bin/cloudflared",
        ):
            environment = startup.backend_environment(
                {"PATH": "/usr/local/bin:/usr/bin"}
            )

        self.assertEqual(environment["BOTANIKA_TUNNEL_ENABLED"], "true")
        self.assertEqual(
            environment["BOTANIKA_CLOUDFLARED_PATH"],
            "/usr/local/bin/cloudflared",
        )
        self.assertEqual(environment["BOTANIKA_HOST"], "127.0.0.1")
        self.assertEqual(environment["BOTANIKA_LOOPBACK_ONLY"], "true")

    def test_build_token_and_kiosk_url_change_with_the_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            index.write_bytes(b"first")
            first = startup.frontend_build_token(index)
            index.write_bytes(b"second")
            second = startup.frontend_build_token(index)

        self.assertNotEqual(first, second)
        self.assertEqual(
            startup.cache_busted_url("http://127.0.0.1:8000/", second),
            f"http://127.0.0.1:8000/?build={second}",
        )

    def test_installed_managed_backend_is_detected(self):
        completed = SimpleNamespace(returncode=0, stdout="loaded\n")
        with (
            patch.object(startup.shutil, "which", return_value="/usr/bin/systemctl"),
            patch.object(startup.subprocess, "run", return_value=completed) as run,
        ):
            self.assertTrue(startup.managed_backend_is_installed())

        self.assertIn("botanika-backend.service", run.call_args.args[0])

    def test_active_managed_backend_is_detected(self):
        completed = SimpleNamespace(returncode=0, stdout="active\n")
        with (
            patch.object(startup.shutil, "which", return_value="/usr/bin/systemctl"),
            patch.object(startup.subprocess, "run", return_value=completed) as run,
        ):
            self.assertTrue(startup.managed_backend_is_active())

        self.assertEqual(
            run.call_args.args[0],
            ["systemctl", "is-active", "botanika-backend.service"],
        )

    def test_managed_backend_is_stopped_before_current_checkout_starts(self):
        completed = SimpleNamespace(returncode=0)
        with (
            patch.object(startup, "managed_backend_is_active", return_value=True),
            patch.object(startup, "wait_for_backend_to_stop") as wait,
            patch.object(startup.subprocess, "run", return_value=completed) as run,
        ):
            startup.stop_managed_backend("http://127.0.0.1:8000/api/v1/health/ready")

        self.assertEqual(
            run.call_args.args[0],
            ["sudo", "-n", "systemctl", "stop", "botanika-backend.service"],
        )
        wait.assert_called_once()

    def test_old_local_backend_is_terminated_gracefully(self):
        with (
            patch.object(startup, "local_backend_pids", return_value=[1234]),
            patch.object(startup, "process_is_alive", return_value=False),
            patch.object(startup.os, "kill") as kill,
        ):
            startup.stop_local_backends(8000)

        kill.assert_called_once_with(1234, startup.signal.SIGTERM)

    def test_backend_port_is_taken_from_launcher_argument(self):
        self.assertEqual(startup.backend_port(["--port", "8001"]), 8001)
        self.assertEqual(startup.backend_port(["--port=8002"]), 8002)


if __name__ == "__main__":
    unittest.main()
