# ADR-0001: Secure Remote Browser Access

- **Status:** Accepted for architecture; hostname/domain choice remains open
- **Date:** 2026-09-01

## Context

The phone and Pi may be on different networks. The phone must use a normal web
browser with no installed client. Camera, geolocation, and modern browser model
runtimes need HTTPS. Residential networks may use NAT, changing public IPs, or
carrier-grade NAT, so direct port forwarding is not a consistent base.

## Decision

Use a named Cloudflare Tunnel from the Pi to a stable HTTPS hostname, protected
by Cloudflare Access owner authentication. Use a second short-lived Botanika
pairing ticket and lease for exclusive controller handoff. Bind the origin to
loopback and keep SOLO usable without the tunnel.

Tailscale Funnel is the domain-free prototype alternative. Quick tunnels and
raw router port forwarding are not production paths.

## Consequences

- A Cloudflare account and managed domain are production prerequisites.
- Networked scanning depends on both devices having internet connectivity.
- Edge login and in-app pairing solve different problems and both remain.
- Tunnel health becomes a supervised, observable Pi dependency.
- HTTPS/WSS allows the requested browser camera/GPS behavior across networks.
