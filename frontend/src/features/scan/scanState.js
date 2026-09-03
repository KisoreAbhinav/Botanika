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
