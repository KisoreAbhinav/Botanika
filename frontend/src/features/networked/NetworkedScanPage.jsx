import { useEffect, useRef, useState } from "react";
import { classifyControllerCrop, saveToLibrary } from "../../platform/api.js";
import { cameraAccessMode, canRequestPosition, positionPayload } from "./browserCapabilities.js";
import { CONTROL_SHORTCUTS } from "../../app/hotkeys.js";

/**
 * The paired browser owns this camera element. Only the accepted still crop is
 * handed to the Pi classifier; the stream never becomes a request payload.
 */
export function NetworkedScanPage({ notify, onLeaseLost }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const fileRef = useRef(null);
  const [cameraState, setCameraState] = useState("starting");
  const [pending, setPending] = useState(null);
  const [quality, setQuality] = useState(null);
  const [classification, setClassification] = useState(null);
  const [cropMargin, setCropMargin] = useState(8);
  const [busy, setBusy] = useState(false);
  const [saveBusy, setSaveBusy] = useState(false);
  const [error, setError] = useState(null);
  const requestSerial = useRef(0);

  useEffect(() => {
    let stream;
    let cancelled = false;
    if (cameraAccessMode(window) !== "stream") {
      setCameraState("capture-input");
      return undefined;
    }
    navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    }).then((value) => {
      stream = value;
      if (cancelled) {
        value.getTracks().forEach((track) => track.stop());
        return;
      }
      if (videoRef.current) videoRef.current.srcObject = value;
      setCameraState("ready");
    }).catch(() => {
      if (!cancelled) setCameraState("denied");
    });
    return () => {
      cancelled = true;
      stream?.getTracks?.().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (pending?.url) URL.revokeObjectURL(pending.url);
    };
  }, [pending?.url]);

  const captureVideo = async () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) {
      setError("The phone camera has not produced a frame yet.");
      return;
    }
    const canvas = canvasRef.current || document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d", { willReadFrequently: true }).drawImage(video, 0, 0);
    await prepareCrop(canvas, "camera frame", cropMargin);
  };

  const chooseFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const image = await loadImage(file);
      const canvas = canvasRef.current || document.createElement("canvas");
      canvas.width = image.naturalWidth || image.width;
      canvas.height = image.naturalHeight || image.height;
      canvas.getContext("2d", { willReadFrequently: true }).drawImage(image, 0, 0);
      await prepareCrop(canvas, "manual image", cropMargin);
    } catch (caught) {
      setError(caught.message || "The selected image could not be read.");
    }
  };

  const prepareCrop = async (sourceCanvas, source, margin = cropMargin) => {
    setError(null);
    setClassification(null);
    const canvas = buildManualCrop(sourceCanvas, margin);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
    const measured = measureQuality(imageData);
    setQuality(measured);
    const blob = await canvasToBlob(canvas);
    const hash = await sha256(blob);
    const url = URL.createObjectURL(blob);
    setPending({
      blob,
      hash,
      width: canvas.width,
      height: canvas.height,
      url,
      source,
      margin,
    });
  };

  const reapplyManualCrop = () => {
    if (!pending || !canvasRef.current || busy) return;
    prepareCrop(canvasRef.current, pending.source, cropMargin);
  };

  const classify = async () => {
    if (!pending || busy) return;
    if (!quality?.ready) {
      setError("Improve the local crop quality before sending it to the Pi.");
      return;
    }
    const serial = ++requestSerial.current;
    setBusy(true);
    setError(null);
    try {
      const response = await classifyControllerCrop({
        blob: pending.blob,
        hash: pending.hash,
        width: pending.width,
        height: pending.height,
        requestId: `browser-${Date.now()}`,
      });
      if (serial !== requestSerial.current) return;
      if (pending.hash && response.crop?.sha256 !== pending.hash) {
        throw new Error("The crop hash changed during upload; retry this crop.");
      }
      if (
        response.crop?.width !== pending.width
        || response.crop?.height !== pending.height
      ) {
        throw new Error("The crop dimensions changed during upload; retry this crop.");
      }
      setClassification(response.classification);
      notify(response.classification?.result?.status === "accepted" ? "Plant identified by the Pi." : "The Pi could not accept this view.", "info");
    } catch (caught) {
      if (caught.status === 401) onLeaseLost?.();
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    const result = classification?.result;
    if (!result || result.status !== "accepted" || saveBusy) return;
    setSaveBusy(true);
    setError(null);
    const position = await requestPosition((message) => notify(message, "info"));
    try {
      const response = await saveToLibrary({
        position,
        requestId: classification.request_id,
        cropHash: classification.crop_hash,
      });
      notify(`Saved ${response.record.common_name} to the Pi library.`, "success");
    } catch (caught) {
      if (caught.status === 401) onLeaseLost?.();
      setError(caught.message);
    } finally {
      setSaveBusy(false);
    }
  };

  const clear = () => {
    requestSerial.current += 1;
    setPending(null);
    setQuality(null);
    setClassification(null);
    setError(null);
  };

  const result = classification?.result;
  return (
    <div className="networked-scan-page">
      <section className="networked-camera-card" aria-label="Phone camera">
        <div className="networked-camera-head">
          <div>
            <div className="eyebrow">Paired camera</div>
            <h1>Scan a plant</h1>
          </div>
          <span className="networked-live-badge">Pi classifier</span>
        </div>
        {!pending ? (
          <div className="phone-camera-view">
            {cameraState === "ready" ? (
              <video ref={videoRef} autoPlay playsInline muted aria-label="Live phone camera" />
            ) : (
              <div className="camera-fallback-message">
                <strong>{cameraState === "starting" ? "Starting phone camera…" : "Use the phone camera"}</strong>
                <p>Open the device camera below. The captured still remains local until you approve its crop.</p>
              </div>
            )}
            <div className="detector-fallback-label">Browser detector unavailable · manual crop fallback</div>
          </div>
        ) : (
          <div className="phone-crop-preview">
            <img src={pending.url} alt="Local crop awaiting Pi classification" />
            <div className={`local-result-box ${result?.status === "accepted" ? "accepted" : ""}`}>
              {result?.status === "accepted" && <span>{result.common_name} · {formatConfidence(result.confidence)}</span>}
              {!result && <span>Manual crop</span>}
            </div>
          </div>
        )}
        {pending && !classification && (
          <div className="manual-crop-control">
            <label htmlFor="crop-margin">
              Manual crop inset: {cropMargin}%
              <input
                id="crop-margin"
                type="range"
                min="0"
                max="30"
                step="1"
                value={cropMargin}
                onChange={(event) => setCropMargin(Number(event.target.value))}
              />
            </label>
            <button
              type="button"
              className="btn quiet"
              onClick={reapplyManualCrop}
              disabled={busy}
              data-hotkey={CONTROL_SHORTCUTS.applyCrop}
              aria-keyshortcuts={CONTROL_SHORTCUTS.applyCrop}
            >
              Apply crop <kbd aria-hidden="true">C</kbd>
            </button>
          </div>
        )}
        <canvas ref={canvasRef} className="visually-hidden" aria-hidden="true" />
        <input ref={fileRef} type="file" accept="image/*" capture="environment" className="visually-hidden" onChange={chooseFile} aria-label="Open the phone camera or choose a local plant image" />
        <div className="networked-camera-actions">
          {!pending && cameraState === "ready" && (
            <button
              type="button"
              className="btn green mobile-primary"
              onClick={captureVideo}
              data-hotkey={CONTROL_SHORTCUTS.phoneCapture}
              aria-keyshortcuts={CONTROL_SHORTCUTS.phoneCapture}
            >
              Capture crop <kbd aria-hidden="true">Space</kbd>
            </button>
          )}
          {!pending && (
            <button
              type="button"
              className="btn quiet"
              onClick={() => fileRef.current?.click()}
              data-hotkey={CONTROL_SHORTCUTS.localImage}
              aria-keyshortcuts={CONTROL_SHORTCUTS.localImage}
            >
              {cameraState === "ready" ? "Use a photo" : "Open camera"} <kbd aria-hidden="true">L</kbd>
            </button>
          )}
          {pending && !classification && (
            <button
              type="button"
              className="btn green mobile-primary"
              onClick={classify}
              disabled={busy || !quality?.ready}
              data-hotkey={CONTROL_SHORTCUTS.identifyCrop}
              aria-keyshortcuts={CONTROL_SHORTCUTS.identifyCrop}
            >
              {busy ? "Sending crop…" : "Identify this crop"} <kbd aria-hidden="true">I</kbd>
            </button>
          )}
          {pending && (
            <button
              type="button"
              className="btn quiet"
              onClick={clear}
              disabled={busy}
              data-hotkey={CONTROL_SHORTCUTS.retake}
              aria-keyshortcuts={CONTROL_SHORTCUTS.retake}
            >
              Retake <kbd aria-hidden="true">R</kbd>
            </button>
          )}
        </div>
        {quality && <p className={`local-quality ${quality.ready ? "ready" : "warning"}`}>{quality.message}</p>}
        <p className="networked-privacy-note">Only the accepted {pending ? "crop" : "still crop"} is uploaded. Continuous phone video never reaches the Pi.</p>
      </section>

      <section className="networked-result-card" aria-live="polite">
        <div className="eyebrow">Identification</div>
        {!result && <><h2>Ready when you are</h2><p>Hold the plant in view, capture a clear crop, and send it to Botanika for local classification.</p></>}
        {result?.status === "accepted" && (
          <>
            <h2>{result.common_name}</h2>
            <div className="networked-scientific">{result.scientific_name}</div>
            <div className="networked-confidence">{formatConfidence(result.confidence)} confidence · {result.classifier_version}</div>
            <dl className="networked-details">
              <div><dt>Category</dt><dd>{result.category}</dd></div>
              <div><dt>Family</dt><dd>{result.family}</dd></div>
              <div><dt>Details</dt><dd>{result.short_notes}</dd></div>
            </dl>
            <button
              type="button"
              className="btn green mobile-primary"
              onClick={save}
              disabled={saveBusy}
              data-hotkey={CONTROL_SHORTCUTS.saveToLibrary}
              aria-keyshortcuts={CONTROL_SHORTCUTS.saveToLibrary}
            >
              {saveBusy ? "Saving…" : <>Save to Pi library <kbd aria-hidden="true">S</kbd></>}
            </button>
          </>
        )}
        {result?.status === "uncertain" && <><h2>Not confident</h2><p>{result.short_notes || "Try another angle or a clearer crop."}</p><button type="button" className="btn quiet" onClick={clear} data-hotkey={CONTROL_SHORTCUTS.tryAnotherView} aria-keyshortcuts={CONTROL_SHORTCUTS.tryAnotherView}>Try another view <kbd aria-hidden="true">R</kbd></button></>}
        {result && !["accepted", "uncertain"].includes(result.status) && <><h2>Pi classifier unavailable</h2><p>{result.error || "No result was produced."}</p><button type="button" className="btn quiet" onClick={classify} disabled={busy} data-hotkey={CONTROL_SHORTCUTS.identifyCrop} aria-keyshortcuts={CONTROL_SHORTCUTS.identifyCrop}>Retry crop upload <kbd aria-hidden="true">I</kbd></button></>}
        {error && <p className="mode-error" role="alert">{error}</p>}
      </section>
    </div>
  );
}

