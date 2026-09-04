import { useCallback, useEffect, useRef, useState } from "react";
import { AskIcon, LeafMark } from "../components/icons.jsx";
import {
  clearControllerToken,
  fetchCapabilities,
  fetchModeStatus,
  fetchReady,
  getControllerToken,
  heartbeatController,
  returnToSolo,
  setControllerToken,
  toggleMode,
} from "../platform/api.js";
import { HomePage } from "../features/home/HomePage.jsx";
import { ScanPage } from "../features/scan/ScanPage.jsx";
import { LibraryPage } from "../features/library/LibraryPage.jsx";
import { AskPage } from "../features/ask/AskPage.jsx";
import { WeedsPage } from "../features/weeds/WeedsPage.jsx";
import { MODES } from "../features/mode/modeState.js";
import { PairingPage, PairedConsole, UnpairedConsole } from "../features/mode/ModeScreens.jsx";
import { isShortcutBlocked, shortcutAction } from "./hotkeys.js";

export function App() {
  const [screen, setScreen] = useState("home");
  const [toasts, setToasts] = useState([]);
  const [capabilities, setCapabilities] = useState(null);
  const [ready, setReady] = useState(null);
  const [modeStatus, setModeStatus] = useState(null);
  const [controllerToken, setControllerTokenState] = useState(() => getControllerToken());
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [scale, setScale] = useState(1);
  const [compact, setCompact] = useState(false);
  const toastSeq = useRef(0);
  const operator = modeStatus?.client_role === "operator";
  // Only an explicitly identified remote client gets the portrait shell.
  // During startup (or when an older backend has no mode endpoint), the Pi
  // remains the fixed kiosk canvas instead of reflowing at 800×480.
  const responsive = modeStatus?.client_role === "remote" || compact;

  const notify = useCallback((message, kind = "info") => {
    const id = ++toastSeq.current;
    setToasts((current) => [...current.slice(-2), { id, message, kind }]);
    if (kind !== "error") {
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

  const refreshMode = useCallback(async () => {
    try {
      const status = await fetchModeStatus();
      setModeStatus(status);
      if (status?.mode !== MODES.NETWORKED_PAIRED && controllerToken) {
        clearControllerToken();
        setControllerTokenState(null);
      }
    } catch {
      // Keep the last known mode while the Pi briefly restarts. Individual
      // features expose their own reconnect state when they need the service.
    }
  }, [controllerToken]);

  useEffect(() => {
    refreshCapabilities();
    const interval = setInterval(refreshCapabilities, 15000);
    return () => clearInterval(interval);
  }, [refreshCapabilities]);

  useEffect(() => {
    refreshMode();
    const interval = setInterval(refreshMode, 2000);
    return () => clearInterval(interval);
  }, [refreshMode]);

  useEffect(() => {
    if (operator || !controllerToken) return undefined;
    const checkLease = async () => {
      try {
        const status = await heartbeatController();
        setModeStatus(status);
      } catch (caught) {
        if (caught.status === 401) {
          clearControllerToken();
          setControllerTokenState(null);
          notify("Controller lease lost. Pair this device again.", "error");
          await refreshMode();
        }
      }
    };
    const interval = setInterval(checkLease, 20000);
    return () => clearInterval(interval);
  }, [operator, controllerToken, notify, refreshMode]);

  // The Pi keeps its exact 800×480 shell. A portrait browser gets a separate
  // responsive shell instead of a scaled kiosk canvas.
  useEffect(() => {
    const update = () => {
      const portrait = window.innerHeight > window.innerWidth * 1.05;
      const isCompact = portrait || window.innerWidth < 700;
      setCompact(isCompact);
      // Match InnoHack's device contract: the kiosk is a fixed 800×480 canvas
      // that scales down to fit, never up. Keeping the layout box fixed makes
      // the transform origin the true viewport centre at every kiosk size.
      const fit = Math.min(window.innerWidth / 800, window.innerHeight / 480);
      setScale(isCompact ? 1 : Math.min(1, Math.max(0.5, fit)));
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  const setPaired = useCallback((token, status) => {
    setControllerToken(token);
    setControllerTokenState(token);
    setModeStatus(status);
  }, []);

  const handleSolo = useCallback(async () => {
    const status = await returnToSolo();
    clearControllerToken();
    setControllerTokenState(null);
    setModeStatus(status);
    setScreen("home");
  }, []);

  const handleToggle = useCallback(async () => {
    try {
      const status = await toggleMode();
      setModeStatus(status);
      if (status?.mode !== MODES.NETWORKED_PAIRED) {
        clearControllerToken();
        setControllerTokenState(null);
      }
      notify(
        status?.mode === MODES.NETWORKED_UNPAIRED
          ? "Networked mode is ready to pair."
          : "SOLO mode restored.",
        "info",
      );
    } catch (caught) {
      notify(caught.message, "error");
    }
  }, [notify]);

  const handleLeaseLost = useCallback(() => {
    clearControllerToken();
    setControllerTokenState(null);
    refreshMode();
  }, [refreshMode]);

  // Software/keyboard fallback for development; the physical GPIO adapter
  // calls the same /mode/toggle transition. Keep navigation available to the
  // local operator and to an explicitly paired browser, while leaving the
  // mode handoff consoles in charge of their own controls.
  useEffect(() => {
    const onKey = (event) => {
      // Escape is the universal close affordance for the help and diagnostics
      // popovers. It must work even when focus is on a button inside them.
      if (event.key === "Escape" && (showShortcuts || showDiagnostics)) {
        event.preventDefault();
        setShowShortcuts(false);
        setShowDiagnostics(false);
        return;
      }
      if (isShortcutBlocked(event, {
        overlaysOpen: showShortcuts || showDiagnostics,
      }) || event.repeat) return;

      const modeConsoleVisible = modeStatus?.mode === MODES.NETWORKED_UNPAIRED
        || (modeStatus?.mode === MODES.NETWORKED_PAIRED && operator);
      if (modeConsoleVisible) return;

      if (event.key === "?") {
        event.preventDefault();
        setShowDiagnostics(false);
        setShowShortcuts((value) => !value);
        return;
      }
      if (event.key.toLowerCase() === "n" && operator && !compact) {
        event.preventDefault();
        void handleToggle();
        return;
      }

      const action = shortcutAction(event.key);
      if (!action) return;
      if (action === "weeds" && !capabilities?.weeds?.available) {
        event.preventDefault();
        notify("Weed Detection is unavailable until its detector is ready.", "error");
        return;
      }
      event.preventDefault();
      setScreen(action);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [capabilities, compact, handleToggle, modeStatus?.mode, notify, operator, showDiagnostics, showShortcuts]);

  if (modeStatus?.mode === MODES.SOLO && !operator) {
    return <PairingPage status={modeStatus} onPaired={setPaired} onRefresh={refreshMode} />;
  }

  if (modeStatus?.mode === MODES.NETWORKED_UNPAIRED) {
    if (operator) return <UnpairedConsole status={modeStatus} onSolo={handleSolo} onRefresh={refreshMode} />;
    return <PairingPage status={modeStatus} onPaired={setPaired} onRefresh={refreshMode} />;
  }

  if (modeStatus?.mode === MODES.NETWORKED_PAIRED && operator) {
    return <PairedConsole status={modeStatus} onSolo={handleSolo} onRefresh={refreshMode} />;
  }

  if (modeStatus?.mode === MODES.NETWORKED_PAIRED && !operator && !controllerToken) {
    return <PairingPage status={modeStatus} onPaired={setPaired} onRefresh={refreshMode} />;
  }

  return (
    <AppShell
      compact={responsive}
      scale={scale}
      screen={screen}
      setScreen={setScreen}
      capabilities={capabilities}
      ready={ready}
      modeStatus={modeStatus}
      networked={modeStatus?.mode === MODES.NETWORKED_PAIRED}
      showDiagnostics={showDiagnostics}
      setShowDiagnostics={setShowDiagnostics}
      showShortcuts={showShortcuts}
      onToggleMode={handleToggle}
      notify={notify}
      toasts={toasts}
      dismissToast={dismissToast}
      onLeaseLost={handleLeaseLost}
    />
  );
}
function AppShell({
  compact,
  scale,
  screen,
  setScreen,
  capabilities,
  ready,
  modeStatus,
  networked,
  showDiagnostics,
  setShowDiagnostics,
  showShortcuts,
  onToggleMode,
  notify,
  toasts,
  dismissToast,
  onLeaseLost,
}) {
  const summary = summarize(capabilities);
  return (
    <div className={`shell ${compact ? "responsive-shell" : ""}`} style={{ transform: compact ? "none" : `scale(${scale})` }}>
      <header className="masthead">
        <div className="masthead-side">
          {screen !== "home" ? (
            <button type="button" className="btn quiet" onClick={() => setScreen("home")} aria-keyshortcuts="H">Home <kbd>H</kbd></button>
          ) : (
            <>
              <span className="masthead-status">{transportLabel(capabilities, modeStatus)}</span>
              {!compact && <button type="button" className="btn quiet mode-button" onClick={onToggleMode} aria-keyshortcuts="N">Mode <kbd>N</kbd></button>}
            </>
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
            aria-keyshortcuts="A"
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
        {screen === "scan" && (
          <ScanPage
            notify={notify}
            capabilities={capabilities}
            networked={networked}
            onLeaseLost={onLeaseLost}
          />
        )}
        {screen === "library" && <LibraryPage notify={notify} />}
        {screen === "weeds" && (
          <WeedsPage
            capabilities={capabilities}
            networked={networked}
            notify={notify}
            onLeaseLost={onLeaseLost}
          />
        )}
        {screen === "ask" && (
          <AskPage
            ready={ready}
            capabilities={capabilities}
            localOperator={modeStatus?.client_role === "operator"}
            onNavigate={setScreen}
          />
        )}
        {showDiagnostics && (
          <DiagnosticsPop
            capabilities={capabilities}
            ready={ready}
            onClose={() => setShowDiagnostics(false)}
          />
        )}
        {showShortcuts && (
          <KeyboardHelp onClose={() => setShowShortcuts(false)} />
        )}
        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((toast) => (
            <div key={toast.id} className={`toast ${toast.kind}`}>
              <span>{toast.message}</span>
              <button type="button" onClick={() => dismissToast(toast.id)} aria-label="Dismiss">×</button>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function KeyboardHelp({ onClose }) {
  return (
    <section
      className="shortcuts-pop"
      role="dialog"
      aria-modal="false"
      aria-label="Keyboard shortcuts"
      data-hotkeys-block="true"
    >
      <div className="shortcuts-heading">
        <div>
          <div className="eyebrow">Kiosk controls</div>
          <h3>Keyboard shortcuts</h3>
        </div>
        <button type="button" className="btn quiet icon-target" onClick={onClose} aria-label="Close keyboard shortcuts">×</button>
      </div>
      <dl className="shortcuts-list">
        <div><kbd>1</kbd><dt>Scan for Plants</dt></div>
        <div><kbd>2</kbd><dt>Open Library</dt></div>
        <div><kbd>3</kbd><dt>Weed Detection</dt></div>
        <div><kbd>A</kbd><dt>Ask Botanika</dt></div>
        <div><kbd>H</kbd><dt>Go Home</dt></div>
        <div><kbd>Esc</kbd><dt>Home / close panel</dt></div>
        <div><kbd>?</kbd><dt>Show these shortcuts</dt></div>
      </dl>
      <p>Shortcuts pause while you type or work in a dialog.</p>
    </section>
  );
}

function summarize(capabilities) {
  if (!capabilities) return { ok: false, knowledge: false };
  const keys = ["camera", "detector", "classifier", "storage", "library", "preview"];
  // The private AP is expected to stay ready while configured. A Quick
  // Tunnel, however, is intentionally idle in SOLO and must not make the
  // otherwise-offline kiosk look degraded before NETWORKED is selected.
  const networkModel = capabilities.network?.model;
  const configuredNetworkEnabled = Boolean(capabilities.network?.model?.enabled);
  const tunnelOnly = Boolean(networkModel?.tunnel?.enabled && !networkModel?.status?.enabled);
  if (configuredNetworkEnabled && !tunnelOnly) keys.push("network");
  const ok = keys.every((key) => capabilities[key] && capabilities[key].available);
  return { ok, knowledge: Boolean(capabilities.knowledge && capabilities.knowledge.available) };
}

function transportLabel(capabilities, modeStatus) {
  if (modeStatus?.mode === MODES.NETWORKED_PAIRED) return "NETWORKED · Paired";
  if (modeStatus?.mode === MODES.NETWORKED_UNPAIRED) return "NETWORKED · Pairing";
  const status = capabilities?.network?.model;
  const tunnelOnly = Boolean(status?.tunnel?.enabled && !status?.status?.enabled);
  if (status?.enabled && !tunnelOnly) {
    if (status.available) return "SOLO · Private Wi-Fi";
    return "SOLO · AP starting";
  }
  if (status?.tunnel?.enabled) return "SOLO · Tunnel idle";
  return "SOLO · Loopback";
}

function DiagnosticsPop({ capabilities, ready, onClose }) {
  const rows = capabilities
    ? Object.entries(capabilities)
    : [["service", { available: false, detail: "Capabilities not reachable." }]];
  return (
    <section className="diagnostics-pop" aria-label="Diagnostics">
      <h3>Diagnostics</h3>
      {ready && <p className="diagnostics-readiness">Readiness: <strong>{ready.status}</strong></p>}
      <dl className="diagnostics-list">
        {rows.map(([name, state]) => (
          <div className="metric-row" key={name}>
            <dt>{name}</dt>
            <dd>
              {state.available ? "Ready" : "Unavailable"}
              {state.detail ? <div className="diagnostics-detail">{state.detail}</div> : null}
            </dd>
          </div>
        ))}
      </dl>
      <button type="button" className="btn quiet diagnostics-close" onClick={onClose}>Close</button>
    </section>
  );
}
