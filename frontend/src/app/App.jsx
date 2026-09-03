import { useCallback, useEffect, useRef, useState } from "react";
import { AskIcon, LeafMark } from "../components/icons.jsx";
import { fetchCapabilities, fetchReady } from "../platform/api.js";
import { HomePage } from "../features/home/HomePage.jsx";
import { ScanPage } from "../features/scan/ScanPage.jsx";
import { LibraryPage } from "../features/library/LibraryPage.jsx";
import { AskPage } from "../features/ask/AskPage.jsx";
import { WeedsPage } from "../features/weeds/WeedsPage.jsx";

export function App() {
  const [screen, setScreen] = useState("home");
  const [toasts, setToasts] = useState([]);
  const [capabilities, setCapabilities] = useState(null);
  const [ready, setReady] = useState(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [scale, setScale] = useState(1);
  const toastSeq = useRef(0);

  const notify = useCallback((message, kind = "info") => {
    const id = ++toastSeq.current;
    setToasts((current) => [...current.slice(-2), { id, message, kind }]);
    if (kind !== "error") {
      // Informational toasts auto-dismiss after 5 s; errors stay until closed.
      setTimeout(() => {
        setToasts((current) => current.filter((toast) => toast.id !== id));
      }, 5000);
    }
  }, []);

  const dismissToast = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const refreshCapabilities = useCallback(async () => {
    try {
      const [report, readyReport] = await Promise.all([
        fetchCapabilities(),
        fetchReady().catch(() => null),
      ]);
      setCapabilities(report);
      if (readyReport) setReady(readyReport);
    } catch {
      setCapabilities(null);
    }
  }, []);

  useEffect(() => {
    refreshCapabilities();
    const interval = setInterval(refreshCapabilities, 15000);
    return () => clearInterval(interval);
  }, [refreshCapabilities]);

  // Scale the fixed 800x480 shell proportionally on other viewports.
  useEffect(() => {
    const update = () => {
      const fit = Math.min(window.innerWidth / 800, window.innerHeight / 480);
      setScale(fit);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Keyboard shortcuts: 1/2/3 homepage actions, A for Ask, H or Escape home.
  useEffect(() => {
    const onKey = (event) => {
      if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
      const key = event.key.toLowerCase();
      if (key === "1") setScreen("scan");
      else if (key === "2") setScreen("library");
      else if (key === "a") setScreen("ask");
      else if (key === "h" || key === "escape") setScreen("home");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const summary = summarize(capabilities);

  return (
    <div className="shell" style={{ transform: `scale(${scale})` }}>
      <header className="masthead">
        <div className="masthead-side">
          {screen !== "home" ? (
            <button type="button" className="btn quiet" onClick={() => setScreen("home")}>
              Home
            </button>
          ) : (
            <span className="masthead-status">SOLO · Loopback</span>
          )}
        </div>
        <div className="masthead-center">
          <LeafMark />
          <span className="masthead-brand">Botanika</span>
        </div>
        <div className="masthead-side right">
          <button
            type="button"
            className="btn"
            onClick={() => setScreen("ask")}
            aria-label={`Ask Botanika (${summary.knowledge ? "available" : "unavailable"})`}
          >
            <AskIcon />
            Ask
          </button>
          <button
            type="button"
            className="btn icon-target quiet"
            aria-label="Capability diagnostics"
            onClick={() => setShowDiagnostics((value) => !value)}
          >
            <span className={`status-dot ${summary.ok ? "" : "degraded"}`} aria-hidden="true" />
          </button>
        </div>
      </header>

      <main className="body">
        {screen === "home" && <HomePage onNavigate={setScreen} capabilities={capabilities} />}
        {screen === "scan" && <ScanPage notify={notify} capabilities={capabilities} />}
        {screen === "library" && <LibraryPage notify={notify} />}
        {screen === "weeds" && <WeedsPage />}
        {screen === "ask" && <AskPage ready={ready} />}
        {showDiagnostics && (
          <DiagnosticsPop
            capabilities={capabilities}
            ready={ready}
            onClose={() => setShowDiagnostics(false)}
          />
        )}
        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((toast) => (
            <div key={toast.id} className={`toast ${toast.kind}`}>
              <span>{toast.message}</span>
              <button type="button" onClick={() => dismissToast(toast.id)} aria-label="Dismiss">
                ×
              </button>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function summarize(capabilities) {
  if (!capabilities) return { ok: false, knowledge: false };
  const keys = ["camera", "detector", "classifier", "storage", "library", "preview"];
  const ok = keys.every((key) => capabilities[key] && capabilities[key].available);
  return { ok, knowledge: Boolean(capabilities.knowledge && capabilities.knowledge.available) };
}

function DiagnosticsPop({ capabilities, ready, onClose }) {
  const rows = capabilities
    ? Object.entries(capabilities)
    : [["service", { available: false, detail: "Capabilities not reachable." }]];
  return (
    <section className="diagnostics-pop" aria-label="Diagnostics">
      <h3>Diagnostics</h3>
      {ready && (
        <p style={{ margin: "0 0 6px" }}>
          Readiness: <strong>{ready.status}</strong>
        </p>
      )}
      <dl style={{ margin: 0 }}>
        {rows.map(([name, state]) => (
          <div className="metric-row" key={name}>
            <dt>{name}</dt>
            <dd>
              {state.available ? "Ready" : "Unavailable"}
              {state.detail ? <div style={{ color: "var(--faint)" }}>{state.detail}</div> : null}
            </dd>
          </div>
        ))}
      </dl>
      <button type="button" className="btn quiet" style={{ marginTop: 8 }} onClick={onClose}>
        Close
      </button>
    </section>
  );
}
