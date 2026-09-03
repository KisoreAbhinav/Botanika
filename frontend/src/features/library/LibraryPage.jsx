import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteLibraryRecord, fetchLibrary, updateLibraryNote } from "../../platform/api.js";

export function LibraryPage({ notify }) {
  const [records, setRecords] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [categoriesFromApi, setCategoriesFromApi] = useState([]);
  const [error, setError] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [category, setCategory] = useState("all");
  const [sort, setSort] = useState("recent");
  const [detailsId, setDetailsId] = useState(null);
  const [noteDrafts, setNoteDrafts] = useState({});
  const [savingNoteId, setSavingNoteId] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchLibrary();
      setRecords(data.records || []);
      setCoverage(data.coverage || null);
      setCategoriesFromApi(data.categories || []);
      setError(null);
    } catch (caught) {
      setError(caught.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const entries = useMemo(() => groupRecords(records), [records]);
  const categories = categoriesFromApi.length
    ? categoriesFromApi
    : [...new Set(entries.map((entry) => entry.category).filter(Boolean))].sort();
  const visibleEntries = entries
    .filter((entry) => category === "all" || entry.category === category)
    .sort((left, right) => sort === "name"
      ? left.common_name.localeCompare(right.common_name)
      : right.newest.observed_at - left.newest.observed_at);
  const details = entries.find((entry) => entry.species_id === detailsId) || null;

  const onDelete = async (record) => {
    if (confirmId !== record.id) {
      setConfirmId(record.id);
      return;
    }
    setConfirmId(null);
    try {
      await deleteLibraryRecord(record.id);
      notify("Observation deleted.", "success");
      await load();
    } catch (caught) {
      notify(caught.message, "error");
    }
  };

  const onSaveNote = async (record) => {
    setSavingNoteId(record.id);
    try {
      const note = noteDrafts[record.id] ?? record.note ?? "";
      await updateLibraryNote(record.id, note);
      notify("Observation note saved.", "success");
      await load();
    } catch (caught) {
      notify(caught.message, "error");
    } finally {
      setSavingNoteId(null);
    }
  };

  return (
    <div className="library">
      <div className="library-toolbar">
        <strong>Library</strong>
        <span className="count">{entries.length} species · {records ? records.length : "–"} observations</span>
        <label>
          <span className="visually-hidden">Filter category</span>
          <select value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="all">All categories</option>
            {categories.map((value) => <option value={value} key={value}>{value}</option>)}
          </select>
        </label>
        <label>
          <span className="visually-hidden">Sort library</span>
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="recent">Newest first</option>
            <option value="name">Name A–Z</option>
          </select>
        </label>
        <a className="btn quiet" href="/api/v1/library/export" download="botanika-library-export.zip">Export</a>
      </div>

      <section className="coverage-panel" aria-label="Coverage summary">
        <div className="coverage-title">Local coverage</div>
        <div className="coverage-note">{coverage?.message || "Location unavailable — discoveries are still saved."}</div>
        <div className="coverage-totals">
          <span>Species: <strong>{entries.length}</strong></span>
          <span>Observations: <strong>{records ? records.length : "–"}</strong></span>
          <span>Storage: <strong>{error ? "Unavailable" : "Ready"}</strong></span>
        </div>
      </section>

      <div className="library-list" aria-label="Saved discoveries">
        {error && <div className="empty-state scan-error">{error}</div>}
        {!error && records && records.length === 0 && (
          <div className="empty-state">No discoveries saved yet. Open Scan, hold a plant steady, and choose Save to Library.</div>
        )}
        {visibleEntries.map((entry) => (
          <div className={`library-row ${priorityClass(entry)}`} key={entry.species_id}>
            <img className="thumb" src={mediaUrl(entry.newest, true)} alt={`Newest saved crop of ${entry.common_name}`} />
            <span className="category-symbol" aria-label={priorityLabel(entry)} />
            <div className="names">
              <div className="common">{entry.common_name}</div>
              <div className="sci">{entry.scientific_name}</div>
            </div>
            <div className="meta"><div>{entry.observations.length} observation(s)</div><div>{formatTime(entry.newest.observed_at)}</div></div>
            <button type="button" className="btn quiet" onClick={() => setDetailsId(entry.species_id)}>Details</button>
          </div>
        ))}
      </div>

      {details && (
        <section className="library-dialog" role="dialog" aria-modal="true" aria-label={`${details.common_name} details`}>
          <div className="dialog-head">
            <div><div className="species-name">{details.common_name}</div><div className="species-sci">{details.scientific_name}</div></div>
            <button type="button" className="btn quiet" onClick={() => setDetailsId(null)}>Close</button>
          </div>
          <div className="dialog-scroll">
            <p>{details.short_notes}</p>
            <dl>
              <div className="metric-row"><dt>Family</dt><dd>{details.family}</dd></div>
              <div className="metric-row"><dt>Category</dt><dd>{details.category}</dd></div>
              <div className="metric-row"><dt>Native status</dt><dd>{details.native_status}</dd></div>
              <div className="metric-row"><dt>Conservation</dt><dd>{details.conservation_status}</dd></div>
            </dl>
            <p><strong>Ecology:</strong> {details.ecology}</p>
            <div className="source-list">
              <strong>Sources</strong>
              {(details.newest.sources || []).map((source) => <a href={source} target="_blank" rel="noreferrer" key={source}>{source}</a>)}
            </div>
            <div className="observation-list">
              {details.observations.map((record) => (
                <article className="observation" key={record.id}>
                  <img src={mediaUrl(record, true)} alt="" />
                  <div className="observation-copy">
                    <strong>{formatTime(record.observed_at)}</strong>
                    <div>confidence {formatConfidence(record.confidence)}</div>
                    <div>{record.classifier_version}</div>
                    <textarea
                      className="note-input"
                      value={noteDrafts[record.id] ?? record.note ?? ""}
                      onChange={(event) => setNoteDrafts((current) => ({ ...current, [record.id]: event.target.value }))}
                      placeholder="Add an observation note"
                      maxLength={2000}
                      aria-label={`Note for ${details.common_name} observation`}
                    />
                  </div>
                  <div className="observation-actions">
                    <button type="button" className="btn quiet" onClick={() => onSaveNote(record)} disabled={savingNoteId === record.id}>
                      {savingNoteId === record.id ? "Saving…" : "Save note"}
                    </button>
                    <button type="button" className={`btn ${confirmId === record.id ? "danger" : "quiet"}`} onClick={() => onDelete(record)}>{confirmId === record.id ? "Confirm" : "Delete"}</button>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

export function groupRecords(records) {
  if (!records) return [];
  const grouped = new Map();
  records.forEach((record) => {
    const current = grouped.get(record.species_id) || { ...record, observations: [] };
    current.observations.push(record);
    grouped.set(record.species_id, current);
  });
  return [...grouped.values()].map((entry) => {
    entry.observations.sort((left, right) => right.observed_at - left.observed_at);
    return { ...entry, newest: entry.observations[0] };
  });
}

function mediaUrl(record, thumbnail = false) {
  return thumbnail ? (record.thumbnail_url || record.crop_url || `/media/discoveries/${record.crop_filename}`) : (record.crop_url || `/media/discoveries/${record.crop_filename}`);
}

function priorityClass(entry) {
  const conservation = String(entry.conservation_status || "").toLowerCase();
  if (conservation.includes("threat") || conservation.includes("endanger")) return "priority-threat";
  if (entry.is_native || String(entry.category || "").toLowerCase().includes("native")) return "priority-native";
  return "priority-generic";
}

function priorityLabel(entry) {
  const kind = priorityClass(entry);
  if (kind === "priority-threat") return "Threatened category";
  if (kind === "priority-native") return "Native category";
  return "Generic category";
}

function formatConfidence(value) { return typeof value === "number" ? `${Math.round(value * 100)}%` : "–"; }
function formatTime(value) {
  if (!value) return "–";
  const date = new Date((value > 1e12 ? value : value * 1000));
  if (Number.isNaN(date.getTime()) || date.getFullYear() < 2020) return "Timestamp unavailable";
  return date.toLocaleString();
}
