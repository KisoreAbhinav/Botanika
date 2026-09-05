import { useEffect, useRef, useState } from "react";
import {
  PREVIEW_URL,
  detectWeedsCamera,
  detectWeedsFrame,
  downloadWeedExport,
  fetchWeedStatus,
} from "../../platform/api.js";
import {
  cameraAccessMode,
  canRequestPosition,
  positionPayload,
} from "../networked/browserCapabilities.js";
import { containedImageRect } from "./weedGeometry.js";
import { createLocationSampler } from "./weedLocation.js";
import { CONTROL_SHORTCUTS } from "../../app/hotkeys.js";

const EXACT_POSITION_MESSAGE = "Exact location could not be found. Coordinate collection was skipped.";
const INDIA_WEED_CONTEXT = "India field context · broadleaf weed cue · confirm on site before acting.";
// Weed frames are samples, not a video upload. Keep the request rate bounded
// and let a slow Pi finish before another sample is sent.
const LIVE_SAMPLE_INTERVAL_MS = 1200;

export function WeedsPage({ capabilities, networked = false, notify, onLeaseLost }) {
  const fileRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const liveSerialRef = useRef(0);
  const liveRequestRef = useRef(false);
  const locationSamplerRef = useRef(null);
  const locationNoticeRef = useRef(false);
  if (!locationSamplerRef.current) {
    locationSamplerRef.current = createLocationSampler(() => accuratePosition());
  }
  const [status, setStatus] = useState(capabilities?.weeds?.model || null);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [error, setError] = useState(null);
  const [cameraState, setCameraState] = useState(networked ? "starting" : "pi-camera");
  const [livePaused, setLivePaused] = useState(false);
  const [liveSize, setLiveSize] = useState({ width: 640, height: 480 });
  const previewRef = useRef(null);
  const [previewSize, setPreviewSize] = useState({ width: 0, height: 0 });
  const manifest = status?.manifest || capabilities?.weeds?.model?.manifest || null;
  const available = Boolean(status?.available ?? capabilities?.weeds?.available);

  useEffect(() => {
    let active = true;
    fetchWeedStatus().then((value) => { if (active) setStatus(value); }).catch(() => {});
    return () => { active = false; };
  }, []);

  useEffect(() => () => {
    if (selected?.url) URL.revokeObjectURL(selected.url);
  }, [selected?.url]);

  useEffect(() => {
    const element = previewRef.current;
    if (!element) return undefined;
    const update = () => setPreviewSize({ width: element.clientWidth, height: element.clientHeight });
    update();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", update);
      return () => window.removeEventListener("resize", update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // A paired browser owns its camera. The backend receives only bounded JPEG
  // samples from this stream; the MediaStream itself never leaves the phone.
  useEffect(() => {
    if (!networked) {
      setCameraState("pi-camera");
      return undefined;
    }
    if (cameraAccessMode(window) !== "stream") {
      setCameraState("capture-input");
      return undefined;
    }
    let cancelled = false;
    navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    }).then((stream) => {
      if (cancelled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      setCameraState("ready");
      if (videoRef.current) videoRef.current.srcObject = stream;
    }).catch(() => {
      if (!cancelled) setCameraState("denied");
    });
    return () => {
      cancelled = true;
      liveSerialRef.current += 1;
      streamRef.current?.getTracks?.().forEach((track) => track.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [networked]);

  // The video element is intentionally conditional when a still fallback is
  // selected. Reattach the live stream when the user returns to the camera.
  useEffect(() => {
    if (videoRef.current && streamRef.current) videoRef.current.srcObject = streamRef.current;
  }, [selected, cameraState]);

  // Start one bounded sampler once metadata is available. The in-flight guard
  // prevents overlapping Pi inference requests on a slow or offline tunnel.
  useEffect(() => {
    if (!networked || !available || cameraState !== "ready" || livePaused || selected) return undefined;
    let cancelled = false;
    const sample = async () => {
      if (cancelled || liveRequestRef.current) return;
      const video = videoRef.current;
      if (!video || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return;
      liveRequestRef.current = true;
      const serial = ++liveSerialRef.current;
      try {
        const canvas = canvasRef.current || document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) return;
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const blob = await canvasToBlob(canvas);
        if (!blob || cancelled) return;
        // A location lookup is itself bounded and cached between samples. A
        // stale/inaccurate/denied fix is passed as null and never persisted.
        const position = await locationSamplerRef.current();
        const response = await detectWeedsFrame(blob, position);
        if (cancelled || serial !== liveSerialRef.current) return;
        setResult(response);
        setLiveSize({
          width: Number(response.image_width) || canvas.width,
          height: Number(response.image_height) || canvas.height,
        });
        if (response.position_message === EXACT_POSITION_MESSAGE && !locationNoticeRef.current) {
          locationNoticeRef.current = true;
          notify?.(EXACT_POSITION_MESSAGE, "info");
        } else if (response.position_available) {
          locationNoticeRef.current = false;
        }
      } catch (caught) {
        if (cancelled || serial !== liveSerialRef.current) return;
        if (caught.status === 401) onLeaseLost?.();
        setError(caught.message || "The live weed sample could not be analyzed.");
      } finally {
        liveRequestRef.current = false;
      }
    };
    void sample();
    const timer = window.setInterval(() => { void sample(); }, LIVE_SAMPLE_INTERVAL_MS);
    return () => {
      cancelled = true;
      liveSerialRef.current += 1;
      window.clearInterval(timer);
    };
  }, [available, cameraState, livePaused, networked, notify, onLeaseLost, selected]);

  const chooseFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("Choose an image frame.");
      return;
    }
    const url = URL.createObjectURL(file);
    setSelected({ file, url });
    setResult(null);
    setError(null);
    setLivePaused(true);
  };

  const returnToLive = () => {
    setSelected(null);
    setResult(null);
    setError(null);
    setLivePaused(false);
  };

  const exportCoordinates = async () => {
    if (exportBusy) return;
    setExportBusy(true);
    setError(null);
    try {
      await downloadWeedExport();
      notify?.("Weed coordinates exported.", "success");
    } catch (caught) {
      if (caught.status === 401) onLeaseLost?.();
      setError(caught.message || "The weed coordinate export could not be downloaded.");
    } finally {
      setExportBusy(false);
    }
  };

  const analyze = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      let response;
      if (networked) {
        if (!selected?.file) {
          setError("The live camera is already analyzing samples.");
          return;
        }
        const position = await accuratePosition();
        response = await detectWeedsFrame(selected.file, position);
      } else {
        response = await detectWeedsCamera();
      }
      setResult(response);
      if (response.position_message === EXACT_POSITION_MESSAGE && !locationNoticeRef.current) {
        locationNoticeRef.current = true;
        notify?.(EXACT_POSITION_MESSAGE, "info");
      } else if (response.position_available) {
        locationNoticeRef.current = false;
      }
    } catch (caught) {
      if (caught.status === 401) onLeaseLost?.();
      setError(caught.message || "The weed frame could not be analyzed.");
    } finally {
      setBusy(false);
    }
  };

  const detections = result?.detections || [];
  const liveCamera = networked && cameraState === "ready" && !selected;
  const imageUrl = networked ? selected?.url : (result?.frame_data_url || PREVIEW_URL);
  const imageWidth = result?.image_width || (liveCamera ? liveSize.width : 500);
  const imageHeight = result?.image_height || (liveCamera ? liveSize.height : 330);
  const frameWidth = previewSize.width || 1;
  const frameHeight = previewSize.height || 1;
  const contained = containedImageRect(frameWidth, frameHeight, imageWidth, imageHeight);
  const frameStyle = contained.width > 0
    ? { width: `${contained.width}px`, height: `${contained.height}px` }
    : undefined;

  return (
    <div className="weed-page">
      <section className="weed-main-card">
        <div className="weed-head">
          <div>
            <div className="eyebrow">Independent detector · Beta</div>
            <h1>Weed detection</h1>
          </div>
          <span className={`status-pill ${available ? "ready" : "degraded"}`}>{available ? "Ready" : "Unavailable"}</span>
        </div>
        <p className="weed-context">
          {INDIA_WEED_CONTEXT}
        </p>
        {manifest?.labels?.length ? <div className="weed-labels">Supported classes: {manifest.labels.join(" · ")}</div> : null}

        {networked ? (
          <div className="weed-input-row">
            <button
              type="button"
              className="btn"
              onClick={() => fileRef.current?.click()}
              data-hotkey={CONTROL_SHORTCUTS.chooseWeedFrame}
              aria-keyshortcuts={CONTROL_SHORTCUTS.chooseWeedFrame}
            >
              {liveCamera ? "Use a photo instead" : "Choose captured frame"} <kbd aria-hidden="true">L</kbd>
            </button>
            <span className="weed-file-name">{selected?.file?.name || (liveCamera ? "Live phone camera sampling" : "No browser frame selected")}</span>
            <input ref={fileRef} type="file" accept="image/*" capture="environment" className="visually-hidden" onChange={chooseFile} />
          </div>
        ) : (
          <p className="weed-local-note">SOLO uses the current Pi camera frame. The regular scan owner keeps camera access single-owner.</p>
        )}

        <div ref={previewRef} className={`weed-preview ${imageUrl || liveCamera ? "has-image" : ""}`}>
          {liveCamera ? (
            <div className="weed-frame-layer weed-live-layer" style={frameStyle}>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                aria-label="Live phone camera for weed detection"
                onLoadedMetadata={(event) => setLiveSize({ width: event.currentTarget.videoWidth || 640, height: event.currentTarget.videoHeight || 480 })}
              />
              <div className="weed-boxes" aria-label="Live weed detections">
                {detections.map((detection, index) => <DetectionBox key={`${detection.weed_class}-${index}`} detection={detection} width={imageWidth} height={imageHeight} />)}
              </div>
              <div className="weed-live-badge" role="status">
                {livePaused ? "Live scan paused" : result ? "Live · sampled frame" : "Live · waiting for sample"}
              </div>
            </div>
          ) : imageUrl ? (
            <div className="weed-frame-layer" style={frameStyle}>
              <img src={imageUrl} alt={networked ? "Selected browser frame" : "Analyzed Pi camera frame"} />
              <div className="weed-boxes" aria-label="Weed detections">
                {detections.map((detection, index) => <DetectionBox key={`${detection.weed_class}-${index}`} detection={detection} width={imageWidth} height={imageHeight} />)}
              </div>
            </div>
          ) : networked && cameraState === "starting" ? (
            <span>Starting the phone camera…</span>
          ) : networked && cameraState === "denied" ? (
            <span>Camera permission was denied. Choose a captured frame below.</span>
          ) : <span>Select one still frame to analyze.</span>}
        </div>

        <div className="weed-actions">
          {liveCamera ? (
            <button
              type="button"
              className="btn green"
              onClick={() => setLivePaused((value) => !value)}
              disabled={!available}
              data-hotkey={CONTROL_SHORTCUTS.pauseWeedScan}
              aria-keyshortcuts={CONTROL_SHORTCUTS.pauseWeedScan}
            >
              {livePaused ? "Resume live scan" : "Pause live scan"} <kbd aria-hidden="true">P</kbd>
            </button>
          ) : (
            <button
              type="button"
              className="btn green"
              onClick={analyze}
              disabled={busy || !available || (networked && !selected?.file)}
              data-hotkey={CONTROL_SHORTCUTS.analyzeWeedFrame}
              aria-keyshortcuts={CONTROL_SHORTCUTS.analyzeWeedFrame}
            >
              {busy ? "Analyzing…" : networked ? "Analyze captured frame" : "Analyze Pi frame"} <kbd aria-hidden="true">W</kbd>
            </button>
          )}
          {selected && (
            <button
              type="button"
              className="btn quiet"
              onClick={returnToLive}
              data-hotkey={CONTROL_SHORTCUTS.returnLiveCamera}
              aria-keyshortcuts={CONTROL_SHORTCUTS.returnLiveCamera}
            >
              Return to live camera <kbd aria-hidden="true">R</kbd>
            </button>
          )}
          {result && <span className="weed-result-count">{detections.length} box{detections.length === 1 ? "" : "es"}</span>}
        </div>
        {error && <p className="chat-error">{error}</p>}
        {result?.detail && <p className="weed-detail">{result.detail}</p>}
        {result?.position_message && <p className="weed-position">{result.position_message}</p>}
      </section>

      <aside className="weed-side-card">
        <div className="side-header">Beta boundary</div>
        <div className="side-body">
          <div className="metric-row"><dt>Model</dt><dd>{manifest?.version || "Unavailable"}</dd></div>
          <div className="metric-row"><dt>Images saved</dt><dd>Never</dd></div>
          <div className="metric-row"><dt>Coordinates</dt><dd>{result?.position_available ? "Recorded" : "Skipped unless accurate"}</dd></div>
          <p className="weed-safety-note">Sampled frames are transient and discarded. Only positive supported weed metadata and a validated device coordinate are persisted; no image or chemical/drone action is performed.</p>
          <button
            className="btn quiet weed-export-link"
            type="button"
            onClick={exportCoordinates}
            disabled={exportBusy}
            data-hotkey={CONTROL_SHORTCUTS.exportWeedCoordinates}
            aria-keyshortcuts={CONTROL_SHORTCUTS.exportWeedCoordinates}
          >
            {exportBusy ? "Exporting…" : "Export coordinates"} <kbd aria-hidden="true">E</kbd>
          </button>
          {detections.length > 0 && (
            <div className="weed-detection-list">
              {detections.map((detection, index) => (
                <div className="weed-detection-row" key={`${detection.weed_class}-${index}`}>
                  <strong>{detection.weed_class}</strong>
                  <span>{Math.round(Number(detection.confidence || 0) * 100)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
      <canvas ref={canvasRef} className="visually-hidden" aria-hidden="true" />
    </div>
  );
}

function DetectionBox({ detection, width, height }) {
  const box = detection.box || {};
  const left = clamp((Number(box.x1) / width) * 100);
  const top = clamp((Number(box.y1) / height) * 100);
  const boxWidth = clamp(((Number(box.x2) - Number(box.x1)) / width) * 100);
  const boxHeight = clamp(((Number(box.y2) - Number(box.y1)) / height) * 100);
  return (
    <div className="weed-box" style={{ left: `${left}%`, top: `${top}%`, width: `${boxWidth}%`, height: `${boxHeight}%` }}>
      <span>{detection.weed_class} · {Math.round(Number(detection.confidence || 0) * 100)}%</span>
    </div>
  );
}

function canvasToBlob(canvas) {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.78);
  });
}

async function accuratePosition(scope = globalThis) {
  if (!canRequestPosition(scope)) return null;
  return new Promise((resolve) => {
    scope.navigator.geolocation.getCurrentPosition(
      (position) => {
        const value = positionPayload(position);
        resolve(value && value.accuracy_m <= 100 ? value : null);
      },
      () => resolve(null),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 3500 },
    );
  });
}

function clamp(value) { return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0)); }
