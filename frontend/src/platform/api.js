// Botanika Phase 6 local API client. The kiosk talks only to its own loopback
// origin; there is no other backend.

const BASE = "/api/v1";

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(BASE + path, options);
  } catch {
    throw new Error("The local service is not reachable.");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const problem = await response.json();
      if (problem && problem.detail) detail = problem.detail;
    } catch {
      /* keep default detail */
    }
    throw new Error(detail);
  }
  return response.json();
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

export function fetchScanState() {
  return request("/scan/state");
}

export function fetchLibrary() {
  return request("/library/records");
}

export function fetchSpecies(query = "") {
  const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
  return request(`/species${suffix}`);
}

export function askBotanika(question, contextSpeciesId = null) {
  return request("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, context_species_id: contextSpeciesId }),
  });
}

export function saveToLibrary() {
  return request("/library/records", { method: "POST" });
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
