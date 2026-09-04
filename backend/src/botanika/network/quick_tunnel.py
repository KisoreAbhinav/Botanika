"""Compatibility import surface for the optional Cloudflare Quick Tunnel."""

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
]
