# Botanika Phase 4 Classifier and Pipeline Report — 2026-09-01

**Decision:** Phase 4 implementation and automated integration pass. The
classifier contract, deterministic response paths, and Phase 3 crop handoff
are complete. The classifier output is deliberately fake and is never evidence
of species identification.

## Implementation

- `vision/classification/classifier.py` defines the input/output contract,
  accepted/uncertain/error/cancelled/malformed-image statuses, cancellation
  token, and schema validation.
- `DummyClassifier` accepts a crop `Path` or BGR `numpy` image and returns
  deterministic demo data with stable ID, common/scientific name, family,
  category, conservation field, confidence, notes, source marker, and version
  `stub-phase-4`.
- Every dummy response carries `is_stub: true`, `demo_label: DEMO DATA`, and
  the visible diagnostic formatter cannot omit that warning. Uncertain results
  do not expose a species ID and provide suggestions only.
- `ClassificationPipeline` passes a successful Phase 3 crop path directly to
  the classifier, preserving the crop path, content hash, request ID, start/end
  times, duration, and result in one `ClassificationRun`.
- `tools/run_phase4.py` reuses the existing camera/detector/lock-on loop and
  prints one local diagnostic result for each accepted crop. `--demo-case`
  selects deterministic accepted, uncertain, error, or cancelled output.

No model was downloaded, trained, or presented as validated.

## Automated evidence

```text
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
Ran 37 tests ... OK

.venv/bin/python -m py_compile \
  backend/src/botanika/vision/classification/*.py \
  tools/run_phase4.py \
  tests/unit/test_classification.py \
  tests/integration/test_phase4_pipeline.py

git diff --check
```

The integration fixture drives camera frame acquisition, generic detection,
stable/quality lock, crop-only persistence, and exactly one stub classification.
Contract tests cover deterministic output, direct crop-path invocation,
uncertainty abstention, classifier error, cancellation, malformed images,
unexpected classifier exceptions, and the visible demo warning.

## Pi integration status

The physical exit-gate trial remains pending under
[`DEFERRED_OPERATOR_ACCEPTANCE.md`](DEFERRED_OPERATOR_ACCEPTANCE.md). It must
hold an eligible object steady on the Pi, verify one crop enters the stub, and
inspect the displayed result. Until Phase 6 replaces the stub, the result must
remain labelled `DEMO DATA` and must not be saved or described as a real species
identification.
