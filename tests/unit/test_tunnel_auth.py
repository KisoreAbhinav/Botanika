"""Cloudflare proxy trust-boundary tests for operator-only routes."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from botanika.api.auth import (
    is_cloudflare_proxy_request,
    is_local_operator,
    mode_status_for_request,
    require_local_operator,
)
from botanika.core.errors import ControllerAuthorizationError


def request(*, peer: str = "127.0.0.1", headers: dict[str, str] | None = None):
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=headers or {},
    )


class TunnelAuthTests(unittest.TestCase):
    def test_normal_loopback_operator_remains_local(self):
        local = request(headers={"X-Forwarded-For": "198.51.100.4"})
        self.assertFalse(is_cloudflare_proxy_request(local))
        self.assertTrue(is_local_operator(local))
        require_local_operator(local)

    def test_genuine_cloudflare_markers_make_loopback_peer_remote(self):
        tunneled = request(
            headers={
                "CF-Connecting-IP": "198.51.100.4",
                "CF-Ray": "0123456789abcdef-SJC",
            }
        )
        self.assertTrue(is_cloudflare_proxy_request(tunneled))
        self.assertFalse(is_local_operator(tunneled))
        with self.assertRaises(ControllerAuthorizationError):
            require_local_operator(tunneled)

    def test_invalid_or_partial_markers_do_not_grant_or_remove_local_access(self):
        for headers in (
            {"CF-Connecting-IP": "not-an-ip", "CF-Ray": "0123456789abcdef-SJC"},
            {"CF-Connecting-IP": "198.51.100.4"},
            {"CF-Ray": "0123456789abcdef-SJC"},
            {"CF-Connecting-IP": "198.51.100.4", "CF-Ray": "short"},
        ):
            current = request(headers=headers)
            self.assertFalse(is_cloudflare_proxy_request(current), headers)
            self.assertTrue(is_local_operator(current), headers)

    def test_remote_mode_status_redacts_code_and_qr_deep_link(self):
        status = {
            "mode": "NETWORKED_UNPAIRED",
            "pairing": {
                "code": "23456789",
                "url": "https://leaf.trycloudflare.com",
                "deep_link": "https://leaf.trycloudflare.com/?pair=23456789",
            },
            "pairing_code": "23456789",
            "tunnel": {"state": "ready", "diagnostics": ["local detail"]},
            "network": {
                "tunnel": {"state": "ready", "diagnostics": ["local detail"]},
            },
        }
        visible = mode_status_for_request(status, request(
            headers={
                "CF-Connecting-IP": "198.51.100.4",
                "CF-Ray": "0123456789abcdef-SJC",
            }
        ))
        self.assertEqual(visible["client_role"], "remote")
        self.assertNotIn("code", visible["pairing"])
        self.assertNotIn("deep_link", visible["pairing"])
        self.assertIsNone(visible["pairing_code"])
        self.assertNotIn("diagnostics", visible["tunnel"])
        self.assertNotIn("diagnostics", visible["network"]["tunnel"])


if __name__ == "__main__":
    unittest.main()
