# Library map and Vellore regional checklist — 2026-09-05

This workstream keeps the Pi classifier catalog and the regional reference
checklist separate. The classifier remains model-gated; the checklist is a
larger, read-only set used to show found/not-found coverage. It is a curated
starter list of 23 plants for the wider Vellore region, not an exhaustive flora
claim.

## Evidence and provenance

The checklist is in
[`config/catalog/vellore-regional-flora.json`](../config/catalog/vellore-regional-flora.json).
Each species has a stable ID, scientific/common names, family, native-status
wording, ecology, conservation note, aliases, sourced fact, and a source URL
with license metadata. The primary taxonomic/distribution references are the
Royal Botanic Gardens, Kew Plants of the World Online pages (POWO), for
example [Aegle marmelos](https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:770819-1/general-information),
[Cassia fistula](https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:484507-1/general-information),
[Lantana camara](https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:325686-2/general-information),
and [Neltuma juliflora (Prosopis juliflora)](https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:509505-1/general-information).

For geographic breadth context, the catalog records the checked
[GBIF Plantae Vellore-area occurrence search](https://api.gbif.org/v1/occurrence/search?taxon_key=6&decimalLatitude=12.6,13.3&decimalLongitude=78.8,79.5&limit=0&facet=speciesKey&facetMincount=1&facetLimit=300)
for 12.6–13.3 N, 78.8–79.5 E. The query returned 1,895 occurrence records
and 300 species facets on 2026-09-05. GBIF is a mediated index with
publisher-specific licenses; the catalog retains the [GBIF Data User
Agreement](https://www.gbif.org/terms/data-user) and does not treat the query
as a complete census.

## Library behavior

- `DiscoveryLibrary` still stores one observation row per accepted crop, but
  `list_grouped()` and the phone UI expose one species entry with all photos
  and observations. Repeated captures therefore do not create separate species
  cards.
- Every validated browser/GNSS position is returned under `locations` with
  latitude, longitude, accuracy, capture time, and safe Google Maps `map_url`
  and `directions_url` links. No turn-by-turn route is fabricated.
- `/api/v1/library/map` returns observation markers and a text/color legend;
  `/api/v1/library/region` returns the regional found/not-found checklist;
  `/api/v1/library/species/{species_id}` returns one grouped species entry.
- `/api/v1/library/records` includes grouped entries, markers, regional
  checklist data, source/license metadata, aliases, conservation assessments,
  and location links. The archive export continues to contain the SQLite
  positioning rows, so map coordinates survive backup/restore.
- The web client provides separate “Your captures / Vellore checklist /
  Observation map” views and renders a dependency-free schematic map that works offline;
  markers and the legend use category colors plus category text, and every
  marker can open an external map. A “Your captures / Vellore checklist” switch
  exposes found and not-found statuses without asserting classifier support for
  every regional plant.

## Verification

```text
PYTHONPATH=backend/src python -m unittest tests.unit.test_phase6_library tests.unit.test_phase6_catalog
14 tests passed

cd frontend && npm test
5 test files passed

cd frontend && npm run build
vite production build passed
```

The regional JSON is validated at load time for unique IDs/names, complete
metadata, a minimum breadth greater than the demo set, and known source/license
references. SQLite schema migration 5 adds only indexes/table safety for
position queries and preserves existing user rows.
