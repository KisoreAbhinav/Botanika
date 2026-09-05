import { useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import {
  pairController,
  retryTunnel,
  takeoverController,
} from "../../platform/api.js";
import { LeafMark } from "../../components/icons.jsx";
import {
  getTunnelState,
  MODES,
  pairingCodeFromLocation,
  pairingDeepLink,
  tunnelConnectUrl,
  tunnelState,
} from "./modeState.js";

export function PairingPage({ status, onPaired, onRefresh }) {
  const [code, setCode] = useState("");
  const [deviceName, setDeviceName] = useState("This phone");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const pairing = status?.pairing;
  const accessPoint = status?.access_point;
  const tunnel = getTunnelState(status);
  const tunnelReady = tunnelState(status) === "ready";
  const tunnelConfigured = Boolean(tunnel?.enabled);
  const tunnelUnavailable = tunnelConfigured && !tunnelReady;
  const solo = status?.mode === MODES.SOLO;

  useEffect(() => {
    if (status?.mode === MODES.SOLO) setError("The Pi returned to SOLO mode.");
  }, [status?.mode]);

  useEffect(() => {
    const queryCode = pairingCodeFromLocation(window.location);
    if (!queryCode) return;
    setCode((current) => current || queryCode);
    // The code is now in component state; avoid leaving a one-time secret in
    // browser history or making it easy to copy from the address bar.
    try {
      const clean = `${window.location.pathname}${window.location.hash || ""}`;
      window.history.replaceState({}, document.title, clean);
    } catch {
      /* History can be unavailable in embedded/private browser contexts. */
    }
  }, []);

  const pair = async (event) => {
    event.preventDefault();
    if (busy || code.trim().length < 6) return;
    setBusy(true);
    setError(null);
    try {
      const result = await pairController(code.trim(), deviceName.trim() || "This phone", clientId());
      onPaired(result.session_token, result.status);
    } catch (caught) {
      setError(caught.message);
      onRefresh?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mobile-mode-page">
      <div className="mobile-mode-card">
        <BrandLine />
        <div className="eyebrow">Networked controller</div>
        <h1>{solo ? "The Pi is in SOLO mode" : "Pair this device"}</h1>
        <p className="mode-lead">
          {solo
            ? "Use the physical mode button or Pi controls to enable pairing. This browser cannot change the Pi mode."
            : tunnelReady
              ? "Open the secure HTTPS link from the Pi screen, or scan its QR code, then confirm the one-time code. This phone will be the only active controller."
              : tunnelUnavailable
                ? "The secure internet link is not ready. Ask the Pi operator to retry Quick Tunnel before using this phone from another network."
              : "Join the private Wi-Fi network, then enter the one-time code shown on the Pi screen. This phone will be the only active controller."}
        </p>
        {tunnelReady ? (
          <section className="mode-info-grid" aria-label="Secure tunnel details">
            <div><span>Secure link</span><strong>{tunnelConnectUrl(status) || "–"}</strong></div>
            <div><span>HTTPS</span><strong>Enabled</strong></div>
          </section>
        ) : tunnelUnavailable ? (
          <section className="mode-info-grid" aria-label="Secure tunnel unavailable">
            <div><span>Secure link</span><strong>{tunnel?.state === "failed" ? "Unavailable" : "Starting…"}</strong></div>
            <div><span>Detail</span><strong>{tunnel?.detail || "Wait for the Pi to publish its HTTPS URL."}</strong></div>
          </section>
        ) : (
          <section className="mode-info-grid" aria-label="Private Wi-Fi details">
            <div><span>Wi-Fi</span><strong>{accessPoint?.ssid || "Botanika"}</strong></div>
            <div><span>Pi address</span><strong>{accessPoint?.address || "–"}</strong></div>
          </section>
        )}
        {status?.mode === MODES.NETWORKED_PAIRED && (
          <p className="mode-warning">Another controller is already paired. Ask the Pi operator to take over.</p>
        )}
        <form className="pair-form" onSubmit={pair}>
          <label>
            Pairing code
            <input
              value={code}
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              inputMode="text"
              autoCapitalize="characters"
              autoComplete="one-time-code"
              placeholder="Enter pairing code"
              maxLength={16}
              aria-label="Pairing code"
            />
          </label>
          <label>
            Device name
            <input
              value={deviceName}
              onChange={(event) => setDeviceName(event.target.value)}
              maxLength={80}
              aria-label="Device name"
            />
          </label>
          <button type="submit" className="btn green mobile-primary" disabled={busy || code.trim().length < 6 || status?.mode !== MODES.NETWORKED_UNPAIRED}>
            {busy ? "Pairing…" : "Pair controller"}
          </button>
        </form>
        {pairing?.expires_at && (
          <p className="mode-expiry">Code expires in {pairing.expires_in_seconds ?? "–"} seconds.</p>
        )}
        {error && <p className="mode-error" role="alert">{error}</p>}
        <button type="button" className="btn quiet mobile-secondary" onClick={onRefresh}>Refresh status</button>
        <p className="mode-footnote">No account is created. The Pi keeps the authoritative library and classifier.</p>
      </div>
    </div>
  );
}

export function UnpairedConsole({ status, onSolo, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const [retryBusy, setRetryBusy] = useState(false);
  const [retryError, setRetryError] = useState(null);
  const pairing = status?.pairing;
  const accessPoint = status?.access_point;
  const tunnel = getTunnelState(status);
  const tunnelMode = Boolean(tunnel?.enabled);
  const apActive = Boolean(accessPoint?.available);
  const currentTunnelState = tunnelState(status);
  const tunnelUrl = tunnelConnectUrl(status);
  const qrValue = pairingDeepLink(status) || tunnelUrl;
  const goSolo = async () => {
    setBusy(true);
    try { await onSolo(); } finally { setBusy(false); }
  };
  const retry = async () => {
    setRetryBusy(true);
    setRetryError(null);
    try {
      await retryTunnel();
      await onRefresh?.();
    } catch (caught) {
      setRetryError(caught.message || "The tunnel retry could not be started.");
    } finally {
      setRetryBusy(false);
    }
  };
  const loading = tunnelMode && ["idle", "starting"].includes(currentTunnelState);
  const failed = tunnelMode && currentTunnelState === "failed";
  const ready = tunnelMode && currentTunnelState === "ready" && Boolean(qrValue);
  return (
    <div className="shell mode-shell">
      <ModeMasthead label="NETWORKED · UNPAIRED" />
      <main className="mode-console unpaired-console">
        <div className="mode-console-heading">
          <div className="eyebrow">Controller handoff</div>
          <h1>Connect a phone to Botanika</h1>
          <p>
            {loading
              ? "Setting up a secure connection…"
              : failed
                ? apActive
                  ? "The secure connection failed. Use the private Wi-Fi fallback below, or retry it."
                  : "The secure connection could not be established."
                : ready
                  ? "Scan the QR code or open the HTTPS link, then enter the short code below."
                  : "Join the private Wi-Fi, open this page, and enter the short code below."}
          </p>
        </div>
        {loading && (
          <section className="handoff-panel tunnel-loading" aria-live="polite">
            <div className="tunnel-spinner" aria-hidden="true" />
            <div>
              <div className="panel-label">Connecting…</div>
              <div className="handoff-value">Setting up secure connection</div>
              <div className="handoff-detail">This usually takes a few seconds. The Pi remains in control of its backend.</div>
            </div>
          </section>
        )}
        {failed && !apActive && (
          <section className="handoff-panel tunnel-failed" aria-live="polite">
            <div className="panel-label">Connection unavailable</div>
            <div className="handoff-value">Quick Tunnel failed</div>
            <div className="handoff-detail">{tunnel?.detail || "cloudflared could not publish a secure URL."}</div>
            {tunnel?.diagnostics?.length > 0 && <div className="handoff-detail">{tunnel.diagnostics[tunnel.diagnostics.length - 1]}</div>}
            {retryError && <div className="handoff-detail" role="alert">{retryError}</div>}
          </section>
        )}
        {ready && (
          <div className="handoff-grid tunnel-handoff-grid">
            <section className="handoff-panel tunnel-qr-panel">
              <div className="panel-label">Scan to connect</div>
              <TunnelQr value={qrValue} />
              <div className="tunnel-url" aria-label="Secure connection URL">{tunnelUrl}</div>
              <div className="handoff-detail">HTTPS enables camera access on the phone.</div>
            </section>
            <section className="handoff-panel pairing-code-panel">
              <div className="panel-label">One-time pairing code</div>
              <div className="pairing-code" aria-label="Current pairing code">{pairing?.code || "--------"}</div>
              <div className="handoff-detail">Expires in {pairing?.expires_in_seconds ?? "–"} seconds · single use</div>
              <div className="handoff-detail">Waiting for device…</div>
            </section>
          </div>
        )}
        {(!tunnelMode || (failed && apActive)) && (
          <div className="handoff-grid">
            <section className="handoff-panel">
              <div className="panel-label">Private Wi-Fi</div>
              <div className="handoff-value">{accessPoint?.ssid || "Botanika"}</div>
              <div className="handoff-detail">Open {accessPoint?.address || "192.168.50.1"} on the joined device.</div>
              <div className="wifi-join-badge" aria-label="Join the Botanika Wi-Fi network">
                <span>Wi-Fi</span>
                <strong>Join Botanika</strong>
              </div>
            </section>
            <section className="handoff-panel pairing-code-panel">
              <div className="panel-label">One-time pairing code</div>
              <div className="pairing-code" aria-label="Current pairing code">{pairing?.code || "--------"}</div>
              <div className="handoff-detail">Expires in {pairing?.expires_in_seconds ?? "–"} seconds · single use</div>
              <div className="handoff-detail">The first paired browser becomes the active controller.</div>
            </section>
          </div>
        )}
        <div className="mode-console-actions">
          {failed && <button type="button" className="btn quiet" onClick={retry} disabled={retryBusy}>{retryBusy ? "Retrying…" : "Retry secure connection"}</button>}
          {!failed && <button type="button" className="btn quiet" onClick={onRefresh}>Refresh status</button>}
          <span className="spacer" />
          <button type="button" className="btn danger" onClick={goSolo} disabled={busy}>Return to SOLO</button>
        </div>
      </main>
    </div>
  );
}

function TunnelQr({ value }) {
  const [canvas, setCanvas] = useState(null);
  useEffect(() => {
    if (!canvas || !value) return undefined;
    let cancelled = false;
    QRCode.toCanvas(canvas, value, {
      errorCorrectionLevel: "M",
      margin: 1,
      width: 150,
      color: { dark: "#272724", light: "#f7f4e9" },
    }).catch(() => {
      if (!cancelled) canvas.replaceChildren();
    });
    return () => { cancelled = true; };
  }, [canvas, value]);
  return <canvas ref={setCanvas} className="tunnel-qr" aria-label="QR code for secure Botanika connection" />;
}

export function PairedConsole({ status, onSolo, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const controller = status?.controller;
  const scan = status?.scan || {};
  const recent = useMemo(() => status?.recent_results || [], [status?.recent_results]);
  const disconnect = async () => {
    setBusy(true);
    try {
      // The Pi has no bearer token. Operator takeover revokes the active lease
      // and leaves a fresh unpaired invitation visible on this console.
      await takeoverController();
      await onRefresh();
    } finally { setBusy(false); }
  };
  const solo = async () => {
    setBusy(true);
    try { await onSolo(); } finally { setBusy(false); }
  };
  return (
    <div className="shell mode-shell">
      <ModeMasthead label="NETWORKED · PAIRED" />
      <main className="mode-console paired-console">
        <div className="paired-topline">
          <div>
            <div className="eyebrow">Active controller</div>
            <h1>{controller?.device_name || "Paired browser"}</h1>
            <p>{controller?.client_id || "browser"} · lease expires in {controller?.expires_in_seconds ?? "–"} seconds</p>
          </div>
          <div className={`connection-badge ${status?.connection?.healthy ? "healthy" : "degraded"}`}>
            <span className="status-dot" aria-hidden="true" />
            {status?.connection?.healthy ? "Connected" : "Reconnecting"}
          </div>
        </div>
        <div className="paired-grid">
          <section className="handoff-panel current-scan-panel">
            <div className="panel-label">Current scan</div>
            <div className="handoff-value">{scan.state || "Waiting"}</div>
            <div className="handoff-detail">{scan.hint || "The paired browser controls the camera and sends accepted crops only."}</div>
            {scan.result?.common_name && <div className="console-result">{scan.result.common_name} · {formatConfidence(scan.result.confidence)}</div>}
          </section>
          <section className="handoff-panel recent-panel">
            <div className="panel-label">Recent result log</div>
            {recent.length ? recent.slice(-3).reverse().map((item, index) => (
              <div className="console-log-row" key={`${item.request_id}-${index}`}>
                <span>{item.common_name || item.status}</span>
                <span>{formatConfidence(item.confidence)}</span>
              </div>
            )) : <div className="handoff-detail">No controller results yet.</div>}
          </section>
        </div>
        <div className="mode-console-actions">
          <span className="console-health">Pi API · {status?.network?.state || "local"}</span>
          <span className="spacer" />
          <button type="button" className="btn quiet" onClick={disconnect} disabled={busy}>Disconnect controller</button>
          <button type="button" className="btn danger" onClick={solo} disabled={busy}>Return to SOLO</button>
        </div>
      </main>
    </div>
  );
}

function ModeMasthead({ label }) {
  return (
    <header className="masthead">
      <div className="masthead-side"><span className="masthead-status">{label}</span></div>
      <div className="masthead-center"><LeafMark /><span className="masthead-brand">Botanika</span></div>
      <div className="masthead-side right"><span className="status-dot degraded" aria-label="Networked mode" /></div>
    </header>
  );
}

function BrandLine() {
  return <div className="mobile-brand"><LeafMark /><span>Botanika</span></div>;
}

function clientId() {
  try {
    const key = "botanika.controller.client-id";
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const value = window.crypto?.randomUUID?.() || `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.localStorage.setItem(key, value);
    return value;
  } catch {
    return `browser-${Date.now()}`;
  }
}

function formatConfidence(value) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "–";
}
