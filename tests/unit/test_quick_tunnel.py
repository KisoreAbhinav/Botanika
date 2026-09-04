"""Focused contracts for the optional Cloudflare Quick Tunnel transport."""

from __future__ import annotations

import io
import subprocess
import threading
import time
import unittest

from botanika.core.settings import AppSettings
from botanika.network import (
    QuickTunnelService,
    extract_quick_tunnel_url,
)


class FakeProcess:
    def __init__(self, output: str = "", *, returncode: int | None = None) -> None:
        self.stdout = io.StringIO(output)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class KillFallbackProcess(FakeProcess):
    def terminate(self):
        self.terminated = True
        # Simulate a child that ignores SIGTERM until SIGKILL.
        self.returncode = None

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("cloudflared", timeout)
        return self.returncode


class QuickTunnelTests(unittest.TestCase):
    def test_parser_accepts_only_strict_quick_tunnel_origin(self):
        self.assertEqual(
            extract_quick_tunnel_url("INF https://leaf-7.trycloudflare.com"),
            "https://leaf-7.trycloudflare.com",
        )
        self.assertEqual(
            extract_quick_tunnel_url("INF https://leaf.trycloudflare.com."),
            "https://leaf.trycloudflare.com",
        )
        for line in (
            "http://leaf.trycloudflare.com",
            "https://leaf.trycloudflare.com/path",
            "https://leaf.trycloudflare.com.evil.example",
            "https://leaf.trycloudflare.com:443",
            "https://-leaf.trycloudflare.com",
            "https://leaf-.trycloudflare.com",
            "https://a_b.trycloudflare.com",
        ):
            self.assertIsNone(extract_quick_tunnel_url(line), line)

    def test_start_returns_immediately_and_reaches_ready_while_draining_output(self):
        process = FakeProcess(
            "2026-09-04 info https://leaf.trycloudflare.com\n"
            "2026-09-04 info still-connected\n"
        )
        calls = []

        def popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return process

        service = QuickTunnelService(
            enabled=True,
            port=8000,
            cloudflared_path="/usr/local/bin/cloudflared",
            startup_timeout_seconds=2,
            popen=popen,
        )
        started = time.monotonic()
        snapshot = service.start()
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(snapshot.state, "starting")
        self.assertTrue(self._wait_for(lambda: service.status().state == "ready"))
        self.assertEqual(service.status().url, "https://leaf.trycloudflare.com")
        self.assertTrue(
            self._wait_for(
                lambda: "still-connected" in " ".join(service.status().diagnostics)
            )
        )
        self.assertEqual(calls[0][0], [
            "/usr/local/bin/cloudflared",
            "tunnel",
            "--config",
            "/dev/null",
            "--no-autoupdate",
            "--url",
            "http://127.0.0.1:8000",
        ])
        self.assertIs(calls[0][1]["stderr"], __import__("subprocess").STDOUT)
        self.assertTrue(calls[0][1]["text"])
        self.assertTrue(service.stop().state == "idle")
        self.assertTrue(process.terminated)

    def test_early_exit_and_startup_timeout_are_visible(self):
        exited = FakeProcess("cloudflared: no internet\n", returncode=2)
        service = QuickTunnelService(enabled=True, popen=lambda *_args, **_kwargs: exited)
        service.start()
        self.assertTrue(self._wait_for(lambda: service.status().state == "failed"))
        self.assertEqual(service.status().error, "process_exit")
        self.assertIn("status 2", service.status().detail)

        hanging = FakeProcess()
        timeout_service = QuickTunnelService(
            enabled=True,
            startup_timeout_seconds=0.1,
            popen=lambda *_args, **_kwargs: hanging,
        )
        timeout_service.start()
        self.assertTrue(self._wait_for(lambda: timeout_service.status().state == "failed"))
        self.assertEqual(timeout_service.status().error, "startup_timeout")
        self.assertTrue(hanging.terminated)

    def test_exit_after_url_and_diagnostics_are_bounded(self):
        output = "https://leaf.trycloudflare.com\n" + "\n".join(
            f"diagnostic-{index}" for index in range(20)
        )
        process = FakeProcess(output, returncode=1)
        service = QuickTunnelService(
            enabled=True,
            diagnostic_limit=3,
            popen=lambda *_args, **_kwargs: process,
        )
        service.start()
        self.assertTrue(self._wait_for(lambda: service.status().state == "failed"))
        self.assertEqual(service.status().error, "process_exit")
        self.assertIn("after publishing", service.status().detail)
        self.assertLessEqual(len(service.status().diagnostics), 3)

    def test_stop_uses_kill_fallback_when_child_ignores_terminate(self):
        process = KillFallbackProcess()
        service = QuickTunnelService(
            enabled=True,
            startup_timeout_seconds=2,
            popen=lambda *_args, **_kwargs: process,
        )
        service.start()
        self.assertTrue(self._wait_for(lambda: service.process is process))
        stopped = service.stop()
        self.assertEqual(stopped.state, "idle")
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)

    def test_restart_terminates_previous_child_and_stale_worker_cannot_overwrite(self):
        old = FakeProcess()
        new = FakeProcess("https://new.trycloudflare.com\n")
        processes = iter((old, new))
        service = QuickTunnelService(
            enabled=True,
            startup_timeout_seconds=2,
            popen=lambda *_args, **_kwargs: next(processes),
        )
        service.start()
        # Give the first worker a chance to publish its process before restart.
        self.assertTrue(self._wait_for(lambda: service.process is old))
        service.retry()
        self.assertTrue(old.terminated)
        self.assertTrue(self._wait_for(lambda: service.status().state == "ready"))
        self.assertEqual(service.status().url, "https://new.trycloudflare.com")
        self.assertEqual(service.status().generation, 2)
        service.stop()

    def test_disabled_tunnel_never_starts_a_child(self):
        called = threading.Event()
        service = QuickTunnelService(enabled=False, popen=lambda *_args, **_kwargs: called.set())
        self.assertEqual(service.start().state, "idle")
        self.assertFalse(called.is_set())
        self.assertFalse(service.status().enabled)

    def test_environment_contract_is_independent_of_ap_networking(self):
        settings = AppSettings.from_environment(
            {
                "BOTANIKA_NETWORK_ENABLED": "false",
                "BOTANIKA_TUNNEL_ENABLED": "true",
                "BOTANIKA_CLOUDFLARED_PATH": "/usr/local/bin/cloudflared",
                "BOTANIKA_TUNNEL_STARTUP_TIMEOUT_SECONDS": "17.5",
            }
        )
        self.assertFalse(settings.network_enabled)
        self.assertTrue(settings.tunnel_enabled)
        self.assertEqual(settings.cloudflared_path, "/usr/local/bin/cloudflared")
        self.assertEqual(settings.tunnel_startup_timeout_seconds, 17.5)

        with self.assertRaisesRegex(ValueError, "BOTANIKA_TUNNEL_ENABLED"):
            AppSettings.from_environment({"BOTANIKA_TUNNEL_ENABLED": "maybe"})
        with self.assertRaisesRegex(ValueError, "tunnel_startup_timeout_seconds"):
            AppSettings(tunnel_enabled=True, tunnel_startup_timeout_seconds=0)

    @staticmethod
    def _wait_for(predicate, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())


if __name__ == "__main__":
    unittest.main()
