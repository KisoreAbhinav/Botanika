import { Foliage, LibraryIcon, ScanIcon, WeedIcon } from "../../components/icons.jsx";

export function HomePage({ onNavigate, capabilities }) {
  const camera = stateOf(capabilities, "camera");
  const plantId = stateOf(capabilities, "classifier");
  const classifierReady = plantId === "ready";
  const knowledge = stateOf(capabilities, "knowledge");
  const storage = stateOf(capabilities, "storage");
  const weeds = stateOf(capabilities, "weeds");

  return (
    <div className="home">
      <div className="home-intro">
        <div className="eyebrow">Local Field Intelligence</div>
        <h1 className="home-title">Scan, save, and learn plants</h1>
        <p className="home-sub">
          Scan plants with the camera, keep discoveries in your library, and ask about them.
        </p>
      </div>

      <div className="home-cards">
        <button type="button" className="home-card" onClick={() => onNavigate("scan")} aria-keyshortcuts="1">
          <span className="card-number">01 / SCAN</span>
          <kbd className="card-hotkey" aria-hidden="true">1</kbd>
          <span className="card-label">Scan for Plants</span>
          <p className="card-desc">
            {classifierReady ? "Hold steady to identify this plant." : "Identification validation pending."}
          </p>
          <span className="card-icon">
            <ScanIcon />
          </span>
        </button>

        <button type="button" className="home-card" onClick={() => onNavigate("library")} aria-keyshortcuts="2">
          <span className="card-number">02 / LIBRARY</span>
          <kbd className="card-hotkey" aria-hidden="true">2</kbd>
          <span className="card-label">Library</span>
          <p className="card-desc">Browse saved plant discoveries.</p>
          <span className="card-icon">
            <LibraryIcon />
          </span>
        </button>

        <button
          type="button"
          className="home-card weed-card"
          onClick={() => onNavigate("weeds")}
          disabled={weeds !== "ready"}
          aria-keyshortcuts="3"
          aria-label={weeds === "ready" ? "Open Weed Detection Beta" : "Weed Detection Beta unavailable"}
          title={weeds === "ready" ? undefined : "Weed Detection Beta is unavailable until its detector is installed."}
        >
          <span className="card-number">03 / WEEDS</span>
          <kbd className="card-hotkey" aria-hidden="true">3</kbd>
          <span className="card-label">
            Weed Detection <span className="badge">Beta</span>
          </span>
          <p className="card-desc">{weeds === "ready" ? "Analyze supported frames locally." : "Detector asset unavailable."}</p>
          <span className="card-icon">
            <WeedIcon />
          </span>
        </button>
      </div>

      <div className="home-shortcuts" aria-label="Keyboard shortcuts">
        <span className="home-shortcuts-label">QUICK KEYS</span>
        <span><kbd>1</kbd> Scan</span>
        <span><kbd>2</kbd> Library</span>
        <span><kbd>3</kbd> Weeds</span>
        <span><kbd>A</kbd> Ask</span>
        <span><kbd>H</kbd> Home</span>
        <span><kbd>?</kbd> Help</span>
      </div>

      <span className="foliage left">
        <Foliage />
      </span>
      <span className="foliage right">
        <Foliage />
      </span>

      <div className="home-status">
        <StatusItem label="Camera" state={camera} />
        <StatusItem label="Plant ID" state={plantId} unavailableText="Validation pending" />
        <StatusItem label="Knowledge" state={knowledge} />
        <StatusItem label="Storage" state={storage} />
        <StatusItem label="Weeds" state={weeds} />
      </div>
    </div>
  );
}

function stateOf(capabilities, key) {
  if (!capabilities || !capabilities[key]) return "unavailable";
  return capabilities[key].available ? "ready" : "unavailable";
}

function StatusItem({ label, state, unavailableText = "Unavailable" }) {
  const dotClass = state === "ready" ? "" : "down";
  return (
    <span className="status-item">
      <span className={`status-dot ${dotClass}`} aria-hidden="true" />
      <span>
        {label}: {state === "ready" ? "Ready" : unavailableText}
      </span>
    </span>
  );
}
