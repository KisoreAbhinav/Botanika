"""Private AP and optional Cloudflare Quick Tunnel transport boundaries.

The network package is deliberately separate from the botanical services.  It
only owns the transport boundary; camera, inference, knowledge, and library
requests continue to use the same FastAPI application and runtime objects.
"""

from .config import AccessPointConfig, NetworkConfigurationError, PASSPHRASE_PLACEHOLDER
from .manager import AccessPointError, AccessPointManager, PlannedCommand
from .service import NetworkService
from .status import AccessPointStatus, CommandResult, NetworkStatusProbe, run_command
from .tunnel import (
    CloudflareTunnelService,
    CloudflaredTunnelService,
    QuickTunnelService,
    QuickTunnelStatus,
    TunnelStatus,
    extract_cloudflared_url,
    extract_quick_tunnel_url,
    extract_tunnel_url,
    parse_quick_tunnel_url,
    parse_tunnel_url,
)

__all__ = [
    "AccessPointConfig",
    "AccessPointError",
    "AccessPointManager",
    "AccessPointStatus",
    "CommandResult",
    "NetworkConfigurationError",
    "PASSPHRASE_PLACEHOLDER",
    "NetworkService",
    "NetworkStatusProbe",
    "PlannedCommand",
    "CloudflareTunnelService",
    "CloudflaredTunnelService",
    "QuickTunnelService",
    "QuickTunnelStatus",
    "TunnelStatus",
    "extract_cloudflared_url",
    "extract_quick_tunnel_url",
    "extract_tunnel_url",
    "parse_quick_tunnel_url",
    "parse_tunnel_url",
    "run_command",
]
