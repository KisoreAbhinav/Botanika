# Phase 6 Implementation Report — Species, Knowledge, and Discovery Library

**Started:** 2026-09-02
**Last verified:** 2026-09-03
**Scope:** `BOTANIKA_PI_APP_IMPLEMENTATION_PROMPT.md` → Phase 6 (SOLO)
**Status:** Safe baseline implemented and verified; field-model exit gate remains explicitly deferred

## Delivered

### Catalog and provenance

The frozen starter region is **India — starter garden and field-edge catalog**.
It contains seven stable IDs:

| Stable ID | Common name | Family | Category | Conservation record |
| --- | --- | --- | --- | --- |
| `in:ficus-benghalensis` | Banyan | Moraceae | Indian native | Not threatened in the Kew profile |
| `in:ficus-religiosa` | Sacred fig | Moraceae | Indian native | Not assessed in this starter record |
| `in:artocarpus-heterophyllus` | Jackfruit | Moraceae | Western Ghats native | Not assessed in this starter record |
| `in:ocimum-tenuiflorum` | Holy basil | Lamiaceae | Indian native | Least concern in the Kew profile |
| `in:moringa-oleifera` | Drumstick tree | Moringaceae | Indian native | LC, linked to an IUCN assessment |
| `in:jasminum-sambac` | Arabian jasmine | Oleaceae | Indian native | Not assessed in this starter record |
| `in:syzygium-microphyllum` | Small-leaved Syzygium | Myrtaceae | Western Ghats native | EN, linked to an IUCN assessment |

The source records, aliases, native status, ecology, assessments, image-view
requirements, and reviewed fact chunks are stored in
[`config/catalog/india-starter-species.json`](../config/catalog/india-starter-species.json).
Each fact now cites the exact Plants of the World Online taxon/profile page or
IUCN assessment that supports it, with the applicable source/license record.
Image-view references retain the Wikimedia Commons provider record, but no
image is represented as curated until its exact URL, hash, observation ID, and
per-file license are added. The runtime ships no remote image dependency.

`KnowledgeStore` validates the catalog digest, seeds normalized SQLite tables,
indexes reviewed chunks with FTS5, returns source citations, and uses an exact
abstention response when evidence is insufficient. It never invents a species
identity from a missing fact.

### Classifier and runtime boundary

[`india-starter-feature-v1.json`](../models/plant_classifier/india-starter-feature-v1.json)
is a checksum-verified, CPU-friendly OpenCV/NumPy artifact using a fixed 96×96
BGR preprocessing path and 14 colour/texture/shape features. Its immutable
seven-class label map is checked against the catalog before inference.

`CompactSpeciesClassifier` is the normal `AppSettings` classifier. It returns
catalog metadata on accepted results only after the release contains held-out
macro/per-class metrics, measured unknown-rejection trials, and Pi latency,
memory, and thermal evidence. The current baseline therefore returns an
explicit non-stub uncertain result with suggestions even when its feature
centroid matches. It cannot save an unvalidated guess to the discovery library.
The old deterministic classifier remains reachable only through the explicit
Phase 5 compatibility configuration used by legacy fixtures; it is not used by
the normal runtime.

The compact artifact is an engineered baseline, not a claim of field-trained
reliability. Its capability is deliberately unavailable for production
identification while metadata records `macro_f1: null`, an unmeasured
unknown-rejection rate, and an unmeasured Pi benchmark. Readiness is degraded
until that evidence exists. The
reference image manifest is also intentionally empty until licensed assets,
per-file hashes, observation IDs, and location-grouped splits are supplied:
[`india-starter-image-manifest.json`](../data/seed/india-starter-image-manifest.json).

### SQLite library and API

The numbered SQLite migrations create catalog, alias, category, source,
assessment, ecology, knowledge, model-release, positioning, discovery, image,
and quota-support tables. The authoritative `DiscoveryLibrary`:

- accepts only accepted non-stub results and copies only the crop;
- verifies crop hashes, creates thumbnails, and removes interrupted or orphaned
  files;
- deduplicates repeated saves within the configured time window;
- keeps multiple observations grouped under one species;
- supports notes, category filtering, confirmed delete, quotas, export, backup,
  and failure-atomic verified restore while knowledge and library services share
  the live DB;
- accepts optional position samples but does not require them.

New routes include `/species`, `/species/search`, `/species/{species_id}`,
`/knowledge/search`, `/chat`, library note/export/restore operations, and the
existing scan routes now use the normal compact classifier. The 800×480 Library
shows local coverage totals and explicitly says when position is unavailable.
Ask answers are grounded in local reviewed chunks with source links and a
visible evidence-insufficient state.

## Verification

- Python: **88 tests passed** with
  `PYTHONPATH=backend/src .venv/bin/python -m unittest discover -s tests`.
- Frontend: **3 Node UI-state tests passed** with `npm test`.
- Frontend production build: `npm run build` succeeded.
- Existing Phase 5 Chromium states and screenshots: `tools/verify_phase5_ui.py` passed.
- Phase 6 Chromium states and screenshots: `tools/verify_phase6_ui.py` passed at
  exactly 800×480 for the honest baseline-abstention state, grouped
  library/details, and grounded Ask. Evidence is under
  [`docs/evidence/phase6`](evidence/phase6/).
- A simultaneous `KnowledgeStore` + `DiscoveryLibrary` smoke test passed
  save, dedupe, grouping, export, delete, restore, FTS retrieval, and compact
  classifier startup.

## Goal check and remaining gate

The catalog/schema, normal non-stub runtime path, deployment gate, unknown
rejection, label join, exact citations, grouped crop-only library, thumbnails,
notes/API surface, categories, failure-atomic export/delete/backup/restore,
unavailable-position behavior, and 800×480 UI are implemented and tested.

The full Phase 6 exit gate is not claimed yet because this workspace contains
no curated licensed field-image observations and has not run a physical Pi
latency/memory/thermal benchmark. Those are data and hardware acceptance
requirements, not values that can be responsibly fabricated in a code-only
workspace. Until they are supplied, the runtime enforces abstention, reports
the classifier unavailable for production identification, disables accepted
library saves, and keeps readiness degraded.
