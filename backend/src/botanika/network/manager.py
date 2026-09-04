"""Explicit operator control for the private Wi-Fi access point."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Sequence

from .config import AccessPointConfig
from .status import CommandResult, CommandRunner, NetworkStatusProbe, run_command


class AccessPointError(RuntimeError):
    """A requested AP operation could not be completed safely."""


@dataclass(frozen=True, slots=True)
class PlannedCommand:
    """One executable operation in an AP recovery plan."""

    argv: tuple[str, ...]
    description: str
    redacted_positions: tuple[int, ...] = ()

    def display(self) -> str:
        return " ".join(
            _quote("<redacted>" if index in self.redacted_positions else part)
            for index, part in enumerate(self.argv)
        )


class AccessPointManager:
    """Manage the AP through a supported OS stack with dry-run support.

    The mutating path requires an explicit WPA passphrase.  Commands are argv
    lists, never shell strings, so SSIDs and interface values cannot become
    shell syntax.  The manager does not alter an upstream internet connection.
    """

    def __init__(
        self,
        config: AccessPointConfig,
        *,
        command: CommandRunner = run_command,
        which: Callable[[str], str | None] = shutil.which,
        uid: Callable[[], int] = os.geteuid,
        service_runner: Callable[[Sequence[str]], CommandResult] | None = None,
    ) -> None:
        self.config = config
        self._command = command
        self._which = which
        self._uid = uid
        self._service_runner = service_runner

    def select_stack(self) -> str:
        if self.config.stack != "auto":
            return self.config.stack
        if self._which("nmcli"):
            return "networkmanager"
        if self._which("hostapd") and self._which("dnsmasq"):
            return "hostapd"
        raise AccessPointError(
            "no supported AP stack found; install NetworkManager or hostapd plus dnsmasq"
        )

    def plan(self, action: str, *, stack: str | None = None) -> list[PlannedCommand]:
        if action not in {"enable", "disable", "recover"}:
            raise AccessPointError("action must be enable, disable, or recover")
        selected = stack or self.select_stack()
        if selected not in {"networkmanager", "hostapd"}:
            raise AccessPointError(f"unsupported AP stack: {selected}")
        commands: list[PlannedCommand] = []
        if action in {"disable", "recover"}:
            commands.extend(self._disable_plan(selected))
        if action in {"enable", "recover"}:
            if action == "recover" and selected == "networkmanager":
                commands.append(
                    PlannedCommand(
                        ("systemctl", "reload", "NetworkManager"),
                        "reload NetworkManager configuration after a recovery stop",
                    )
                )
            commands.extend(self._enable_plan(selected))
        return commands

    def status(self) -> dict[str, object]:
        return NetworkStatusProbe(self.config, command=self._command, which=self._which).status().to_dict()

    def enable(self, *, dry_run: bool = False) -> list[PlannedCommand]:
        return self._apply("enable", dry_run=dry_run)

    def disable(self, *, dry_run: bool = False) -> list[PlannedCommand]:
        return self._apply("disable", dry_run=dry_run)

    def recover(self, *, dry_run: bool = False) -> list[PlannedCommand]:
        return self._apply("recover", dry_run=dry_run)

    def _apply(self, action: str, *, dry_run: bool) -> list[PlannedCommand]:
        if not dry_run and self._uid() != 0:
            raise AccessPointError("AP changes require root; use --dry-run to inspect the recovery plan")
        selected = self.select_stack()
        if action in {"enable", "recover"} and not dry_run and not self.config.passphrase:
            raise AccessPointError(
                "a WPA passphrase is required for enable/recover; set BOTANIKA_AP_PASSPHRASE"
            )
        commands = self.plan(action, stack=selected)
        if dry_run:
            return commands
        for item in commands:
            result = self._run_mutation(item.argv)
            if result.returncode != 0:
                if action in {"disable", "recover"} and _safe_to_ignore_stop_failure(result):
                    continue
                raise AccessPointError(
                    f"{item.description} failed ({result.returncode}): "
                    f"{(result.stderr or result.stdout).strip() or 'no diagnostic'}"
                )
        return commands

    def _run_mutation(self, argv: Sequence[str]) -> CommandResult:
        if self._service_runner is not None:
            return self._service_runner(argv)
        try:
            result = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                timeout=20.0,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(127, "", str(exc))
        return CommandResult(result.returncode, result.stdout, result.stderr)

    def _enable_plan(self, stack: str) -> list[PlannedCommand]:
        config = self.config
        common = [
            PlannedCommand(
                ("systemctl", "enable", "--now", "botanika-firewall.service"),
                "apply AP-only firewall restrictions before opening the AP",
            ),
            PlannedCommand(
                ("systemctl", "enable", "--now", "botanika-dnsmasq.service"),
                "start private DHCP and local DNS",
            ),
        ]
        if stack == "networkmanager":
            add: list[PlannedCommand] = []
            add.append(
                PlannedCommand(
                    ("nmcli", "radio", "wifi", "on"),
                    "enable the Wi-Fi radio without changing the upstream connection",
                )
            )
            if not self._connection_exists():
                add.append(
                    PlannedCommand(
                        (
                            "nmcli",
                            "connection",
                            "add",
                            "type",
                            "wifi",
                            "ifname",
                            config.interface,
                            "con-name",
                            config.connection_name,
                            "ssid",
                            config.ssid,
                        ),
                        "create the NetworkManager AP profile if it does not exist",
                    )
                )
            modify = (
                "nmcli",
                "connection",
                "modify",
                config.connection_name,
                "802-11-wireless.mode",
                "ap",
                "802-11-wireless.band",
                "bg",
                "ipv4.method",
                "manual",
                "ipv4.addresses",
                config.cidr,
                "ipv4.never-default",
                "yes",
                "ipv6.method",
                "disabled",
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                config.passphrase or "",
                "connection.autoconnect",
                "no",
            )
            add.extend(
                [
                    PlannedCommand(
                        modify,
                        "configure a private WPA AP without an internet default route",
                        redacted_positions=(modify.index(config.passphrase or ""),),
                    ),
                    PlannedCommand(
                        ("nmcli", "connection", "up", config.connection_name),
                        "bring up the controlled AP profile",
                    ),
                ]
            )
            return common + add
        return common + [
            PlannedCommand(
                ("ip", "link", "set", "dev", config.interface, "up"),
                "bring the AP interface up",
            ),
            PlannedCommand(
                ("ip", "address", "replace", config.cidr, "dev", config.interface),
                "assign the stable private AP address",
            ),
            PlannedCommand(
                ("systemctl", "enable", "--now", "botanika-hostapd.service"),
                "start hostapd with the WPA2/WPA3 transition configuration",
            ),
        ]

    def _connection_exists(self) -> bool:
        if not self._which("nmcli"):
            return False
        result = self._command(("nmcli", "-t", "-f", "NAME", "connection", "show"), 2.0)
        return any(
            line.strip().replace("\\:", ":") == self.config.connection_name
            for line in result.stdout.splitlines()
        )

    def render_hostapd_config(self, output: Path) -> Path:
        """Render a root-only hostapd file from the machine-local passphrase."""

        if not self.config.passphrase:
            raise AccessPointError(
                "a WPA passphrase is required to render hostapd configuration"
            )
        if self._uid() != 0:
            raise AccessPointError("rendering hostapd configuration requires root")
        config = self.config
        key_management = "WPA-PSK SAE" if config.wpa3_transition else "WPA-PSK"
        content = "\n".join(
            [
                "# Generated by Botanika; do not commit this file.",
                f"interface={config.interface}",
                "driver=nl80211",
                f"ssid={config.ssid}",
                f"country_code={config.country_code.upper()}",
                "hw_mode=g",
                "channel=6",
                "ieee80211n=1",
                "wmm_enabled=1",
                "auth_algs=1",
                "wpa=2",
                f"wpa_key_mgmt={key_management}",
                "rsn_pairwise=CCMP",
                "ieee80211w=1" if config.wpa3_transition else "ieee80211w=0",
                "sae_require_mfp=0" if config.wpa3_transition else "# WPA2-only mode",
                "sae_pwe=1" if config.wpa3_transition else "# SAE disabled",
                f"wpa_passphrase={config.passphrase}",
                "ignore_broadcast_ssid=0",
                "",
            ]
        )
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(output)
        return output

    def write_firewall_ready_marker(self, output: Path, rules_path: Path) -> Path:
        """Publish the exact root-loaded firewall boundary for unprivileged probes."""

        if self._uid() != 0:
            raise AccessPointError("publishing firewall readiness requires root")
        try:
            rules = rules_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AccessPointError(f"cannot read installed firewall rules: {exc}") from exc
        definitions = {
            line.strip()
            for line in rules.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        expected = (
            f'define botanika_ap_if = "{self.config.interface}"',
            f"define botanika_ap_net = {self.config.network}",
            f"define botanika_api_port = {self.config.api_port}",
        )
        missing = [line for line in expected if line not in definitions]
        if missing:
            raise AccessPointError(
                "installed firewall rules do not match AP environment: " + ", ".join(missing)
            )
        payload = {
            "interface": self.config.interface,
            "network": str(self.config.network),
            "api_port": self.config.api_port,
        }
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o644)
        temporary.replace(output)
        return output

    def _disable_plan(self, stack: str) -> list[PlannedCommand]:
        config = self.config
        # Keep the firewall installed while the backend may still own a
        # wildcard socket. With the AP interface down, these rules leave the
        # application effectively loopback-only and prevent a failed recovery
        # from exposing FastAPI through Ethernet or another Wi-Fi interface.
        commands = [
            PlannedCommand(
                ("systemctl", "disable", "--now", "botanika-dnsmasq.service"),
                "stop private DHCP and DNS",
            ),
        ]
        if stack == "networkmanager":
            commands.append(
                PlannedCommand(
                    ("nmcli", "connection", "down", config.connection_name),
                    "stop the controlled AP profile",
                )
            )
        else:
            commands.extend(
                [
                    PlannedCommand(
                        ("systemctl", "disable", "--now", "botanika-hostapd.service"),
                        "stop hostapd",
                    ),
                    PlannedCommand(
                        ("ip", "address", "flush", "dev", config.interface),
                        "remove the AP address without changing another interface",
                    ),
                ]
            )
        return commands


def _quote(value: str) -> str:
    if value and all(char.isalnum() or char in "._:/-" for char in value):
        return value
    return repr(value)


def _safe_to_ignore_stop_failure(result: CommandResult) -> bool:
    """Treat already-stopped/missing units as idempotent cleanup outcomes."""

    diagnostic = f"{result.stdout}\n{result.stderr}".lower()
    return any(
        phrase in diagnostic
        for phrase in (
            "not loaded",
            "not found",
            "no such file",
            "already inactive",
            "unknown connection",
            "not active",
        )
    )
