import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteLibraryRecord, fetchLibrary, updateLibraryNote } from "../../platform/api.js";
import { CONTROL_SHORTCUTS } from "../../app/hotkeys.js";

export function LibraryPage({ notify }) {
  const [records, setRecords] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [progress, setProgress] = useState(null);
  const [aggregate, setAggregate] = useState(null);
  const [regionalChecklist, setRegionalChecklist] = useState([]);
  const [regionalCatalog, setRegionalCatalog] = useState(null);
  const [mapData, setMapData] = useState(null);
  const [categoriesFromApi, setCategoriesFromApi] = useState([]);
  const [error, setError] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [category, setCategory] = useState("all");
  const [sort, setSort] = useState("recent");
  const [detailsId, setDetailsId] = useState(null);
  const [noteDrafts, setNoteDrafts] = useState({});
  const [savingNoteId, setSavingNoteId] = useState(null);
  const [libraryView, setLibraryView] = useState("captured");

  const load = useCallback(async () => {
    try {
      const data = await fetchLibrary();
      setRecords(data.records || []);
      setCoverage(data.coverage || null);
      setProgress(data.progress || null);
      setAggregate(data.aggregate || null);
      setRegionalChecklist(data.regional_checklist || []);
      setRegionalCatalog(data.regional_catalog || null);
      setMapData(data.map || null);
      setCategoriesFromApi(data.categories || []);
      setError(null);
    } catch (caught) {
      setError(caught.message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // The app-wide shortcuts intentionally pause inside this dialog. Escape is
  // the dialog's own close affordance, so handle it locally without allowing
  // it to navigate the underlying library page.
  useEffect(() => {
    if (!detailsId) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      setDetailsId(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detailsId]);

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
  const regionalDetails = !details
    ? regionalChecklist.find((entry) => entry.species_id === detailsId) || null
    : null;

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
        <div className="library-heading">
          <div className="eyebrow">04 / Saved discoveries</div>
          <h1>Library</h1>
        </div>
        <span className="count">{entries.length} species · {records ? records.length : "–"} observations</span>
        <div className="library-view-switch" role="group" aria-label="Library view">
          <button
            type="button"
            className={`btn ${libraryView === "captured" ? "green" : "quiet"}`}
            onClick={() => setLibraryView("captured")}
            data-hotkey={CONTROL_SHORTCUTS.libraryCaptured}
            aria-keyshortcuts={CONTROL_SHORTCUTS.libraryCaptured}
          >
            Your captures <kbd aria-hidden="true">Y</kbd>
          </button>
          <button
            type="button"
            className={`btn ${libraryView === "regional" ? "green" : "quiet"}`}
            onClick={() => setLibraryView("regional")}
            data-hotkey={CONTROL_SHORTCUTS.libraryRegional}
            aria-keyshortcuts={CONTROL_SHORTCUTS.libraryRegional}
          >
            Vellore checklist <kbd aria-hidden="true">V</kbd>
          </button>
          <button
            type="button"
            className={`btn ${libraryView === "map" ? "green" : "quiet"}`}
            onClick={() => setLibraryView("map")}
            data-hotkey={CONTROL_SHORTCUTS.libraryMap}
            aria-keyshortcuts={CONTROL_SHORTCUTS.libraryMap}
          >
            Observation map <kbd aria-hidden="true">M</kbd>
          </button>
        </div>
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
        <a
          className="btn quiet"
          href="/api/v1/library/export"
          download="botanika-library-export.zip"
          data-hotkey={CONTROL_SHORTCUTS.exportLibrary}
          aria-keyshortcuts={CONTROL_SHORTCUTS.exportLibrary}
        >
          Export <kbd aria-hidden="true">E</kbd>
        </a>
      </div>

      {libraryView === "captured" && <>
        <section className="coverage-panel" aria-label="Coverage summary">
          <div className="coverage-title">Local coverage · {formatPercent(progress?.coverage_percent ?? coverage?.coverage_percent)}</div>
          <div className="coverage-note">{coverage?.message || "Location unavailable — discoveries are still saved."}</div>
          <div className="coverage-totals">
            <span>Species: <strong>{entries.length}</strong></span>
            <span>Observations: <strong>{records ? records.length : "–"}</strong></span>
            <span>Storage: <strong>{error ? "Unavailable" : "Ready"}</strong></span>
          </div>
        </section>

        <section className="progress-panel" aria-label="Discovery progress">
          <div className="progress-panel-head">
            <strong>Catalog progress</strong>
            <span>{progress?.discovered_species ?? entries.length} / {progress?.supported_species ?? "–"} species</span>
          </div>
          <div className="progress-categories">
            {(progress?.category_progress || []).slice(0, 4).map((item) => (
              <div className="progress-category" key={item.category}>
                <span>{item.category}</span>
                <div className="progress-track"><span style={{ width: `${item.coverage_percent || 0}%` }} /></div>
                <small>{formatPercent(item.coverage_percent)}</small>
              </div>
            ))}
          </div>
          <div className="milestone-row">
            {(progress?.milestones || []).filter((item) => item.complete).slice(0, 3).map((item) => <span className="milestone" key={item.id}>✓ {item.label}</span>)}
            {aggregate?.anonymous && <span className="aggregate-note">Anonymous local summary</span>}
          </div>
        </section>
      </>}

      {libraryView === "map" && <ObservationMap mapData={mapData} />}

      {libraryView === "regional" ? (
        <RegionalChecklist
          species={regionalChecklist}
          catalog={regionalCatalog}
          onOpenDetails={(species) => setDetailsId(species.species_id)}
        />
      ) : libraryView === "map" ? null : <div className="library-list" aria-label="Saved discoveries">
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
      </div>}

      {details && (
        <section className="library-dialog" role="dialog" aria-modal="true" aria-label={`${details.common_name} details`}>
          <div className="dialog-head">
            <div><div className="species-name">{details.common_name}</div><div className="species-sci">{details.scientific_name}</div></div>
            <button
              type="button"
              className="btn quiet"
              onClick={() => setDetailsId(null)}
              aria-keyshortcuts={CONTROL_SHORTCUTS.cancelScan}
            >
              Close <kbd aria-hidden="true">Esc</kbd>
            </button>
          </div>
          <div className="dialog-scroll">
            <p>{details.short_notes}</p>
            <dl>
              <div className="metric-row"><dt>Family</dt><dd>{details.family}</dd></div>
              <div className="metric-row"><dt>Category</dt><dd>{details.category}</dd></div>
              <div className="metric-row"><dt>Native status</dt><dd>{details.native_status}</dd></div>
              <div className="metric-row"><dt>Conservation</dt><dd>{details.conservation_status}</dd></div>
              <div className="metric-row"><dt>Region</dt><dd>{details.region || "–"}</dd></div>
            </dl>
            {details.aliases?.length > 0 && <p><strong>Also called:</strong> {details.aliases.join(", ")}</p>}
            <p><strong>Ecology:</strong> {details.ecology}</p>
            <div className="source-list">
              <strong>Sources</strong>
              {(details.source_details?.length ? details.source_details : (details.newest.sources || []).map((url) => ({ url, title: url, license: "" }))).map((source) => (
                <a href={source.url} target="_blank" rel="noreferrer" key={`${source.url}-${source.title}`}>
                  {source.title || source.url}{source.publisher ? ` · ${source.publisher}` : ""}{source.license ? ` · ${source.license}` : ""}
                </a>
              ))}
            </div>
            <div className="observation-locations">
              <strong>Observation locations</strong>
              {details.locations?.length ? details.locations.map((location) => (
                <div className="location-row" key={`${location.sample_id || location.observation_id}-${location.captured_at}`}>
                  <span>{location.latitude.toFixed(5)}, {location.longitude.toFixed(5)} · ±{Math.round(location.accuracy_m)} m</span>
                  <span className="location-actions">
                    <a href={location.map_url} target="_blank" rel="noreferrer">Open map</a>
                    <a href={location.directions_url} target="_blank" rel="noreferrer">Open directions</a>
                  </span>
                </div>
              )) : <p className="muted">No accurate location was supplied for these observations.</p>}
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
      {regionalDetails && <RegionalDetailsDialog species={regionalDetails} onClose={() => setDetailsId(null)} />}
    </div>
  );
}

function ObservationMap({ mapData }) {
  const locations = mapData?.locations || [];
  const bounds = locations.reduce((result, location) => ({
    minLat: Math.min(result.minLat, Number(location.latitude)),
    maxLat: Math.max(result.maxLat, Number(location.latitude)),
    minLon: Math.min(result.minLon, Number(location.longitude)),
    maxLon: Math.max(result.maxLon, Number(location.longitude)),
  }), { minLat: Infinity, maxLat: -Infinity, minLon: Infinity, maxLon: -Infinity });
  const latEqual = bounds.maxLat === bounds.minLat;
  const lonEqual = bounds.maxLon === bounds.minLon;
  const latRange = Number.isFinite(bounds.maxLat - bounds.minLat) && !latEqual ? bounds.maxLat - bounds.minLat : 0.01;
  const lonRange = Number.isFinite(bounds.maxLon - bounds.minLon) && !lonEqual ? bounds.maxLon - bounds.minLon : 0.01;
  return (
    <section className="library-map-panel" aria-label="Discovery map">
      <div className="library-map-head">
        <div><div className="eyebrow">Observation map</div><strong>Where you found plants</strong></div>
        <span>{locations.length} mapped observation{locations.length === 1 ? "" : "s"}</span>
      </div>
      <p className="map-note">{mapData?.message || "Save a discovery with an accurate phone location to place it on the map."}</p>
      {locations.length > 0 ? (
        <div className="observation-map" role="img" aria-label="Schematic map of saved plant observation coordinates">
          <div className="map-grid" aria-hidden="true" />
          {locations.map((location, index) => {
            const left = lonEqual ? 50 : 7 + ((Number(location.longitude) - bounds.minLon) / lonRange) * 86;
            const top = latEqual ? 50 : 92 - ((Number(location.latitude) - bounds.minLat) / latRange) * 84;
            return (
              <a
                className="map-marker"
                href={location.map_url}
                target="_blank"
                rel="noreferrer"
                key={`${location.observation_id || "location"}-${location.sample_id || index}`}
                style={{ left: `${Math.max(3, Math.min(97, left))}%`, top: `${Math.max(3, Math.min(97, top))}%`, backgroundColor: location.category_color || "#6f6257" }}
                title={`${location.common_name} · ${location.category} · ${Number(location.latitude).toFixed(5)}, ${Number(location.longitude).toFixed(5)}`}
                aria-label={`Open map for ${location.common_name} at ${Number(location.latitude).toFixed(5)}, ${Number(location.longitude).toFixed(5)}`}
              >
                <span className="visually-hidden">{location.common_name}</span>
              </a>
            );
          })}
        </div>
      ) : <div className="empty-state map-empty">No mapped observations yet.</div>}
      <div className="map-legend" aria-label="Map category legend">
        {(mapData?.legend || []).map((item) => <span key={item.category}><i style={{ backgroundColor: item.color }} aria-hidden="true" />{item.label}</span>)}
      </div>
      {locations.length > 0 && <div className="map-location-list">
        {locations.map((location, index) => <a href={location.directions_url} target="_blank" rel="noreferrer" key={`${location.observation_id || "loc"}-link-${index}`}><span style={{ color: location.category_color }}>●</span> {location.common_name} · Open directions</a>)}
      </div>}
    </section>
  );
}

function RegionalChecklist({ species, catalog, onOpenDetails }) {
  return (
    <section className="regional-checklist" aria-label="Vellore regional flora checklist">
      <div className="regional-head">
        <div><div className="eyebrow">Reference coverage</div><h2>Wider Vellore region</h2></div>
        <span>{species.filter((item) => item.status === "found").length} found · {species.filter((item) => item.status !== "found").length} not found</span>
      </div>
      <p className="regional-scope">{catalog?.scope_note || "Curated regional starter checklist; not an exhaustive flora."}</p>
      {catalog?.occurrence_basis?.query_url && <p className="regional-source">Breadth context: <a href={catalog.occurrence_basis.query_url} target="_blank" rel="noreferrer">GBIF Vellore-area occurrence search</a> ({catalog.occurrence_basis.record_count || "–"} records, checked {catalog.occurrence_basis.retrieved_at || "–"}).</p>}
      <div className="regional-list">
        {species.map((item) => (
          <article className={`regional-row ${item.status === "found" ? "is-found" : "is-missing"}`} key={item.species_id}>
            <span className="regional-color" style={{ backgroundColor: item.category_color }} aria-hidden="true" />
            <div className="regional-names"><strong>{item.common_name}</strong><em>{item.scientific_name}</em><small>{item.category}</small></div>
            <span className="regional-status">{item.status === "found" ? `Found · ${item.observation_count}` : "Not found yet"}</span>
            <button type="button" className="btn quiet" onClick={() => onOpenDetails(item)}>Details</button>
            <details className="regional-facts"><summary>Quick facts</summary><p>{item.short_notes}</p><p><strong>Ecology:</strong> {item.ecology}</p><p><strong>Native status:</strong> {item.native_status}</p></details>
          </article>
        ))}
      </div>
    </section>
  );
}

function RegionalDetailsDialog({ species, onClose }) {
  return (
    <section className="library-dialog" role="dialog" aria-modal="true" aria-label={`${species.common_name} regional details`}>
      <div className="dialog-head">
        <div><div className="species-name">{species.common_name}</div><div className="species-sci">{species.scientific_name}</div></div>
        <button type="button" className="btn quiet" onClick={onClose}>Close <kbd aria-hidden="true">Esc</kbd></button>
      </div>
      <div className="dialog-scroll">
        <p className="regional-status-detail">{species.status === "found" ? `Found in your library · ${species.observation_count} observation(s)` : "Not found in your library yet"}</p>
        <p>{species.short_notes}</p>
        <dl>
          <div className="metric-row"><dt>Family</dt><dd>{species.family}</dd></div>
          <div className="metric-row"><dt>Category</dt><dd>{species.category}</dd></div>
          <div className="metric-row"><dt>Native status</dt><dd>{species.native_status}</dd></div>
          <div className="metric-row"><dt>Conservation</dt><dd>{species.conservation_status}</dd></div>
          <div className="metric-row"><dt>Region</dt><dd>{species.region || "Vellore region, Tamil Nadu"}</dd></div>
        </dl>
        {species.aliases?.length > 0 && <p><strong>Also called:</strong> {species.aliases.join(", ")}</p>}
        <p><strong>Ecology:</strong> {species.ecology}</p>
        {species.knowledge?.length > 0 && <div className="source-list"><strong>Sourced facts</strong>{species.knowledge.map((fact, index) => <p key={`${fact.source_id}-${index}`}>{fact.text}</p>)}</div>}
        <div className="source-list"><strong>Sources and licenses</strong>{(species.source_details || []).map((source) => <a href={source.url} target="_blank" rel="noreferrer" key={source.source_id}>{source.title} · {source.publisher} · {source.license}</a>)}</div>
        {species.locations?.length > 0 && <div className="observation-locations"><strong>Observation locations</strong>{species.locations.map((location, index) => <div className="location-row" key={`${location.sample_id || index}-${location.captured_at}`}><span>{Number(location.latitude).toFixed(5)}, {Number(location.longitude).toFixed(5)}</span><span className="location-actions"><a href={location.map_url} target="_blank" rel="noreferrer">Open map</a><a href={location.directions_url} target="_blank" rel="noreferrer">Open directions</a></span></div>)}</div>}
      </div>
    </section>
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
    const locations = entry.observations.flatMap((observation) => observation.locations || []);
    return {
      ...entry,
      newest: entry.observations[0],
      locations,
      location_count: locations.length,
    };
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
function formatPercent(value) { return typeof value === "number" ? `${Math.round(value)}%` : "–"; }
function formatTime(value) {
  if (!value) return "–";
  const date = new Date((value > 1e12 ? value : value * 1000));
  if (Number.isNaN(date.getTime()) || date.getFullYear() < 2020) return "Timestamp unavailable";
  return date.toLocaleString();
}
