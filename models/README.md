# Model asset boundary

Each model family gets an isolated directory containing a model card, labels,
preprocessing contract, checksums, license/provenance, benchmark data, and the
runtime artifact. Large weights are intentionally ignored by Git.

The campus plant/tree path uses the machine-local MobileNetV2 encoder described
by [`config/models/mobilenetv2-campus-embedding.json`](../config/models/mobilenetv2-campus-embedding.json)
and the checksummed few-shot artifact produced by
[`tools/enroll_plants.py`](../tools/enroll_plants.py). Five photos per label
are enough to create provisional suggestions, never enough by themselves to
claim production validation. Independent held-out and unknown images are
required before the app may save a campus identification.

Phase 2 currently uses the COCO-pretrained Ultralytics YOLO11n ONNX artifact.
Its tracked contract is
[`config/models/yolo11n-coco.json`](../config/models/yolo11n-coco.json); the
11 MiB artifact belongs at `models/detectors/yolo11n.onnx` and is ignored by
Git. The application verifies the manifest checksum before loading it and does
not download model files at runtime.
