import {
  cancelScan,
  clearFallback,
  fallbackCapture,
  manualCapture,
  retake,
  saveToLibrary,
} from "../../platform/api.js";
import { selectedFallbackIndex } from "./scanState.js";
import { CONTROL_SHORTCUTS } from "../../app/hotkeys.js";

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
        <button
          type="button"
          className="btn primary"
          onClick={onManualCapture}
          disabled={processing}
          data-hotkey={CONTROL_SHORTCUTS.manualCapture}
          aria-keyshortcuts={CONTROL_SHORTCUTS.manualCapture}
        >
          Manual capture <kbd aria-hidden="true">Space</kbd>
        </button>
      )}
      {!hasResult && (
        <button
          type="button"
          className="btn"
          onClick={openFilePicker}
          disabled={processing}
          data-hotkey={CONTROL_SHORTCUTS.localImage}
          aria-keyshortcuts={CONTROL_SHORTCUTS.localImage}
        >
          Local image <kbd aria-hidden="true">L</kbd>
        </button>
      )}
      {mode === "fallback" && !hasResult && (
        <>
          <button
            type="button"
            className="btn green"
            onClick={onFallbackCapture}
            disabled={processing}
            data-hotkey={CONTROL_SHORTCUTS.captureFromImage}
            aria-keyshortcuts={CONTROL_SHORTCUTS.captureFromImage}
          >
            Capture from image <kbd aria-hidden="true">C</kbd>
          </button>
          <button
            type="button"
            className="btn quiet"
            onClick={onClearFallback}
            data-hotkey={CONTROL_SHORTCUTS.clearImage}
            aria-keyshortcuts={CONTROL_SHORTCUTS.clearImage}
          >
            Clear image <kbd aria-hidden="true">X</kbd>
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
            data-hotkey={CONTROL_SHORTCUTS.saveToLibrary}
            aria-keyshortcuts={CONTROL_SHORTCUTS.saveToLibrary}
            title={
              !accepted
                ? "A guessed result cannot be saved as a confirmed species"
                : !storageAvailable
                  ? "Storage is unavailable"
                : "Save this crop to the local discovery library"
            }
          >
            {saveState === "saving" ? "Saving…" : <>Save to Library <kbd aria-hidden="true">S</kbd></>}
          </button>
          <button
            type="button"
            className="btn"
            onClick={onRetake}
            data-hotkey={CONTROL_SHORTCUTS.retake}
            aria-keyshortcuts={CONTROL_SHORTCUTS.retake}
          >
            Retake <kbd aria-hidden="true">R</kbd>
          </button>
          {/* Another angle resets the lock so the operator can reframe. */}
          <button
            type="button"
            className="btn"
            onClick={onRetake}
            data-hotkey={CONTROL_SHORTCUTS.anotherAngle}
            aria-keyshortcuts={CONTROL_SHORTCUTS.anotherAngle}
          >
            Another angle <kbd aria-hidden="true">G</kbd>
          </button>
        </>
      )}

      <span className="spacer" />
      {processing && (
        <button
          type="button"
          className="btn danger"
          onClick={onCancel}
          data-hotkey={CONTROL_SHORTCUTS.cancelScan}
          aria-keyshortcuts={CONTROL_SHORTCUTS.cancelScan}
        >
          Cancel <kbd aria-hidden="true">Esc</kbd>
        </button>
      )}
      {result && result.is_stub && <span className="demo-tag">Demo data</span>}
    </div>
  );
}
