/**
 * Text used by the canvas/ARIA scan overlay once the Pi accepts a result.
 * Keeping this pure makes the live-vs-recognized contract independently
 * testable without requiring a browser canvas implementation.
 */

export function recognitionOverlayLabels(result) {
  if (!result || result.status !== "accepted") return null;
  return {
    top: `Name- ${result.common_name || "Unknown"}`,
    bottom: `Confidence- ${formatConfidence(result.confidence)}${result.is_stub ? " · DEMO DATA" : ""}`,
  };
}

export function overlayAriaLabel(snapshot) {
  const labels = recognitionOverlayLabels(snapshot?.classification?.result);
  if (labels) {
    return `Detection overlay. ${labels.top}. ${labels.bottom}. Tap a box to select it.`;
  }
  const count = Array.isArray(snapshot?.detections) ? snapshot.detections.length : 0;
  return `Detection overlay with ${count} live box${count === 1 ? "" : "es"}. Tap a box to select it.`;
}

function formatConfidence(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value * 100)}%`
    : "–";
}
