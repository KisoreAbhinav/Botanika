import { useEffect, useRef, useState } from "react";
import { PREVIEW_URL, detectWeedsCamera, detectWeedsFrame, fetchWeedStatus } from "../../platform/api.js";
import { canRequestPosition, positionPayload } from "../networked/browserCapabilities.js";
import { containedImageRect } from "./weedGeometry.js";

const EXACT_POSITION_MESSAGE = "Exact location could not be found. Coordinate collection was skipped.";

export function WeedsPage({ capabilities, networked = false, notify, onLeaseLost }) {
  const fileRef = useRef(null);
  const [status, setStatus] = useState(capabilities?.weeds?.model || null);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const previewRef = useRef(null);
  const [previewSize, setPreviewSize] = useState({ width: 0, height: 0 });

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

  const manifest = status?.manifest || capabilities?.weeds?.model?.manifest || null;
  const available = Boolean(status?.available ?? capabilities?.weeds?.available);

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
  };

  const analyze = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      let response;
      if (networked) {
        if (!selected?.file) {
          setError("Choose one captured browser frame first.");
          return;
        }
        const position = await accuratePosition();
        response = await detectWeedsFrame(selected.file, position);
      } else {
        response = await detectWeedsCamera();
      }
      setResult(response);
      if (response.position_message === EXACT_POSITION_MESSAGE) notify?.(EXACT_POSITION_MESSAGE, "info");
    } catch (caught) {
      if (caught.status === 401) onLeaseLost?.();
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  const detections = result?.detections || [];
  const imageUrl = networked ? selected?.url : (result?.frame_data_url || PREVIEW_URL);
  const imageWidth = result?.image_width || 500;
  const imageHeight = result?.image_height || 330;
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
          {manifest ? `${manifest.crop_context || "Supported crop context"} · ${manifest.region || "Region not specified"}` : "Supported crop context and region are unavailable until the beta model is installed."}
        </p>
        {manifest?.labels?.length ? <div className="weed-labels">Supported classes: {manifest.labels.join(" · ")}</div> : null}

        {networked ? (
          <div className="weed-input-row">
            <button type="button" className="btn" onClick={() => fileRef.current?.click()}>Choose captured frame</button>
            <span className="weed-file-name">{selected?.file?.name || "No browser frame selected"}</span>
            <input ref={fileRef} type="file" accept="image/*" capture="environment" className="visually-hidden" onChange={chooseFile} />
          </div>
        ) : (
          <p className="weed-local-note">SOLO uses the current Pi camera frame. The regular scan owner keeps camera access single-owner.</p>
        )}

        <div ref={previewRef} className={`weed-preview ${imageUrl ? "has-image" : ""}`}>
          {imageUrl ? (
            <div className="weed-frame-layer" style={frameStyle}>
              <img src={imageUrl} alt={networked ? "Selected browser frame" : "Analyzed Pi camera frame"} />
              <div className="weed-boxes" aria-label="Weed detections">
                {detections.map((detection, index) => <DetectionBox key={`${detection.weed_class}-${index}`} detection={detection} width={imageWidth} height={imageHeight} />)}
              </div>
            </div>
          ) : <span>Select one still frame to analyze.</span>}
        </div>

        <div className="weed-actions">
          <button type="button" className="btn green" onClick={analyze} disabled={busy || !available || (networked && !selected?.file)}>
            {busy ? "Analyzing…" : networked ? "Analyze captured frame" : "Analyze Pi frame"}
          </button>
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
          <p className="weed-safety-note">This beta reports supported weed boxes only. It does not operate a drone, recommend chemicals, or write image files.</p>
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

async function accuratePosition(scope = globalThis) {
  if (!canRequestPosition(scope)) {
    return null;
  }
  return new Promise((resolve) => {
    scope.navigator.geolocation.getCurrentPosition(
      (position) => {
        const value = positionPayload(position);
        if (!value || value.accuracy_m > 100) {
          resolve(null);
          return;
        }
        resolve(value);
      },
      () => {
        resolve(null);
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 3500 },
    );
  });
}

function clamp(value) { return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0)); }
