"""Application-facing transport status and lifecycle service."""

from .config import AccessPointConfig
from .status import AccessPointStatus, NetworkStatusProbe
from .tunnel import QuickTunnelService, QuickTunnelStatus


class NetworkService:
    """Expose AP status and optionally own a Cloudflare Quick Tunnel.

    The AP remains a separate, optional local transport.  A configured tunnel
    does not make AP probes or AP services mandatory; both can be unavailable
    while the loopback API is still reachable through cloudflared.
    """

    def __init__(
        self,
        settings: object,
        *,
        probe: NetworkStatusProbe | None = None,
        tunnel: QuickTunnelService | None = None,
    ) -> None:
        self.settings = settings
        config = AccessPointConfig.from_settings(settings)
        self.config = config
        self.probe = probe or NetworkStatusProbe(config)
        self.tunnel = tunnel or QuickTunnelService(settings)

    def status(self) -> AccessPointStatus:
        return self.probe.status()

    def tunnel_status(self) -> QuickTunnelStatus:
        return self.tunnel.status()

    def start_tunnel(self, port: int | None = None) -> QuickTunnelStatus:
        return self.tunnel.start(port=port)

    def retry_tunnel(self) -> QuickTunnelStatus:
        return self.tunnel.retry()

    def stop_tunnel(self) -> QuickTunnelStatus:
        return self.tunnel.stop()

    def to_dict(self) -> dict[str, object]:
        status = self.status()
        status_data = status.to_dict()
        tunnel_data = self.tunnel.to_dict()
        tunnel_ready = tunnel_data.get("state") == "ready"
        # Keep the historical AP snapshot nested under ``status`` while the
        # top-level summary answers whether either configured transport works.
        aggregate = dict(status_data)
        if tunnel_data.get("enabled"):
            aggregate.update(
                {
                    "enabled": bool(status.enabled or tunnel_data.get("enabled")),
                    "available": bool(status.available or tunnel_ready),
                    "state": "ready" if tunnel_ready else tunnel_data.get("state"),
                    "transport": (
                        "cloudflare-quick-tunnel"
                        if tunnel_ready
                        else status.transport
                    ),
                    "detail": (
                        str(tunnel_data.get("detail"))
                        if not status.available or tunnel_ready
                        else status.detail
                    ),
                    "connect_url": tunnel_data.get("connect_url"),
                }
            )
        return {
            # Keep the compact status at the top level for shell/curl users;
            # the nested copy is convenient for capability consumers that
            # already group measured state under ``model.status``.
            **aggregate,
            "status": status_data,
            "configuration": self.config.to_dict(),
            "tunnel": tunnel_data,
        }

__all__ = ["NetworkService"]
