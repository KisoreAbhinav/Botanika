export const MODES = Object.freeze({
  SOLO: "SOLO",
  NETWORKED_UNPAIRED: "NETWORKED_UNPAIRED",
  NETWORKED_PAIRED: "NETWORKED_PAIRED",
});

export function isNetworked(mode) {
  return mode === MODES.NETWORKED_UNPAIRED || mode === MODES.NETWORKED_PAIRED;
}

export function modeLabel(mode) {
  if (mode === MODES.NETWORKED_UNPAIRED) return "Networked · waiting to pair";
  if (mode === MODES.NETWORKED_PAIRED) return "Networked · paired";
  return "Solo";
}

/** Return the public tunnel snapshot regardless of its API nesting. */
export function getTunnelState(status) {
  return status?.tunnel || status?.network?.tunnel || null;
}

export function tunnelState(status) {
  const tunnel = getTunnelState(status);
  if (!tunnel?.enabled) return "disabled";
  return tunnel.state || "idle";
}

export function tunnelConnectUrl(status) {
  const tunnel = getTunnelState(status);
  return tunnel?.connect_url || tunnel?.url || null;
}

/**
 * The operator-only status includes a deep link with the one-time code.  A
 * remote status intentionally never does; this helper therefore has no way
 * to manufacture or expose a code on its own.
 */
export function pairingDeepLink(status) {
  return status?.pairing?.deep_link || null;
}

export function pairingCodeFromLocation(location = globalThis.location) {
  if (!location?.search) return null;
  try {
    const code = new URLSearchParams(location.search).get("pair");
    const normalized = code?.trim().toUpperCase();
    return normalized && /^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{6,16}$/.test(normalized)
      ? normalized
      : null;
  } catch {
    return null;
  }
}
