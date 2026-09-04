"""Validated, non-secret configuration for Botanika's private Wi-Fi link."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
import os
import re
from typing import Mapping


DEFAULT_ACCESS_POINT_INTERFACE = "wlan0"
DEFAULT_ACCESS_POINT_ADDRESS = "192.168.50.1"
DEFAULT_ACCESS_POINT_PREFIX_LENGTH = 24
DEFAULT_ACCESS_POINT_SSID = "Botanika"
DEFAULT_ACCESS_POINT_CONNECTION = "botanika-ap"
DEFAULT_LOCAL_HOSTNAME = "botanika.home.arpa"
DEFAULT_DHCP_START = "192.168.50.20"
DEFAULT_DHCP_END = "192.168.50.200"
DEFAULT_WIFI_COUNTRY_CODE = "IN"
DEFAULT_NETWORK_STACK = "auto"
PASSPHRASE_PLACEHOLDER = "REPLACE_WITH_A_RANDOM_PRIVATE_PASSPHRASE"

_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_STACKS = frozenset({"auto", "networkmanager", "hostapd"})


class NetworkConfigurationError(ValueError):
    """A network value is unsafe or cannot be represented by the deployer."""


@dataclass(frozen=True, slots=True)
class AccessPointConfig:
    """Private AP values shared by the application, CLI, and deploy templates.

    ``passphrase`` is optional for read-only status reporting.  Mutating
    operations require it and never include it in serialized status output.
    """

    interface: str = DEFAULT_ACCESS_POINT_INTERFACE
    address: str = DEFAULT_ACCESS_POINT_ADDRESS
    prefix_length: int = DEFAULT_ACCESS_POINT_PREFIX_LENGTH
    ssid: str = DEFAULT_ACCESS_POINT_SSID
    connection_name: str = DEFAULT_ACCESS_POINT_CONNECTION
    hostname: str = DEFAULT_LOCAL_HOSTNAME
    dhcp_start: str = DEFAULT_DHCP_START
    dhcp_end: str = DEFAULT_DHCP_END
    country_code: str = DEFAULT_WIFI_COUNTRY_CODE
    stack: str = DEFAULT_NETWORK_STACK
    api_port: int = 8000
    passphrase: str | None = None
    enabled: bool = False
    wpa3_transition: bool = True

    def __post_init__(self) -> None:
        if not _INTERFACE_RE.fullmatch(self.interface):
            raise NetworkConfigurationError(
                "access-point interface must be a Linux interface name up to 15 characters"
            )
        try:
            address = IPv4Address(self.address)
        except ValueError as exc:
            raise NetworkConfigurationError("access-point address must be an IPv4 address") from exc
        if address.is_loopback or address.is_multicast or address.is_unspecified:
            raise NetworkConfigurationError("access-point address must be a private unicast IPv4 address")
        if not address.is_private:
            raise NetworkConfigurationError("access-point address must be inside a private IPv4 range")
        if not 8 <= self.prefix_length <= 30:
            raise NetworkConfigurationError("access-point prefix length must be between 8 and 30")
        network = IPv4Network(f"{self.address}/{self.prefix_length}", strict=False)
        if not (network.network_address < address < network.broadcast_address):
            raise NetworkConfigurationError("access-point address cannot be a network or broadcast address")
        self._validate_dhcp_range(network)
        if not self.ssid or len(self.ssid.encode("utf-8")) > 32:
            raise NetworkConfigurationError("Wi-Fi SSID must contain 1 to 32 UTF-8 bytes")
        if any(character in self.ssid for character in "\x00\r\n"):
            raise NetworkConfigurationError("Wi-Fi SSID cannot contain control line breaks")
        if not self.connection_name or len(self.connection_name) > 64:
            raise NetworkConfigurationError("Network connection name must contain 1 to 64 characters")
        if any(character in self.connection_name for character in "\x00\r\n"):
            raise NetworkConfigurationError("Network connection name cannot contain control line breaks")
        _validate_hostname(self.hostname)
        if not re.fullmatch(r"[A-Za-z]{2}", self.country_code):
            raise NetworkConfigurationError("Wi-Fi country code must be a two-letter ISO code")
        if self.stack not in _STACKS:
            raise NetworkConfigurationError(
                f"network stack must be one of {', '.join(sorted(_STACKS))}"
            )
        if not 1 <= self.api_port <= 65535:
            raise NetworkConfigurationError("API port must be between 1 and 65535 for AP service mode")
        if self.passphrase is not None:
            _validate_passphrase(self.passphrase)

    def _validate_dhcp_range(self, network: IPv4Network) -> None:
        try:
            start = IPv4Address(self.dhcp_start)
            end = IPv4Address(self.dhcp_end)
        except ValueError as exc:
            raise NetworkConfigurationError("DHCP range must contain IPv4 addresses") from exc
        if start >= end or start not in network or end not in network:
            raise NetworkConfigurationError("DHCP range must be ordered and inside the AP subnet")
        ap_address = IPv4Address(self.address)
        if ap_address in {start, end} or start < ap_address < end:
            raise NetworkConfigurationError("DHCP range cannot include the AP address")
        if start in {network.network_address, network.broadcast_address} or end in {
            network.network_address,
            network.broadcast_address,
        }:
            raise NetworkConfigurationError("DHCP range cannot use subnet or broadcast addresses")

    @property
    def cidr(self) -> str:
        return f"{self.address}/{self.prefix_length}"

    @property
    def network(self) -> IPv4Network:
        return IPv4Network(self.cidr, strict=False)

    @property
    def url(self) -> str:
        return f"http://{self.address}:{self.api_port}/"

    @property
    def connect_url(self) -> str:
        return f"http://{self.hostname}:{self.api_port}/connect"

    def to_dict(self) -> dict[str, object]:
        """Return safe configuration metadata; never expose the passphrase."""

        return {
            "interface": self.interface,
            "address": self.address,
            "cidr": self.cidr,
            "prefix_length": self.prefix_length,
            "ssid": self.ssid,
            "connection_name": self.connection_name,
            "hostname": self.hostname,
            "dhcp_range": {"start": self.dhcp_start, "end": self.dhcp_end},
            "country_code": self.country_code.upper(),
            "stack": self.stack,
            "api_port": self.api_port,
            "url": self.url,
            "connect_url": self.connect_url,
            "enabled": self.enabled,
            "wpa3_transition": self.wpa3_transition,
        }

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        **overrides: object,
    ) -> "AccessPointConfig":
        """Load Phase 7 values from ``BOTANIKA_AP_*`` environment variables."""

        values = dict(environ or os.environ)
        def value(name: str, default: object) -> object:
            return overrides.get(name, values.get(f"BOTANIKA_AP_{name.upper()}", default))

        enabled_value = value("enabled", False)
        transition_value = value("wpa3_transition", True)
        raw_passphrase = value("passphrase", "")
        return cls(
            interface=str(value("interface", DEFAULT_ACCESS_POINT_INTERFACE)),
            address=str(value("address", DEFAULT_ACCESS_POINT_ADDRESS)),
            prefix_length=_as_int(value("prefix_length", DEFAULT_ACCESS_POINT_PREFIX_LENGTH), "prefix length"),
            ssid=str(value("ssid", DEFAULT_ACCESS_POINT_SSID)),
            connection_name=str(value("connection_name", DEFAULT_ACCESS_POINT_CONNECTION)),
            hostname=str(value("hostname", DEFAULT_LOCAL_HOSTNAME)),
            dhcp_start=str(value("dhcp_start", DEFAULT_DHCP_START)),
            dhcp_end=str(value("dhcp_end", DEFAULT_DHCP_END)),
            country_code=str(value("country_code", DEFAULT_WIFI_COUNTRY_CODE)),
            stack=str(value("stack", DEFAULT_NETWORK_STACK)).lower(),
            api_port=_as_int(value("api_port", 8000), "API port"),
            passphrase=str(raw_passphrase) if raw_passphrase else None,
            enabled=_as_bool(enabled_value, "enabled"),
            wpa3_transition=_as_bool(transition_value, "WPA3 transition"),
        )

    @classmethod
    def from_settings(cls, settings: object) -> "AccessPointConfig":
        """Build AP metadata from ``AppSettings`` without importing it."""

        return cls(
            interface=str(getattr(settings, "access_point_interface")),
            address=str(getattr(settings, "access_point_address")),
            prefix_length=int(getattr(settings, "access_point_prefix_length")),
            ssid=str(getattr(settings, "access_point_ssid")),
            connection_name=str(getattr(settings, "access_point_connection_name")),
            hostname=str(getattr(settings, "local_hostname")),
            country_code=str(getattr(settings, "wifi_country_code")),
            stack=str(getattr(settings, "network_stack")),
            api_port=int(getattr(settings, "port")),
            enabled=bool(getattr(settings, "network_enabled")),
        )


def _validate_hostname(hostname: str) -> None:
    normalized = hostname.rstrip(".")
    if len(normalized) < 1 or len(normalized) > 253:
        raise NetworkConfigurationError("local hostname must contain 1 to 253 characters")
    labels = normalized.split(".")
    if any(not _HOSTNAME_LABEL_RE.fullmatch(label) for label in labels):
        raise NetworkConfigurationError("local hostname contains an invalid DNS label")
    if normalized.lower().endswith(".local"):
        raise NetworkConfigurationError(
            ".local names require multicast DNS; use home.arpa with the supplied unicast DNS service"
        )


def _validate_passphrase(passphrase: str) -> None:
    if passphrase == PASSPHRASE_PLACEHOLDER:
        raise NetworkConfigurationError(
            "replace the example WPA passphrase before enabling the access point"
        )
    size = len(passphrase.encode("utf-8"))
    if not 8 <= size <= 63:
        raise NetworkConfigurationError("WPA passphrase must contain 8 to 63 UTF-8 bytes")
    if "\x00" in passphrase or "\n" in passphrase or "\r" in passphrase:
        raise NetworkConfigurationError("WPA passphrase cannot contain control line breaks")


def _as_bool(value: object, label: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise NetworkConfigurationError(f"{label} must be a boolean")


def _as_int(value: object, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise NetworkConfigurationError(f"{label} must be an integer") from exc
