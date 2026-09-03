import { Foliage, LibraryIcon, ScanIcon, WeedIcon } from "../../components/icons.jsx";

export function HomePage({ onNavigate, capabilities }) {
  const camera = stateOf(capabilities, "camera");
  const models = combinedState(capabilities, ["detector", "classifier"]);
  const classifierReady = stateOf(capabilities, "classifier") === "ready";
  const knowledge = stateOf(capabilities, "knowledge");
  const storage = stateOf(capabilities, "storage");

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
        <button type="button" className="home-card" onClick={() => onNavigate("scan")}>
          <span className="card-number">01 / SCAN</span>
          <span className="card-label">Scan for Plants</span>
          <p className="card-desc">
            {classifierReady ? "Hold a plant steady to identify it." : "Scanning ready; identification validation pending."}
          </p>
          <span className="card-icon">
            <ScanIcon />
          </span>
        </button>

        <button type="button" className="home-card" onClick={() => onNavigate("library")}>
          <span className="card-number">02 / LIBRARY</span>
          <span className="card-label">Library</span>
          <p className="card-desc">Browse identified plants and saved views.</p>
          <span className="card-icon">
            <LibraryIcon />
          </span>
        </button>

        <button
          type="button"
          className="home-card"
          disabled
          aria-label="Weed Detection, beta, not available yet"
        >
          <span className="card-number">03 / WEEDS</span>
          <span className="card-label">
            Weed Detection <span className="badge">Beta</span>
          </span>
          <p className="card-desc">Unavailable in this build.</p>
          <span className="card-icon">
            <WeedIcon />
          </span>
        </button>
      </div>

      <span className="foliage left">
        <Foliage />
      </span>
      <span className="foliage right">
        <Foliage />
      </span>

      <div className="home-status">
        <StatusItem label="Camera" state={camera} />
        <StatusItem label="Models" state={models} />
        <StatusItem label="Knowledge" state={knowledge} />
        <StatusItem label="Storage" state={storage} />
      </div>
    </div>
  );
}

function stateOf(capabilities, key) {
  if (!capabilities || !capabilities[key]) return "unavailable";
  return capabilities[key].available ? "ready" : "unavailable";
}

function combinedState(capabilities, keys) {
  return keys.every((key) => stateOf(capabilities, key) === "ready") ? "ready" : "unavailable";
}

function StatusItem({ label, state }) {
  const dotClass = state === "ready" ? "" : "down";
  return (
    <span className="status-item">
      <span className={`status-dot ${dotClass}`} aria-hidden="true" />
      <span>
        {label}: {state === "ready" ? "Ready" : "Unavailable"}
      </span>
    </span>
  );
}