function measureQuality(imageData) {
  const values = [];
  let clipped = 0;
  for (let index = 0; index < imageData.data.length; index += 4) {
    const red = imageData.data[index];
    const green = imageData.data[index + 1];
    const blue = imageData.data[index + 2];
    values.push(0.2126 * red + 0.7152 * green + 0.0722 * blue);
    if (Math.max(red, green, blue) >= 250 || Math.min(red, green, blue) <= 5) clipped += 1;
  }
  const mean = values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1);
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(values.length, 1);
  if (mean < 25) return { ready: false, message: "Quality warning: crop is too dark." };
  if (mean > 235) return { ready: false, message: "Quality warning: crop is too bright." };
  if (clipped / Math.max(values.length, 1) > 0.35) return { ready: false, message: "Quality warning: crop is too clipped." };
  if (variance < 120) return { ready: false, message: "Quality warning: hold steady and improve focus." };
  return { ready: true, message: "Local quality checks passed; the crop is ready for the Pi." };
}

function buildManualCrop(sourceCanvas, marginPercent) {
  const width = sourceCanvas.width;
  const height = sourceCanvas.height;
  const margin = Math.max(0, Math.min(30, Number(marginPercent) || 0)) / 100;
  const x1 = Math.floor(width * margin);
  const y1 = Math.floor(height * margin);
  const x2 = Math.max(x1 + 1, Math.ceil(width * (1 - margin)));
  const y2 = Math.max(y1 + 1, Math.ceil(height * (1 - margin)));
  const crop = document.createElement("canvas");
  crop.width = x2 - x1;
  crop.height = y2 - y1;
  crop.getContext("2d", { willReadFrequently: true }).drawImage(
    sourceCanvas,
    x1,
    y1,
    crop.width,
    crop.height,
    0,
    0,
    crop.width,
    crop.height,
  );
  return crop;
}

function canvasToBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("The crop could not be encoded.")), "image/png");
  });
}

async function sha256(blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  if (globalThis.crypto?.subtle) {
    try {
      const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
      return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
    } catch {
      // Private AP pages are normally HTTP, where Web Crypto may be disabled.
    }
  }
  return sha256Fallback(bytes);
}

function sha256Fallback(bytes) {
  const constants = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b,
    0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7,
    0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152,
    0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819,
    0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
    0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const hash = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const bitLength = bytes.length * 8;
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000));
  view.setUint32(paddedLength - 4, bitLength >>> 0);
  const rotate = (value, amount) => (value >>> amount) | (value << (32 - amount));
  for (let offset = 0; offset < paddedLength; offset += 64) {
    const words = new Uint32Array(64);
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4);
    }
    for (let index = 16; index < 64; index += 1) {
      const value = words[index - 15];
      const small0 = rotate(value, 7) ^ rotate(value, 18) ^ (value >>> 3);
      const previous = words[index - 2];
      const small1 = rotate(previous, 17) ^ rotate(previous, 19) ^ (previous >>> 10);
      words[index] = (words[index - 16] + small0 + words[index - 7] + small1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = hash;
    for (let index = 0; index < 64; index += 1) {
      const large1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
      const choose = (e & f) ^ (~e & g);
      const first = (h + large1 + choose + constants[index] + words[index]) >>> 0;
      const large0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const second = (large0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + first) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (first + second) >>> 0;
    }
    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }
  return [...hash].map((value) => value.toString(16).padStart(8, "0")).join("");
}

function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => { URL.revokeObjectURL(url); resolve(image); };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error("The selected image could not be decoded.")); };
    image.src = url;
  });
}

function requestPosition(notify) {
  if (!canRequestPosition(window)) {
    notify("Location unavailable — the discovery will still be saved.");
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const value = positionPayload(position);
        if (value === null) {
          notify("Location was too inaccurate — the discovery will still be saved without coordinates.");
          resolve(null);
          return;
        }
        resolve(value);
      },
      () => {
        notify("Location unavailable — the discovery will still be saved.");
        resolve(null);
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 5000 },
    );
  });
}

function formatConfidence(value) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "–";
}
