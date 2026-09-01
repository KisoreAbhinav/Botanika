const state = {
  file: null,
  requestId: null,
  clientHash: null,
  dimensions: null,
  previewUrl: null,
  controller: null,
  cancelled: false,
  retryCount: 0,
  socket: null,
  reconnectTimer: null,
  reconnectDelay: 1000,
};

const $ = (id) => document.getElementById(id);
const input = $("image-input");
const previewPanel = $("preview-panel");
const preview = $("preview");
const uploadButton = $("upload-button");
const cancelButton = $("cancel-button");
const uploadState = $("upload-state");
const receipt = $("receipt");

function setConnection(online, message) {
  $("status-dot").classList.toggle("online", online);
  $("status-dot").classList.toggle("offline", !online);
  $("connection-state").textContent = message;
}

function socketUrl() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws/status`;
}

function connectStatus() {
  if (state.socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(state.socket.readyState)) return;
  const socket = new WebSocket(socketUrl());
  state.socket = socket;
  socket.addEventListener("open", () => {
    state.reconnectDelay = 1000;
    setConnection(true, "Connected to Botanika status channel.");
  });
  socket.addEventListener("message", (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.type === "connected") {
        $("environment").textContent = message.environment || "Pi";
        $("build-label").textContent = `Build ${message.service || "Botanika"}`;
      }
    } catch {
      // A malformed status event cannot affect the upload state.
    }
  });
  socket.addEventListener("close", () => {
    if (state.socket !== socket) return;
    setConnection(false, "Pi status channel disconnected. Retrying…");
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = setTimeout(connectStatus, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 2, 30000);
  });
  socket.addEventListener("error", () => socket.close());
}

async function sha256(file) {
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function imageDimensions(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => { URL.revokeObjectURL(url); resolve({ width: image.naturalWidth, height: image.naturalHeight }); };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error("The selected file is not a decodable image.")); };
    image.src = url;
  });
}

input.addEventListener("change", async () => {
  const file = input.files?.[0];
  if (!file) return;
  // Selecting a new crop supersedes any in-flight request for the old one.
  state.controller?.abort();
  state.controller = null;
  state.file = file;
  state.requestId = crypto.randomUUID();
  state.retryCount = 0;
  state.cancelled = false;
  state.dimensions = null;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;
  previewPanel.hidden = true;
  receipt.hidden = true;
  uploadState.textContent = "Checking crop…";
  uploadButton.disabled = true;
  if (file.size > 5 * 1024 * 1024) {
    state.file = null;
    uploadState.textContent = "The crop is larger than the 5 MiB image limit.";
    return;
  }
  try {
    const [dimensions, hash] = await Promise.all([imageDimensions(file), sha256(file)]);
    state.clientHash = hash;
    state.dimensions = dimensions;
    state.previewUrl = URL.createObjectURL(file);
    preview.src = state.previewUrl;
    $("file-name").textContent = file.name || "selected crop";
    $("file-details").textContent = `${dimensions.width} × ${dimensions.height} px · ${(file.size / 1024).toFixed(1)} KB · ${file.type || "unknown MIME"}`;
    $("client-hash").textContent = `Phone SHA-256: ${hash}`;
    previewPanel.hidden = false;
    uploadButton.disabled = false;
    uploadState.textContent = "Crop ready. The complete camera frame is not part of this request.";
  } catch (error) {
    state.file = null;
    uploadState.textContent = error.message;
  }
});

cancelButton.addEventListener("click", () => {
  state.cancelled = true;
  state.controller?.abort();
  state.controller = null;
  state.file = null;
  state.requestId = null;
  state.dimensions = null;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;
  input.value = "";
  previewPanel.hidden = true;
  uploadButton.disabled = true;
  cancelButton.hidden = true;
  uploadState.textContent = "Retained crop discarded on the phone.";
});

async function csrfToken(signal) {
  const response = await fetch("/api/v1/security/csrf", { credentials: "same-origin", signal });
  if (!response.ok) throw new Error("Could not establish the upload security token.");
  const body = await response.json();
  return body.token;
}

uploadButton.addEventListener("click", async () => {
  if (!state.file || !state.requestId) return;
  const requestId = state.requestId;
  const controller = new AbortController();
  let timedOut = false;
  state.controller = controller;
  state.cancelled = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 30000);
  uploadButton.disabled = true;
  cancelButton.hidden = false;
  receipt.hidden = true;
  uploadState.textContent = state.retryCount ? "Retrying the same crop…" : "Uploading crop securely…";
  try {
    const token = await csrfToken(controller.signal);
    const form = new FormData();
    form.append("image", state.file, `crop.${state.file.type === "image/webp" ? "webp" : "jpg"}`);
    form.append("metadata", JSON.stringify({
      capture_event_id: requestId,
      captured_at: new Date().toISOString(),
      client_type: "phone",
      detector: "connectivity-placeholder",
      source_frame_dimensions: [state.dimensions.width, state.dimensions.height],
      crop_dimensions: [state.dimensions.width, state.dimensions.height],
      orientation_applied: "none",
      quality_gate: "not-applicable",
    }));
    const response = await fetch("/api/v1/connectivity/receipt", {
      method: "POST",
      body: form,
      credentials: "same-origin",
      headers: { "Idempotency-Key": requestId, "X-CSRF-Token": token },
      signal: controller.signal,
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail?.message || body.detail?.error || "The Pi rejected the crop.");
    receipt.textContent = JSON.stringify(body, null, 2);
    receipt.hidden = false;
    uploadState.textContent = body.content_hash === state.clientHash
      ? "Receipt verified: the Pi received the same bytes and discarded the crop."
      : "Pi receipt received; compare the displayed hashes before continuing.";
    if (state.requestId === requestId) {
      state.controller = null;
      cancelButton.hidden = true;
    }
  } catch (error) {
    // A replaced/cancelled request must not overwrite the newer UI state.
    if (state.requestId !== requestId) return;
    state.controller = null;
    if (error.name === "AbortError") {
      if (state.cancelled) return;
      state.retryCount += 1;
      uploadState.textContent = timedOut
        ? "Upload timed out. The crop is still on this phone; retry or cancel."
        : "Upload cancelled. The crop is still on this phone; retry or cancel.";
      uploadButton.disabled = state.retryCount > 1;
      cancelButton.hidden = false;
      return;
    }
    state.retryCount += 1;
    uploadState.textContent = `Upload paused: ${error.message} Keep this crop and retry, or cancel it.`;
    uploadButton.disabled = state.retryCount > 1;
    cancelButton.hidden = false;
  } finally {
    clearTimeout(timeoutId);
  }
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
connectStatus();
