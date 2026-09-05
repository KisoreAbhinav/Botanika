export function deriveScanPanelState(snapshot) {
  if (snapshot && snapshot.processing) return "processing";
  const result = snapshot && snapshot.classification ? snapshot.classification.result : null;
  if (!result) return "guidance";
  if (result.status === "accepted") return "result";
  if (result.status === "uncertain") return "uncertain";
  return "error";
}

export function selectedFallbackIndex(snapshot) {
  if (!snapshot || snapshot.mode !== "fallback") return 0;
  return Number.isInteger(snapshot.selected_index) ? snapshot.selected_index : 0;
}

export function shouldManualCaptureFromKey(event, snapshot) {
  const targetBlocked = event?.target?.matches?.(
    "input, textarea, select, button, [contenteditable=\"true\"]",
  );
  return Boolean(
    event
    && event.code === "Space"
    && !event.repeat
    && !event.defaultPrevented
    && !event.ctrlKey
    && !event.altKey
    && !event.metaKey
    && !targetBlocked
    && !(snapshot && snapshot.classification)
    && (snapshot ? snapshot.camera_available : true)
    && (!snapshot || snapshot.mode === "camera")
    && !(snapshot && snapshot.processing),
  );
}
