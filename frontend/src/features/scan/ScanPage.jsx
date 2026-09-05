import { useCallback, useEffect, useRef, useState } from "react";
import { CameraIcon } from "../../components/icons.jsx";
import {
  PREVIEW_URL,
  fetchScanState,
  selectBox,
  subscribeToSnapshots,
  uploadFallbackImage,
} from "../../platform/api.js";
import { ScanOverlay } from "./ScanOverlay.jsx";
import { ScanSidePanel } from "./ScanSidePanel.jsx";
import { ScanActions } from "./ScanActions.jsx";
import { NetworkedScanPage } from "../networked/NetworkedScanPage.jsx";
import { CONTROL_SHORTCUTS } from "../../app/hotkeys.js";

export function ScanPage({ notify, capabilities, networked = false, onLeaseLost }) {
  if (networked) {
    return <NetworkedScanPage notify={notify} onLeaseLost={onLeaseLost} />;
  }
  return <SoloScanPage notify={notify} capabilities={capabilities} />;
}

function SoloScanPage({ notify, capabilities }) {
  const [snapshot, setSnapshot] = useState(null);
  const [connected, setConnected] = useState(false);
  const [saveState, setSaveState] = useState("idle");
  const fileInputRef = useRef(null);

  useEffect(() => {
    // Seed with one poll, then stay current via the event channel.
    fetchScanState()
      .then(setSnapshot)
      .catch(() => {});
    const unsubscribe = subscribeToSnapshots(
      (event) => {
        setSnapshot(event);
        setConnected(true);
      },
      () => setConnected(false),
    );
    return unsubscribe;
  }, []);

  const cameraAvailable = Boolean(snapshot ? snapshot.camera_available : true);
  const mode = snapshot ? snapshot.mode : "camera";
  const previewAvailable = cameraAvailable || mode === "fallback";
  const hasResult = Boolean(snapshot && snapshot.classification);

  const onSelectBox = useCallback(
    async (index) => {
      try {
        await selectBox(index);
      } catch (caught) {
        notify(caught.message, "error");
      }
    },
    [notify],
  );

  const openFilePicker = () => {
    if (fileInputRef.current) fileInputRef.current.click();
  };

  return (
    <div className="scan">
      <div className="scan-main">
        <div className={`camera-workspace ${previewAvailable ? "" : "unavailable"}`}>
          {previewAvailable ? (
            <>
              <img
                className="camera-frame"
                src={PREVIEW_URL}
                alt={mode === "fallback" ? "Selected local image" : "Live camera preview"}
                width={500}
                height={330}
              />
              <ScanOverlay snapshot={snapshot} onBoxTap={onSelectBox} />
              <div className="status-pill" role="status">
                {statusText(snapshot, connected)}
              </div>
              {mode === "camera" &&
                snapshot &&
                snapshot.required_checks > 0 &&
                !hasResult && (
                  <div className="stability-strip" aria-hidden="true">
                    {Array.from({ length: snapshot.required_checks }).map((_, index) => (
                      <span
                        key={index}
                        className={`stability-cell ${
                          index < snapshot.stable_checks ? "filled" : ""
                        }`}
                      />
                    ))}
                  </div>
                )}
            </>
          ) : (
            <>
              <p>
                The camera is not available. Upload a photo from this device to keep identifying
                plants.
              </p>
              <button
                type="button"
                className="btn"
                onClick={openFilePicker}
                data-hotkey={CONTROL_SHORTCUTS.localImage}
                aria-keyshortcuts={CONTROL_SHORTCUTS.localImage}
              >
                <CameraIcon />
                Upload a local image <kbd aria-hidden="true">L</kbd>
              </button>
            </>
          )}
        </div>

        <ScanSidePanel snapshot={snapshot} saveState={saveState} />
      </div>

      <ScanActions
        snapshot={snapshot}
        capabilities={capabilities}
        saveState={saveState}
        setSaveState={setSaveState}
        notify={notify}
        openFilePicker={openFilePicker}
      />

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="visually-hidden"
        onChange={async (event) => {
          const file = event.target.files && event.target.files[0];
          event.target.value = "";
          if (!file) return;
          try {
            await uploadFallbackImage(file);
            notify("Local image selected for analysis.", "info");
          } catch (caught) {
            notify(caught.message, "error");
          }
        }}
        aria-label="Upload a local image for analysis"
      />
    </div>
  );
}

function statusText(snapshot, connected) {
  if (!snapshot) return "Starting…";
  if (snapshot.error) return `Error: ${snapshot.error}`;
  if (snapshot.processing) return "Processing plant…";
  if (snapshot.state) return snapshot.hint || snapshot.state;
  return connected ? "Waiting for a frame…" : "Connecting…";
}
