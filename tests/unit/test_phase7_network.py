"""Phase 7 private-network configuration, probing, and operator contracts."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from botanika.core.capabilities import CapabilitiesReport, CapabilityState
from botanika.core.settings import AppSettings
from botanika.network import (
    AccessPointConfig,
    AccessPointError,
    AccessPointManager,
    CommandResult,
    NetworkConfigurationError,
    NetworkStatusProbe,
)
from tools.run_api import resolve_safe_bind


def firewall_payload(interface: str = "wlan0", port: int = 8000) -> str:
    def match(left, right, op="=="):
        return {"match": {"op": op, "left": left, "right": right}}

    iif = {"meta": {"key": "iifname"}}
    tcp_port = {"payload": {"protocol": "tcp", "field": "dport"}}
    rules = [
        {"rule": {"chain": "input", "expr": [match(iif, "lo"), match(tcp_port, port), {"accept": None}]}},
        {"rule": {"chain": "input", "expr": [match(iif, interface), match(tcp_port, port), {"accept": None}]}},
        {"rule": {"chain": "input", "expr": [match(iif, interface), {"drop": None}]}},
        {
            "rule": {
                "chain": "input",
                "expr": [match(iif, interface, "!="), match(tcp_port, port), {"drop": None}],
            }
        },
        {"rule": {"chain": "forward", "expr": [match(iif, interface), {"drop": None}]}},
    ]
    return json.dumps({"nftables": rules})


class Phase7NetworkTests(unittest.TestCase):
    def test_default_settings_are_still_loopback_only(self):
        settings = AppSettings()
        self.assertTrue(settings.loopback_only)
        self.assertFalse(settings.network_enabled)

    def test_network_settings_select_wildcard_listener_and_private_ap(self):
        settings = AppSettings(network_enabled=True, loopback_only=False, host="0.0.0.0")
        self.assertEqual(settings.access_point_address, "192.168.50.1")
        self.assertEqual(settings.local_hostname, "botanika.home.arpa")

    def test_ap_address_only_bind_is_rejected_because_it_loses_loopback(self):
        with self.assertRaisesRegex(ValueError, "loopback remains available"):
            AppSettings(
                network_enabled=True,
                loopback_only=False,
                host="192.168.50.1",
            )

    def test_non_loopback_listener_cannot_be_enabled_without_phase7_mode(self):
        with self.assertRaisesRegex(ValueError, "network_enabled"):
            AppSettings(host="0.0.0.0", loopback_only=False)

    def test_environment_loader_does_not_change_imported_defaults(self):
        settings = AppSettings.from_environment(
            {
                "BOTANIKA_NETWORK_ENABLED": "true",
                "BOTANIKA_HOST": "0.0.0.0",
                "BOTANIKA_LOOPBACK_ONLY": "false",
                "BOTANIKA_AP_INTERFACE": "wlan1",
                "BOTANIKA_AP_HOSTNAME": "botanika-field.home.arpa",
            }
        )
        self.assertTrue(settings.network_enabled)
        self.assertFalse(settings.loopback_only)
        self.assertEqual(settings.access_point_interface, "wlan1")
        self.assertEqual(settings.access_point_address, "192.168.50.1")
        self.assertEqual(settings.local_hostname, "botanika-field.home.arpa")
        self.assertTrue(AppSettings().loopback_only)

    def test_unicast_dns_configuration_rejects_reserved_dot_local_name(self):
        with self.assertRaisesRegex(NetworkConfigurationError, "multicast DNS"):
            AccessPointConfig(hostname="botanika.local")

    def test_ap_config_rejects_dhcp_range_that_contains_ap(self):
        with self.assertRaises(NetworkConfigurationError):
            AccessPointConfig(
                dhcp_start="192.168.50.1",
                dhcp_end="192.168.50.20",
            )

    def test_config_metadata_never_contains_passphrase(self):
        config = AccessPointConfig(passphrase="a-private-test-passphrase")
        self.assertNotIn("passphrase", config.to_dict())
        self.assertNotIn("private-test", str(config.to_dict()))

    def test_status_is_unavailable_when_ap_is_disabled(self):
        status = NetworkStatusProbe(AccessPointConfig()).status()
        self.assertFalse(status.available)
        self.assertEqual(status.state, "disabled")
        self.assertEqual(status.transport, "loopback")
        self.assertIn("SOLO", status.detail)

    def test_status_requires_all_transport_boundaries(self):
        config = AccessPointConfig(enabled=True, passphrase="a-private-test-passphrase")

        def which(name: str):
            return f"/usr/bin/{name}"

        def command(argv, timeout):
            if argv[:3] == ("nmcli", "-t", "-f"):
                return CommandResult(
                    0,
                    "GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:botanika-ap\n",
                )
            if argv[:2] == ("systemctl", "is-active"):
                return CommandResult(0)
            if argv[:4] == ("nft", "--json", "list", "table"):
                return CommandResult(0, firewall_payload())
            return CommandResult(0)

        probe = NetworkStatusProbe(
            config,
            command=command,
            which=which,
            interface_exists=lambda interface: interface == "wlan0",
            interface_address=lambda interface: "192.168.50.1",
            listener=lambda port, address: port == 8000,
            dns_listener=lambda port, address: port == 53 and address == "192.168.50.1",
            dhcp_listener=lambda port, address: port == 67 and address == "192.168.50.1",
            dns_resolver=lambda hostname, address: hostname == "botanika.home.arpa"
            and address == "192.168.50.1",
        )
        status = probe.status()
        self.assertTrue(status.available)
        self.assertEqual(status.state, "active")
        self.assertEqual(status.stack, "networkmanager")
        self.assertTrue(all(status.checks.values()))

    def test_status_rejects_wrong_interface_listener_and_empty_firewall(self):
        config = AccessPointConfig(enabled=True)

        def command(argv, timeout):
            if argv[:3] == ("nmcli", "-t", "-f"):
                return CommandResult(0, "GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:botanika-ap\n")
            if argv[:2] == ("systemctl", "is-active"):
                return CommandResult(0)
            if argv[:4] == ("nft", "--json", "list", "table"):
                return CommandResult(0, json.dumps({"nftables": [{"table": {"name": "botanika"}}]}))
            return CommandResult(0)

        status = NetworkStatusProbe(
            config,
            command=command,
            which=lambda name: "/usr/bin/" + name,
            interface_exists=lambda interface: True,
            interface_address=lambda interface: config.address,
            listener=lambda port, address: address == "127.0.0.1",
            dns_listener=lambda port, address: True,
            dhcp_listener=lambda port, address: True,
            dns_resolver=lambda hostname, address: True,
        ).status()
        self.assertFalse(status.available)
        self.assertFalse(status.checks["firewall"])
        self.assertFalse(status.checks["listener"])

    def test_unprivileged_status_accepts_only_active_firewall_with_root_marker(self):
        config = AccessPointConfig(enabled=True)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "firewall.ready"
            marker.write_text(
                json.dumps(
                    {
                        "interface": config.interface,
                        "network": str(config.network),
                        "api_port": config.api_port,
                    }
                ),
                encoding="utf-8",
            )

            def command(argv, timeout):
                if argv[:2] == ("systemctl", "is-active"):
                    return CommandResult(0)
                if argv[:2] == ("nft", "--json"):
                    return CommandResult(1, stderr="Operation not permitted")
                return CommandResult(1)

            probe = NetworkStatusProbe(
                config,
                command=command,
                which=lambda name: "/usr/bin/" + name,
                firewall_ready_marker=marker,
            )
            self.assertTrue(probe._firewall_active())
            marker.unlink()
            self.assertFalse(probe._firewall_active())

    def test_manager_dry_run_redacts_wpa_secret_and_is_repeatable(self):
        config = AccessPointConfig(enabled=True, passphrase="a-private-test-passphrase")
        calls = []

        def command(argv, timeout):
            calls.append(tuple(argv))
            if tuple(argv) == ("nmcli", "-t", "-f", "NAME", "connection", "show"):
                return CommandResult(0, "some-other-profile\n")
            return CommandResult(0)

        manager = AccessPointManager(
            config,
            command=command,
            which=lambda name: "/usr/bin/" + name,
            uid=lambda: 0,
        )
        commands = manager.enable(dry_run=True)
        rendered = "\n".join(item.display() for item in commands)
        self.assertIn("nmcli connection add", rendered)
        self.assertIn("<redacted>", rendered)
        self.assertNotIn("a-private-test-passphrase", rendered)
        self.assertTrue(calls)

    def test_disable_and_recover_never_remove_the_firewall(self):
        config = AccessPointConfig(enabled=True, passphrase="a-private-test-passphrase")
        manager = AccessPointManager(
            config,
            command=lambda argv, timeout: CommandResult(0, "botanika-ap\n"),
            which=lambda name: "/usr/bin/" + name,
            uid=lambda: 0,
        )
        for action in ("disable", "recover"):
            commands = manager.plan(action, stack="networkmanager")
            rendered = "\n".join(item.display() for item in commands)
            self.assertNotIn("disable --now botanika-firewall.service", rendered)
            self.assertIn("botanika-dnsmasq.service", rendered)

    def test_network_bind_falls_back_to_loopback_when_boundary_is_incomplete(self):
        class IncompleteProbe:
            def boundary_checks(self):
                return {"interface": True, "address": False, "firewall": True}

        requested = AppSettings(network_enabled=True, loopback_only=False, host="0.0.0.0")
        resolved = resolve_safe_bind(requested, probe=IncompleteProbe())
        self.assertTrue(resolved.network_enabled)
        self.assertTrue(resolved.loopback_only)
        self.assertEqual(resolved.host, "127.0.0.1")

    def test_network_bind_opens_wildcard_only_after_complete_boundary(self):
        class CompleteProbe:
            def boundary_checks(self):
                return {"interface": True, "address": True, "firewall": True}

        requested = AppSettings(network_enabled=True, loopback_only=False, host="0.0.0.0")
        self.assertIs(resolve_safe_bind(requested, probe=CompleteProbe()), requested)

    def test_systemd_backend_is_not_hard_dependent_on_the_ap(self):
        root = Path(__file__).resolve().parents[2]
        backend_unit = (root / "deploy/systemd/botanika-backend.service").read_text(encoding="utf-8")
        ap_unit = (root / "deploy/systemd/botanika-access-point.service").read_text(encoding="utf-8")
        self.assertNotIn("Requires=botanika-access-point.service", backend_unit)
        self.assertNotIn("PartOf=botanika-backend.service", ap_unit)
        self.assertNotIn("run_api.py --network", backend_unit)

    def test_frontend_reads_the_flat_network_capability_model(self):
        root = Path(__file__).resolve().parents[2]
        app_source = (root / "frontend/src/app/App.jsx").read_text(encoding="utf-8")
        self.assertIn("capabilities.network?.model?.enabled", app_source)
        self.assertIn("capabilities?.network?.model", app_source)
        self.assertNotIn("model?.status", app_source)

    def test_hostapd_runtime_config_is_root_only_and_supports_transition_mode(self):
        config = AccessPointConfig(enabled=True, passphrase="a-private-test-passphrase")
        manager = AccessPointManager(config, uid=lambda: 0)
        with tempfile.TemporaryDirectory() as directory:
            output = manager.render_hostapd_config(Path(directory) / "hostapd.conf")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            text = output.read_text(encoding="utf-8")
        self.assertIn("wpa_key_mgmt=WPA-PSK SAE", text)
        self.assertIn("a-private-test-passphrase", text)

    def test_firewall_marker_is_published_only_for_matching_loaded_config(self):
        config = AccessPointConfig(enabled=True)
        manager = AccessPointManager(config, uid=lambda: 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rules = root / "nftables.conf"
            marker = root / "firewall.ready"
            rules.write_text(
                'define botanika_ap_if = "wlan0"\n'
                "define botanika_ap_net = 192.168.50.0/24\n"
                "define botanika_api_port = 8000\n",
                encoding="utf-8",
            )
            manager.write_firewall_ready_marker(marker, rules)
            self.assertEqual(
                json.loads(marker.read_text(encoding="utf-8")),
                {"interface": "wlan0", "network": "192.168.50.0/24", "api_port": 8000},
            )
            rules.write_text('define botanika_ap_if = "wlan1"\n', encoding="utf-8")
            with self.assertRaisesRegex(AccessPointError, "do not match"):
                manager.write_firewall_ready_marker(marker, rules)

    def test_network_required_readiness_is_separate_from_solo_readiness(self):
        ready = CapabilityState("ready", True, "ready")
        unavailable = CapabilityState("unavailable", False, "missing")
        report = CapabilitiesReport(
            camera=ready,
            detector=ready,
            classifier=ready,
            knowledge=ready,
            storage=ready,
            library=ready,
            preview=ready,
            network=unavailable,
            network_required=True,
        )
        self.assertFalse(report.ready)
        report = CapabilitiesReport(
            camera=ready,
            detector=ready,
            classifier=ready,
            knowledge=ready,
            storage=ready,
            library=ready,
            preview=ready,
            network=unavailable,
        )
        self.assertTrue(report.ready)


if __name__ == "__main__":
    unittest.main()
