import {
  cancelScan,
  clearFallback,
  fallbackCapture,
  manualCapture,
  retake,
  saveToLibrary,
} from "../../platform/api.js";
import { selectedFallbackIndex } from "./scanState.js";

// Bottom action bar: manual capture during live detection, save/retake/another
// angle once a result exists, cancel while processing, and local-image
// fallback actions. Always visible; primary targets stay >= 44 px tall.

export function ScanActions({
  snapshot,
  capabilities,
  saveState,
  setSaveState,
  notify,
  openFilePicker,
}) {
  const mode = snapshot ? snapshot.mode : "camera";
  const hasResult = Boolean(snapshot && snapshot.classification);
  const result = hasResult ? snapshot.classification.result : null;
  const accepted = Boolean(result && result.status === "accepted");
  const processing = Boolean(snapshot && snapshot.processing);
  const cameraAvailable = Boolean(snapshot ? snapshot.camera_available : true);
  const storageAvailable = Boolean(
    capabilities && capabilities.storage && capabilities.storage.available,
  );

  const onManualCapture = async () => {
    try {
      await manualCapture();
      notify("Manual capture requested.", "info");
    } catch (caught) {
      notify(caught.message, "error");
    }
  };

  const onRetake = async () => {
    try {
      setSaveState("idle");
      await retake();
    } catch (caught) {
      notify(caught.message, "error");
    }
  };

  const onCancel = async () => {
    try {
      await cancelScan();
      notify("Scan cancelled.", "info");
    } catch (caught) {
      notify(caught.message, "error");
    }
  };

  const onSave = async () => {
    setSaveState("saving");
    try {
      const response = await saveToLibrary();
      setSaveState("saved");
      notify(`Saved ${response.record.common_name} to the library.`, "success");
    } catch (caught) {
      setSaveState("idle");
      notify(caught.message, "error");
    }
  };

  const onFallbackCapture = async () => {
    try {
      await fallbackCapture(selectedFallbackIndex(snapshot));
    } catch (caught) {
      notify(caught.message, "error");
    }
  };

  const onClearFallback = async () => {
    try {
      await clearFallback();
    } catch (caught) {
      notify(caught.message, "error");
    }
  };

  return (
    <div className="scan-actions">
      {!hasResult && cameraAvailable && (
        <button type="button" className="btn primary" onClick={onManualCapture} disabled={processing}>
          Manual capture · Space
        </button>
      )}
      {!hasResult && (
        <button type="button" className="btn" onClick={openFilePicker} disabled={processing}>
          Local image
        </button>
      )}
      {mode === "fallback" && !hasResult && (
        <>
          <button type="button" className="btn green" onClick={onFallbackCapture} disabled={processing}>
            Capture from image
          </button>
          <button type="button" className="btn quiet" onClick={onClearFallback}>
            Clear image
          </button>
        </>
      )}

      {hasResult && (
        <>
          <button
            type="button"
            className="btn green"
            onClick={onSave}
            disabled={!accepted || saveState === "saving" || !storageAvailable}
            title={
              !accepted
                ? "A guessed result cannot be saved as a confirmed species"
                : !storageAvailable
                  ? "Storage is unavailable"
                : "Save this crop to the local discovery library"
            }
          >
            {saveState === "saving" ? "Saving…" : "Save to Library"}
          </button>
          <button type="button" className="btn" onClick={onRetake}>
            Retake
          </button>
          {/* Another angle resets the lock so the operator can reframe. */}
          <button type="button" className="btn" onClick={onRetake}>
            Another angle
          </button>
        </>
      )}

      <span className="spacer" />
      {processing && (
        <button type="button" className="btn danger" onClick={onCancel}>
          Cancel
        </button>
      )}
      {result && result.is_stub && <span className="demo-tag">Demo data</span>}
    </div>
  );
}
