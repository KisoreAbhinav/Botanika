// Canvas overlay that draws detector boxes and result labels exactly on the
// backend letterboxed preview rectangle using the published transform.

import { useEffect, useRef } from "react";
import { overlayAriaLabel, recognitionOverlayLabels } from "./scanOverlayState.js";

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
      aria-label={overlayAriaLabel(snapshot)}
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
  const accepted = Boolean(result && result.status === "accepted");
  const detections = Array.isArray(snapshot.detections) ? snapshot.detections : [];

  detections.forEach((detection, index) => {
    const selected = index === snapshot.selected_index;
    const [x1, y1, x2, y2] = toPreviewBox(detection.box, frame);
    const width = x2 - x1;
    const height = y2 - y1;
    if (width <= 0 || height <= 0) return;

    context.lineWidth = selected ? 2.4 : 1.6;
    context.strokeStyle = selected ? GREEN : OCHRE;
    context.strokeRect(x1, y1, width, height);

    // Live detector label above the box; the accepted backend result replaces
    // it with the requested AR-style Name/Confidence labels on the selected
    // box. Before acceptance, the detector box stays visible and trackable.
    let label = null;
    let subLabel = null;
    const recognizedLabels = selected && accepted ? recognitionOverlayLabels(result) : null;
    if (recognizedLabels) {
      label = recognizedLabels.top;
      subLabel = recognizedLabels.bottom;
    } else if (selected && result && result.status === "uncertain") {
      label = "Not confident";
    } else {
      label = formatDetectorLabel(detection.label);
    }

    context.font = "800 12px Inter, ui-sans-serif, system-ui, sans-serif";
    context.textBaseline = "bottom";
    if (label) {
      // Keep the top and bottom labels on the actual preview even when a box
      // touches an image edge. This matters on the fixed 500×330 kiosk frame.
      drawLabel(context, label, x1, Math.max(16, y1 - 4), selected ? GREEN : OCHRE);
    }
    if (subLabel) {
      context.textBaseline = "top";
      drawLabel(context, subLabel, x1, Math.min(canvas.height - 16, y2 + 4), GREEN);
    }
  });
}

function drawLabel(context, text, x, y, color) {
  const metrics = context.measureText(text);
  const padding = 3;
  const boxWidth = metrics.width + padding * 2;
  const boxX = Math.max(0, Math.min(x - padding, context.canvas.width - boxWidth));
  const textX = boxX + padding;
  const boxY = context.textBaseline === "top" ? y : y - 14;
  context.fillStyle = "rgba(39, 39, 36, 0.82)";
  context.fillRect(boxX, boxY, boxWidth, 16);
  context.fillStyle = SURFACE;
  context.fillText(text, textX, context.textBaseline === "top" ? y + 1 : y);
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
  const detections = Array.isArray(snapshot?.detections) ? snapshot.detections : [];
  if (!snapshot || !snapshot.frame || !onBoxTap || detections.length === 0) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  // Canvas renders at natural 500x330; map CSS position back to canvas pixels
  // in case the shell is scaled proportionally on a larger display.
  const x = ((event.clientX - rect.left) / rect.width) * canvas.width;
  const y = ((event.clientY - rect.top) / rect.height) * canvas.height;

  let bestIndex = null;
  let bestDistance = Infinity;
  detections.forEach((detection, index) => {
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
