"""Measured private access-point status, with no configuration-only claims."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import struct
import shutil
import socket
import subprocess
from typing import Callable, Sequence

from .config import AccessPointConfig


DEFAULT_FIREWALL_READY_MARKER = Path("/run/botanika/firewall.ready")


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[Sequence[str], float], CommandResult]


def run_command(argv: Sequence[str], timeout: float = 2.0) -> CommandResult:
    """Run one bounded read-only system probe."""

    try:
        result = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(127, "", str(exc))
    return CommandResult(result.returncode, result.stdout, result.stderr)


@dataclass(frozen=True, slots=True)
class AccessPointStatus:
    """A serializable snapshot of AP and listener checks."""

    enabled: bool
    available: bool
    state: str
    transport: str
    interface: str
    address: str
    hostname: str
    url: str
    stack: str | None
    detail: str
    checks: dict[str, bool]

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "state": self.state,
            "transport": self.transport,
            "interface": self.interface,
            "address": self.address,
            "hostname": self.hostname,
            "url": self.url,
            "stack": self.stack,
            "detail": self.detail,
            "checks": dict(self.checks),
        }


class NetworkStatusProbe:
    """Probe AP state using only bounded, read-only OS operations."""

    def __init__(
        self,
        config: AccessPointConfig,
        *,
        command: CommandRunner = run_command,
        which: Callable[[str], str | None] = shutil.which,
        interface_exists: Callable[[str], bool] | None = None,
        interface_address: Callable[[str], str | None] | None = None,
        listener: Callable[[int, str], bool] | None = None,
        dns_listener: Callable[[int, str], bool] | None = None,
        dhcp_listener: Callable[[int, str], bool] | None = None,
        dns_resolver: Callable[[str, str], bool] | None = None,
        firewall_ready_marker: Path = DEFAULT_FIREWALL_READY_MARKER,
    ) -> None:
        self.config = config
        self._command = command
        self._which = which
        self._interface_exists = interface_exists or _interface_exists
        self._interface_address = interface_address or _interface_ipv4
        self._listener = listener or _tcp_listener_present_on
        self._dns_listener = dns_listener or _dns_listener_present_on
        self._dhcp_listener = dhcp_listener or _udp_listener_present_on
        self._dns_resolver = dns_resolver or _dns_name_resolves_to
        self._firewall_ready_marker = firewall_ready_marker

    def status(self) -> AccessPointStatus:
        config = self.config
        base = {
            "interface": False,
            "address": False,
            "wifi": False,
            "dhcp": False,
            "dns": False,
            "firewall": False,
            "listener": False,
        }
        if not config.enabled:
            return AccessPointStatus(
                enabled=False,
                available=False,
                state="disabled",
                transport="loopback",
                interface=config.interface,
                address=config.address,
                hostname=config.hostname,
                url=config.url,
                stack=None,
                detail="Private Wi-Fi is disabled; SOLO loopback transport remains active.",
                checks=base,
            )

        boundary, stack = self._boundary_snapshot()
        base.update(boundary)
        # A wildcard IPv4 socket covers both addresses. If the server ever
        # moves to explicit sockets, require both the kiosk and AP listeners.
        base["listener"] = self._listener(config.api_port, config.address) and self._listener(
            config.api_port,
            "127.0.0.1",
        )

        required = tuple(base.values())
        available = all(required)
        if available:
            state = "active"
            detail = "Private Wi-Fi access point, local DNS/DHCP, firewall, and FastAPI listener are ready."
        else:
            state = "degraded" if any(required) else "unavailable"
            missing = ", ".join(name for name, value in base.items() if not value)
            detail = f"Private Wi-Fi is not reachable yet; failed checks: {missing}."
        return AccessPointStatus(
            enabled=True,
            available=available,
            state=state,
            transport="private-access-point",
            interface=config.interface,
            address=config.address,
            hostname=config.hostname,
            url=config.url,
            stack=stack,
            detail=detail,
            checks=base,
        )

    def boundary_checks(self) -> dict[str, bool]:
        """Measure the AP boundary independently of the not-yet-started API.

        The service launcher uses this before opening a wildcard socket. It is
        deliberately stricter than checking process or unit names alone.
        """

        checks, _stack = self._boundary_snapshot()
        return checks

    def _boundary_snapshot(self) -> tuple[dict[str, bool], str | None]:
        config = self.config
        checks = {
            "interface": self._interface_exists(config.interface),
            "address": self._observed_address(config.interface) == config.address,
            "wifi": False,
            "dhcp": False,
            "dns": False,
            "firewall": False,
        }
        stack, checks["wifi"] = self._wifi_state()
        dnsmasq_active = self._service_active("botanika-dnsmasq.service")
        checks["dhcp"] = dnsmasq_active and self._dhcp_listener(67, config.address)
        checks["dns"] = (
            dnsmasq_active
            and self._dns_listener(53, config.address)
            and self._dns_resolver(config.hostname, config.address)
        )
        checks["firewall"] = self._firewall_active()
        return checks, stack

    def _observed_address(self, interface: str) -> str | None:
        address = self._interface_address(interface)
        if address:
            return address
        if self._which("nmcli"):
            result = self._command(("nmcli", "-g", "IP4.ADDRESS", "device", "show", interface), 2.0)
            for line in result.stdout.splitlines():
                candidate = line.strip().split("/", 1)[0]
                if candidate:
                    return candidate
        return None

    def _wifi_state(self) -> tuple[str | None, bool]:
        if self._which("nmcli"):
            result = self._command(
                ("nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", self.config.interface),
                2.0,
            )
            if result.returncode == 0:
                output = result.stdout.lower()
                connected = "100 (connected)" in output or "general.state:100" in output
                named = self.config.connection_name.lower() in output
                if connected and named:
                    return "networkmanager", True
        if self._which("hostapd") and self._service_active("botanika-hostapd.service"):
            return "hostapd", True
        return None, False

    def _service_active(self, service: str) -> bool:
        if not self._which("systemctl"):
            return False
        result = self._command(("systemctl", "is-active", "--quiet", service), 2.0)
        return result.returncode == 0

    def _firewall_active(self) -> bool:
        if not self._which("nft"):
            return False
        result = self._command(("nft", "--json", "list", "table", "inet", "botanika"), 2.0)
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
            except (TypeError, json.JSONDecodeError):
                return False
            rules = [
                item["rule"]
                for item in payload.get("nftables", [])
                if isinstance(item, dict) and isinstance(item.get("rule"), dict)
            ]
            interface = self.config.interface
            port = self.config.api_port
            return all(
                (
                    _has_firewall_rule(rules, "input", "accept", iifname="lo", tcp_port=port),
                    _has_firewall_rule(rules, "input", "accept", iifname=interface, tcp_port=port),
                    _has_firewall_rule(
                        rules,
                        "input",
                        "drop",
                        iifname=interface,
                        iifname_operator="!=",
                        tcp_port=port,
                    ),
                    _has_firewall_rule(rules, "input", "drop", iifname=interface),
                    _has_firewall_rule(rules, "forward", "drop", iifname=interface),
                )
            )
        # The backend intentionally has no CAP_NET_ADMIN. The root-owned unit
        # writes this volatile marker only after nft accepts the full ruleset;
        # /run is cleared on reboot and ExecStop removes it.
        return self._service_active("botanika-firewall.service") and self._firewall_marker_matches()

    def _firewall_marker_matches(self) -> bool:
        try:
            payload = json.loads(self._firewall_ready_marker.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, TypeError, json.JSONDecodeError):
            return False
        return payload == {
            "interface": self.config.interface,
            "network": str(self.config.network),
            "api_port": self.config.api_port,
        }


def _interface_exists(interface: str) -> bool:
    try:
        return interface in {name for _, name in socket.if_nameindex()}
    except (AttributeError, OSError):
        return Path("/sys/class/net", interface).exists()


def _interface_ipv4(interface: str) -> str | None:
    """Read one IPv4 address without requiring psutil or the ``ip`` command."""

    if not _interface_exists(interface):
        return None
    try:
        import fcntl
        import struct

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            request = struct.pack("256s", interface.encode("ascii"))
            result = fcntl.ioctl(sock.fileno(), 0x8915, request)  # SIOCGIFADDR
        finally:
            sock.close()
        return socket.inet_ntoa(result[20:24])
    except (OSError, UnicodeEncodeError):
        return None


def _tcp_listener_present_on(port: int, address: str) -> bool:
    return _socket_present_on("/proc/net/tcp", port, address, required_state="0A")


def _udp_listener_present_on(port: int, address: str) -> bool:
    return _socket_present_on("/proc/net/udp", port, address)


def _dns_listener_present_on(port: int, address: str) -> bool:
    """Require both UDP and TCP DNS sockets on the AP address."""

    return _udp_listener_present_on(port, address) and _tcp_listener_present_on(port, address)


def _dns_name_resolves_to(hostname: str, address: str) -> bool:
    """Query the configured AP resolver and verify its A response locally."""

    try:
        labels = hostname.rstrip(".").encode("ascii").split(b".")
        question = b"".join(bytes((len(label),)) + label for label in labels) + b"\x00"
        transaction_id = 0xB07A
        packet = struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
        packet += question + struct.pack("!HH", 1, 1)
        expected_address = socket.inet_aton(address)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.75)
            sock.sendto(packet, (address, 53))
            response, peer = sock.recvfrom(4096)
        finally:
            sock.close()
    except (OSError, UnicodeEncodeError, ValueError):
        return False
    if len(response) < 12 or peer != (address, 53):
        return False
    response_id, flags, _questions, answers, _authority, _additional = struct.unpack(
        "!HHHHHH", response[:12]
    )
    return response_id == transaction_id and flags & 0x000F == 0 and answers > 0 and expected_address in response


def _socket_present_on(
    path: str,
    port: int,
    address: str,
    *,
    required_state: str | None = None,
) -> bool:
    if port <= 0:
        return False
    try:
        lines = Path(path).read_text(encoding="ascii").splitlines()[1:]
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return False
    for line in lines:
        columns = line.split()
        if len(columns) < 4 or (required_state is not None and columns[3] != required_state):
            continue
        try:
            raw_address, raw_port = columns[1].rsplit(":", 1)
            local_port = int(raw_port, 16)
            local_address = socket.inet_ntoa(bytes.fromhex(raw_address)[::-1])
        except (OSError, ValueError):
            continue
        if local_port == port and local_address in {address, "0.0.0.0"}:
            return True
    return False


def _has_firewall_rule(
    rules: list[dict[str, object]],
    chain: str,
    verdict: str,
    *,
    iifname: str,
    iifname_operator: str = "==",
    tcp_port: int | None = None,
) -> bool:
    for rule in rules:
        if rule.get("chain") != chain:
            continue
        expressions = rule.get("expr")
        if not isinstance(expressions, list) or not any(
            isinstance(expression, dict) and verdict in expression for expression in expressions
        ):
            continue
        interface_matches = False
        port_matches = tcp_port is None
        for expression in expressions:
            if not isinstance(expression, dict) or not isinstance(expression.get("match"), dict):
                continue
            match = expression["match"]
            left = match.get("left")
            if (
                isinstance(left, dict)
                and left.get("meta") == {"key": "iifname"}
                and match.get("op") == iifname_operator
                and match.get("right") == iifname
            ):
                interface_matches = True
            if (
                isinstance(left, dict)
                and left.get("payload") == {"protocol": "tcp", "field": "dport"}
                and match.get("op") == "=="
                and match.get("right") == tcp_port
            ):
                port_matches = True
        if interface_matches and port_matches:
            return True
    return False
