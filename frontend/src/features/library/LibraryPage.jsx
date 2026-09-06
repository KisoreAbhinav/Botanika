import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
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
  const mapElement = useRef(null);
  const [tileUnavailable, setTileUnavailable] = useState(() => typeof navigator !== "undefined" && navigator.onLine === false);
  const locations = useMemo(() => (mapData?.locations || []).filter((location) => (
    Number.isFinite(Number(location.latitude)) && Number.isFinite(Number(location.longitude))
  )), [mapData]);

  useEffect(() => {
    const setOffline = () => setTileUnavailable(true);
    const setOnline = () => setTileUnavailable(false);
    window.addEventListener("offline", setOffline);
    window.addEventListener("online", setOnline);
    return () => {
      window.removeEventListener("offline", setOffline);
      window.removeEventListener("online", setOnline);
    };
  }, []);

  useEffect(() => {
    if (!mapElement.current) return undefined;
    setTileUnavailable(typeof navigator !== "undefined" && navigator.onLine === false);
    const map = L.map(mapElement.current, {
      // The checklist is scoped to Vellore, so an empty library still opens
      // on a useful local street map instead of hiding the map entirely.
      center: [12.9165, 79.1325],
      zoom: 12,
      minZoom: 2,
      maxZoom: 19,
      zoomControl: true,
      scrollWheelZoom: true,
      attributionControl: true,
    });
    const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>',
    });
    tiles.on("tileerror", () => setTileUnavailable(true));
    tiles.addTo(map);

    const points = locations.map((location) => [Number(location.latitude), Number(location.longitude)]);
    if (points.length === 1) map.setView(points[0], 16);
    else if (points.length > 1) {
      const bounds = L.latLngBounds(points);
      map.fitBounds(bounds, { padding: [28, 28], maxZoom: 17 });
    }

    const groups = groupNearbyLocations(locations);
    groups.forEach((group) => group.forEach((location, index) => {
      const position = spreadLocation(location, index, group.length);
      const marker = L.marker(position, {
        icon: L.divIcon({
          className: "map-marker observation-marker-icon",
          html: "<span aria-hidden=\"true\"></span>",
          iconSize: [44, 44],
          iconAnchor: [22, 22],
          tooltipAnchor: [0, -22],
        }),
        riseOnHover: true,
        keyboard: true,
        title: `${location.common_name || "Saved observation"} · ${formatCoordinates(location)}`,
      }).addTo(map);
      const element = marker.getElement();
      if (element) {
        element.style.setProperty("--marker-color", location.category_color || "#6f6257");
        // Keep each marker independently discoverable to keyboard and browser
        // tooling even when Leaflet has fanned several markers from one fix.
        element.dataset.testid = "map-marker";
        element.setAttribute("role", "button");
        element.setAttribute("aria-label", `${location.common_name || "Saved observation"} at ${formatCoordinates(location)}`);
        element.setAttribute("href", markerHref(location, index));
      }
      marker.bindTooltip(location.common_name || "Saved observation", {
        permanent: true,
        direction: "top",
        className: "map-label",
        offset: [0, -11],
      });
      marker.bindPopup(createObservationPopup(location));
    }));

    // Leaflet measures its container during construction. The library panel
    // can finish its flex layout a frame later, especially on the kiosk.
    const resize = window.setTimeout(() => map.invalidateSize(), 0);
    return () => {
      window.clearTimeout(resize);
      tiles.off();
      map.remove();
    };
  }, [locations]);

  return (
    <section className="library-map-panel" aria-label="Discovery map">
      <div className="library-map-head">
        <div><div className="eyebrow">Observation map</div><strong>Where you found plants</strong></div>
        <span>{locations.length} mapped observation{locations.length === 1 ? "" : "s"}</span>
      </div>
      <p className="map-note">{mapData?.message || "Save a discovery with an accurate phone location to place it on the map."}</p>
      {tileUnavailable && <div className="map-offline" role="status">Street map tiles are unavailable offline. Saved observations are listed below.</div>}
      <div className="observation-map" ref={mapElement} data-testid="observation-map" aria-label="Interactive street map of saved plant observations" />
      <div className="map-legend" aria-label="Map category legend">
        {(mapData?.legend || []).map((item) => <span key={item.category}><i style={{ backgroundColor: item.color }} aria-hidden="true" />{item.label}</span>)}
      </div>
      {locations.length > 0 && <div className="map-location-list">
        {locations.map((location, index) => <div className="map-location-row" key={`${location.observation_id || "loc"}-link-${index}`}>
          <a
            className="map-list-marker map-marker"
            data-testid="map-marker"
            href={directionsUrl(location)}
            target="_blank"
            rel="noreferrer"
            style={{ backgroundColor: location.category_color || "#6f6257" }}
            title={`${location.common_name || "Saved observation"} · ${formatCoordinates(location)}`}
            aria-label={`${location.common_name || "Saved observation"} at ${formatCoordinates(location)}`}
          />
          <span className="map-location-name">{location.common_name || "Saved observation"}{location.scientific_name && <em className="map-location-species"> · {location.scientific_name}</em>}</span>
          <span className="map-location-coordinates">{formatCoordinates(location)}</span>
          <a className="btn quiet map-directions" href={directionsUrl(location)} target="_blank" rel="noreferrer">Walking directions</a>
        </div>)}
      </div>}
    </section>
  );
}

function groupNearbyLocations(locations) {
  const groups = new Map();
  locations.forEach((location) => {
    // Four decimal places is roughly an 11 m cell around Vellore. This keeps
    // coincident GPS fixes selectable while also separating near misses.
    const key = `${Number(location.latitude).toFixed(4)}:${Number(location.longitude).toFixed(4)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(location);
  });
  return [...groups.values()];
}

function spreadLocation(location, index, count) {
  if (count < 2) return [Number(location.latitude), Number(location.longitude)];
  const radius = 0.00012;
  const angle = (index / count) * Math.PI * 2;
  const latitude = Number(location.latitude) + Math.sin(angle) * radius;
  const longitude = Number(location.longitude) + (Math.cos(angle) * radius) / Math.max(0.2, Math.cos(Number(location.latitude) * Math.PI / 180));
  return [latitude, longitude];
}

function formatCoordinates(location) {
  return `${Number(location.latitude).toFixed(5)}, ${Number(location.longitude).toFixed(5)}`;
}

function directionsUrl(location) {
  if (location.directions_url) return location.directions_url;
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${location.latitude},${location.longitude}`)}&travelmode=walking&dir_action=navigate`;
}

function markerHref(location, index) {
  const target = location.map_url || directionsUrl(location);
  const token = location.observation_id || location.sample_id || index;
  return `${target}${target.includes("?") ? "&" : "?"}botanika_observation=${encodeURIComponent(token)}`;
}

function createObservationPopup(location) {
  const popup = document.createElement("div");
  popup.className = "map-popup";
  const title = document.createElement("strong");
  title.textContent = location.common_name || "Saved observation";
  popup.appendChild(title);
  if (location.scientific_name) {
    const scientific = document.createElement("em");
    scientific.textContent = location.scientific_name;
    popup.appendChild(scientific);
  }
  const metadata = document.createElement("span");
  metadata.textContent = `${location.category || "Observation"} · ${formatCoordinates(location)}`;
  popup.appendChild(metadata);
  const actions = document.createElement("div");
  actions.className = "map-popup-actions";
  [[directionsUrl(location), "Walking directions"], [location.map_url, "Open map"]].forEach(([href, label]) => {
    if (!href) return;
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = label;
    actions.appendChild(link);
  });
  popup.appendChild(actions);
  return popup;
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
