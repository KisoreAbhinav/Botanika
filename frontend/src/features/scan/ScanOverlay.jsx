// Canvas overlay that draws detector boxes and result labels exactly on the
// backend letterboxed preview rectangle using the published transform.

import { useEffect, useRef } from "react";

const OCHRE = "#8a692e";
const GREEN = "#486b51";
const SURFACE = "#f7f4e9";

export function ScanOverlay({ snapshot, onBoxTap }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    drawScene(context, canvas, snapshot);
  }, [snapshot]);

  return (
    <canvas
      ref={canvasRef}
      className="camera-overlay"
      width={500}
      height={330}
      onClick={(event) => handleTap(event, snapshot, onBoxTap)}
      aria-label="Detection overlay. Tap a box to select it."
      role="img"
    />
  );
}

function drawScene(context, canvas, snapshot) {
  context.clearRect(0, 0, canvas.width, canvas.height);
  if (!snapshot) return;
  const frame = snapshot.frame;
  if (!frame) return;

  const classification = snapshot.classification;
  const result = classification ? classification.result : null;
  const accepted = result && result.status === "accepted";

  snapshot.detections.forEach((detection, index) => {
    const selected = index === snapshot.selected_index;
    const [x1, y1, x2, y2] = toPreviewBox(detection.box, frame);
    const width = x2 - x1;
    const height = y2 - y1;
    if (width <= 0 || height <= 0) return;

    context.lineWidth = selected ? 2.4 : 1.6;
    context.strokeStyle = selected ? GREEN : OCHRE;
    context.strokeRect(x1, y1, width, height);

    // Live detector label above the box; species name replaces it once an
    // accepted result exists, with calibrated confidence below the box.
    let label = null;
    let subLabel = null;
    if (selected && accepted) {
      label = result.common_name;
      subLabel = `confidence ${Math.round(result.confidence * 100)}%${result.is_stub ? " · DEMO DATA" : ""}`;
    } else if (selected && result && result.status === "uncertain") {
      label = "Not confident";
    } else {
      label = formatDetectorLabel(detection.label);
    }

    context.font = "800 12px Inter, ui-sans-serif, system-ui, sans-serif";
    context.textBaseline = "bottom";
    if (label) {
      drawLabel(context, label, x1, y1 - 4, selected ? GREEN : OCHRE);
    }
    if (subLabel) {
      context.textBaseline = "top";
      drawLabel(context, subLabel, x1, y2 + 4, GREEN);
    }
  });
}

function drawLabel(context, text, x, y, color) {
  const metrics = context.measureText(text);
  const padding = 3;
  const boxY = context.textBaseline === "top" ? y : y - 14;
  context.fillStyle = "rgba(39, 39, 36, 0.82)";
  context.fillRect(x - padding, boxY, metrics.width + padding * 2, 16);
  context.fillStyle = SURFACE;
  context.fillText(text, x, context.textBaseline === "top" ? y + 1 : y);
  context.strokeStyle = color;
  context.lineWidth = 1;
}

function toPreviewBox(box, frame) {
  return [
    box.x1 * frame.scale + frame.offset_x,
    box.y1 * frame.scale + frame.offset_y,
    box.x2 * frame.scale + frame.offset_x,
    box.y2 * frame.scale + frame.offset_y,
  ];
}

function handleTap(event, snapshot, onBoxTap) {
  if (!snapshot || !snapshot.frame || !onBoxTap || snapshot.detections.length === 0) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  // Canvas renders at natural 500x330; map CSS position back to canvas pixels
  // in case the shell is scaled proportionally on a larger display.
  const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
  const y = ((event.clientY - rect.top) / rect.height) * canvas.height;

  let bestIndex = null;
  let bestDistance = Infinity;
  snapshot.detections.forEach((detection, index) => {
    const [x1, y1, x2, y2] = toPreviewBox(detection.box, snapshot.frame);
    if (x >= x1 && x <= x2 && y >= y1 && y <= y2) {
      const distance =
        Math.pow((x - (x1 + x2) / 2) / Math.max(1, x2 - x1), 2) +
        Math.pow((y - (y1 + y2) / 2) / Math.max(1, y2 - y1), 2);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
    }
  });
  if (bestIndex !== null) onBoxTap(bestIndex);
}

function formatDetectorLabel(label) {
  if (!label) return "";
  const spaced = label.replace(/-/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
