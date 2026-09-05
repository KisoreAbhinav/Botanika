// Botanika local API client. Every mode uses the same Pi backend. A paired
// controller token is attached to controller-only operations; live browser
// video is never sent here.

const BASE = "/api/v1";
const TOKEN_KEY = "botanika.controller.token";

export function getControllerToken() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setControllerToken(token) {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* Private browsing/storage-disabled browsers keep the in-memory flow alive. */
  }
}

export function clearControllerToken() {
  setControllerToken(null);
}

async function request(path, options = {}) {
  let response;
  const headers = new Headers(options.headers || {});
  const token = getControllerToken();
  if (token && !headers.has("X-Botanika-Controller-Token")) {
    headers.set("X-Botanika-Controller-Token", token);
  }
  try {
    response = await fetch(BASE + path, { ...options, headers });
  } catch {
    throw new ApiError("The local service is not reachable.", 0);
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const problem = await response.json();
      if (problem && problem.detail) detail = problem.detail;
    } catch {
      /* keep default detail */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json();
}

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function fetchHealth() {
  return request("/health/live");
}

export function fetchReady() {
  return request("/health/ready");
}

export function fetchCapabilities() {
  return request("/capabilities");
}

export function fetchNetworkStatus() {
  return request("/network/status");
}

export function fetchModeStatus() {
  return request("/mode/status");
}

export function toggleMode() {
  return request("/mode/toggle", { method: "POST" });
}

export function returnToSolo() {
  return request("/mode/solo", { method: "POST" });
}

export function retryTunnel() {
  return request("/mode/tunnel/retry", { method: "POST" });
}

export function takeoverController() {
  return request("/mode/takeover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_name: "Pi operator", client_id: "pi-console" }),
  });
}

export function pairController(code, deviceName, clientId) {
  return request("/mode/pair", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, device_name: deviceName, client_id: clientId }),
  });
}

export function disconnectController() {
  return request("/mode/disconnect", { method: "POST" });
}

export function heartbeatController() {
  return request("/mode/heartbeat", { method: "POST" });
}

export function fetchScanState() {
  return request("/scan/state");
}

export function fetchLibrary() {
  return request("/library/records");
}

export function fetchLibraryMap() {
  return request("/library/map");
}

export function fetchRegionalLibrary() {
  return request("/library/region");
}

export function fetchLibrarySpecies(speciesId) {
  return request(`/library/species/${encodeURIComponent(speciesId)}`);
}

export function fetchLibraryProgress() {
  return request("/library/progress");
}

export function fetchKnowledgeStatus() {
  return request("/knowledge/status");
}

export function fetchVoiceStatus() {
  return request("/voice/status");
}

export function fetchWeedStatus() {
  return request("/weeds/status");
}

export function fetchWeedRuns(limit = 100) {
  const bounded = Math.max(1, Math.min(500, Number(limit) || 100));
  return request(`/weeds/runs?limit=${bounded}`);
}

export async function downloadWeedExport() {
  const headers = new Headers();
  const token = getControllerToken();
  if (token) headers.set("X-Botanika-Controller-Token", token);
  let response;
  try {
    response = await fetch(`${BASE}/weeds/export`, { headers });
  } catch {
    throw new ApiError("The local service is not reachable.", 0);
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const problem = await response.json();
      if (problem?.detail) detail = problem.detail;
    } catch {
      /* keep default detail */
    }
    throw new ApiError(detail, response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "botanika-weed-observations.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function listenBotanika() {
  return request("/voice/listen", { method: "POST" });
}

export function speakBotanika(text) {
  return request("/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function interruptVoice() {
  return request("/voice/interrupt", { method: "POST" });
}

export async function detectWeedsCamera() {
  return request("/weeds/camera", { method: "POST" });
}

export async function detectWeedsFrame(file, position = null) {
  const form = new FormData();
  form.append("file", file, file.name || "weed-frame.jpg");
  if (position) form.append("position_json", JSON.stringify(position));
  return request("/weeds/controller/frame", { method: "POST", body: form });
}

export function fetchSpecies(query = "") {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  return request(`/species${suffix}`);
}

export function askBotanika(question, contextSpeciesId = null, speak = false) {
  return request("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, context_species_id: contextSpeciesId, speak }),
  });
}

export function saveToLibrary({ note = null, position = null, requestId = null, cropHash = null } = {}) {
  const hasBody = note !== null || position !== null || requestId !== null || cropHash !== null;
  return request("/library/records", {
    method: "POST",
    ...(hasBody
      ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note, position, request_id: requestId, crop_hash: cropHash }),
        }
      : {}),
  });
}

export function deleteLibraryRecord(recordId) {
  return request(`/library/records/${encodeURIComponent(recordId)}?confirmed=true`, {
    method: "DELETE",
  });
}

export function updateLibraryNote(recordId, note) {
  return request(`/library/records/${encodeURIComponent(recordId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
}

export function postScanCommand(path) {
  return request(path, { method: "POST" });
}

export function selectBox(index) {
  return request("/scan/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index }),
  });
}

export function manualCapture() {
  return postScanCommand("/scan/manual-capture");
}

export function retake() {
  return postScanCommand("/scan/retake");
}

export function cancelScan() {
  return postScanCommand("/scan/cancel");
}

export function fallbackCapture(index) {
  return request("/scan/fallback/capture", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index }),
  });
}

export function clearFallback() {
  return postScanCommand("/scan/fallback/clear");
}

export async function uploadFallbackImage(file) {
  const form = new FormData();
  form.append("file", file, file.name || "local-image.jpg");
  return request("/scan/fallback", { method: "POST", body: form });
}

export async function classifyControllerCrop({
  blob,
  hash,
  width,
  height,
  requestId,
}) {
  const form = new FormData();
  form.append("file", blob, "botanika-crop.png");
  if (hash) form.append("crop_hash", hash);
  form.append("width", String(width));
  form.append("height", String(height));
  form.append("client_request_id", requestId);
  return request("/mode/controller/crop", { method: "POST", body: form });
}

export const PREVIEW_URL = `${BASE}/scan/preview.mjpg`;

/**
 * Subscribe to the backend snapshot event channel. Returns a cleanup fn.
 * Events are authoritative: the latest snapshot replaces prior UI state.
 */
export function subscribeToSnapshots(onSnapshot, onError) {
  const source = new EventSource(`${BASE}/scan/events`);
  source.addEventListener("snapshot", (event) => {
    try {
      onSnapshot(JSON.parse(event.data));
    } catch {
      /* ignore malformed event */
    }
  });
  source.onerror = () => {
    if (onError) onError();
  };
  return () => source.close();
}
