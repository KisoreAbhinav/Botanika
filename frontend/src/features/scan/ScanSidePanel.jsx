// Right-hand status/details panel of the Scan screen: live quality guidance
// during detection, processing state, and the accepted/uncertain result.

import { deriveScanPanelState } from "./scanState.js";

function pct(value) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "–";
}

export function ScanSidePanel({ snapshot, saveState }) {
  const classification = snapshot && snapshot.classification;
  const result = classification ? classification.result : null;
  const panelState = deriveScanPanelState(snapshot);

  if (panelState === "processing") {
    return (
      <aside className="scan-side">
        <div className="side-header">Processing plant…</div>
        <div className="side-body">
          <p>The accepted crop is being identified. You can cancel below.</p>
          <div className="scan-line" aria-hidden="true" />
        </div>
      </aside>
    );
  }

  if (panelState === "result") {
    return (
      <aside className="scan-side">
        <div className="side-header">Result</div>
        <div className="side-body">
          <div className="species-name">{result.common_name}</div>
          <div className="species-sci">{result.scientific_name}</div>
          <div className="confidence-line">
            confidence {pct(result.confidence)} · {classification.duration_ms?.toFixed?.(0) ?? "–"} ms
          </div>
          {result.is_stub && <span className="demo-tag">Demo data — not an identification</span>}
          <dl className="metric-list result-metrics">
            <Metric label="Family" value={result.family} />
            <Metric label="Category" value={result.category} />
            <Metric label="Conservation" value={result.conservation_status} />
          </dl>
          {result.short_notes && <p className="side-copy">{result.short_notes}</p>}
          {result.sources && result.sources.length > 0 && (
            <p className="side-source">
              Source: {result.sources.join("; ")}
            </p>
          )}
          {saveState === "saving" && <p>Saving…</p>}
          {saveState === "saved" && <p className="side-copy side-copy-success">Saved to library.</p>}
        </div>
      </aside>
    );
  }

  if (panelState === "uncertain") {
    return (
      <aside className="scan-side">
        <div className="side-header">Not confident</div>
        <div className="side-body">
          <p>
            The classifier could not accept this view ({pct(result.confidence)}). No species will be
            forced.
          </p>
          {(result.suggestions || []).map((suggestion) => (
            <div className="suggestion-row" key={suggestion.scientific_name}>
              <span>
                {suggestion.common_name}
                <div className="sci">
                  {suggestion.scientific_name}
                </div>
              </span>
              <span className="mono">{pct(suggestion.confidence)}</span>
            </div>
          ))}
          {result.short_notes && <p className="side-copy">{result.short_notes}</p>}
          <p className="side-copy">
            Try another angle — a clearer leaf, flower, fruit, bark, or whole-plant view.
          </p>
        </div>
      </aside>
    );
  }

  if (panelState === "error") {
    return (
      <aside className="scan-side">
        <div className="side-header">Identification failed</div>
        <div className="side-body">
          <p className="scan-error">{result.error}</p>
          <p>Retake the scan or try another angle.</p>
        </div>
      </aside>
    );
  }

  return <QualityPanel snapshot={snapshot} />;
}

function QualityPanel({ snapshot }) {
  const quality = snapshot ? snapshot.quality : null;
  const detections = snapshot ? snapshot.detections : [];
  const selected =
    snapshot && snapshot.selected_index != null ? detections[snapshot.selected_index] : null;
  const targetType = selected ? formatDetectorLabel(selected.label) : "None yet";

  return (
    <aside className="scan-side">
      <div className="side-header">Guidance</div>
      <div className="side-body">
        {!snapshot && <p>Connecting to the scan service…</p>}
        {snapshot && snapshot.error && <p className="scan-error">{snapshot.error}</p>}
        {snapshot && (
          <dl className="metric-list">
            <Metric label="Target" value={targetType} />
            <Metric
              label="Stability"
              value={`${snapshot.stable_checks}/${snapshot.required_checks || "–"} checks`}
            />
            <Metric
              label="Focus"
              value={quality ? (quality.ready ? "Ready" : "Improve") : "–"}
            />
            <Metric label="Exposure" value={quality ? describeExposure(quality) : "–"} />
            <Metric
              label="Target size"
              value={quality ? `${quality.target_width}×${quality.target_height} px` : "–"}
            />
          </dl>
        )}
        {quality && quality.reasons && quality.reasons.length > 0 && (
          <ul className="reason-list">
            {quality.reasons.map((reason) => (
              <li key={reason}>{prettifyReason(reason)}</li>
            ))}
          </ul>
        )}
        {quality && quality.hint && <p className="side-copy">{quality.hint}</p>}
      </div>
    </aside>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric-row">
      <dt>{label}</dt>
      <dd>{value ?? "–"}</dd>
    </div>
  );
}

function describeExposure(quality) {
  if (typeof quality.saturated_fraction !== "number") return "–";
  if (quality.saturated_fraction > 0.05) return "Too bright";
  if (quality.mean_luma < 40) return "Too dark";
  return "Usable";
}

function prettifyReason(reason) {
  return String(reason).replace(/[_-]+/g, " ");
}

function formatDetectorLabel(label) {
  if (!label) return "None yet";
  const spaced = String(label).replace(/-/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
