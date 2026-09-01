# Model asset boundary

Each model family gets an isolated directory containing a model card, labels,
preprocessing contract, checksums, license/provenance, benchmark data, and the
runtime artifact. Large weights are intentionally ignored by Git.

Phase 2 currently uses the COCO-pretrained Ultralytics YOLO11n ONNX artifact.
Its tracked contract is
[`config/models/yolo11n-coco.json`](../config/models/yolo11n-coco.json); the
11 MiB artifact belongs at `models/detectors/yolo11n.onnx` and is ignored by
Git. The application verifies the manifest checksum before loading it and does
not download model files at runtime.
