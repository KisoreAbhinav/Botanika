# Local model asset review — 2026-09-04

This record separates a model's published scope from Botanika's seven-species
catalog and records the exact artifacts installed on the Pi. Model weights are
machine-local and are not committed to Git; the tracked manifests carry the
checksums and source/license contract.

## Seven-species plant classifier: unavailable as a trustworthy pretrained artifact

Botanika's catalog is the following exact set: *Ficus benghalensis* (Banyan),
*Ficus religiosa* (Sacred fig), *Artocarpus heterophyllus* (Jackfruit),
*Ocimum tenuiflorum* (Holy basil), *Moringa oleifera* (Drumstick tree),
*Jasminum sambac* (Arabian jasmine), and *Syzygium microphyllum* (Small-leaved
Syzygium).

The reviewed candidates did not pass the exact-label, scope, and Pi-runtime
gate:

| Candidate | Published contract | Result |
| --- | --- | --- |
| [Plants Computer Vision Model](https://universe.roboflow.com/plants-mcgil/plants-9wp6a) | Public Domain; 30 classes, 172-image dataset; includes Moringa, Jackfruit, *Ficus religiosa*, and *Ocimum tenuiflorum* but not *Ficus benghalensis* or *Syzygium microphyllum*, and does not publish an exact seven-class Pi artifact. | Rejected: incomplete catalog and too little documented data for a field claim. |
| [PlantNet-300K](https://github.com/plantnet/PlantNet-300K) | 1,081-class plant dataset/model family; its broad class contract is not Botanika's seven classes and requires a separate runtime/model selection. | Rejected: incompatible label contract. |
| [Google Coral iNat plant labels](https://raw.githubusercontent.com/google-coral/test_data/master/inat_plant_labels.txt) | Official 2,102-label TFLite test-data label list, not a seven-class classifier release. | Rejected: no documented exact seven-class artifact. |
| [PlantCLEF 2024 release](https://zenodo.org/records/10848263) | Large 7,806-class southwest-European ViT-B/14 task, not the Indian starter catalog or a Pi-5-sized seven-class artifact. | Rejected: incompatible scope and footprint. |
| [iNaturalist developers](https://www.inaturalist.org/pages/developers) | Hosted/API identification service and taxon model documentation; no reviewed local seven-class weight artifact was found. | Rejected: no offline artifact to checksum/install. |

The tracked [starter classifier manifest](../models/plant_classifier/india-starter-feature-v1.json)
therefore remains the honest engineered feature baseline (`opencv-numpy`, no
third-party weights). It is not promoted to a pretrained field classifier and
its metrics remain unmeasured. A future exact seven-class model must publish a
license, class map, Pi-compatible artifact, and held-out field evaluation
before this gate is changed.

## Weed detector: installed, but only as a scoped experimental beta

The installed artifact is the `broadleaf-yolo11n-640.onnx` file from
[Llama Farm's broadleaf weed detector](https://huggingface.co/llama-farm/broadleaf-weed-detector),
at repository revision `33475e9`, with the direct [pinned ONNX download](https://huggingface.co/llama-farm/broadleaf-weed-detector/resolve/33475e9/weights/broadleaf-yolo11n-640.onnx?download=true).
The release card states CC-BY-4.0 weights, one output class (`weed`), 640×640
input, and a Wisconsin turf/lawn, ground-level UGV evaluation domain. It says
small weeds should use 3×2 overlapping tiles. Botanika's current service
accepts multiple boxes but performs one submitted-frame pass; it does not
claim species identity or Indian-crop accuracy.

The artifact is pinned in [config/weed/phase9-beta.json](../config/weed/phase9-beta.json):

- SHA-256: `5e9e6bd6b83dd4c7e483baeed05d8847f2b69e3fc97a301bef354e22c7c1316b`
- ONNX contract observed on the Pi: input `[1,3,640,640]`, output `[1,5,8400]`,
  class map `{0: weed}`; ONNX Runtime CPU session loaded successfully.
- The exported ONNX metadata includes an `AGPL-3.0` Ultralytics license field,
  while the release card explicitly grants CC-BY-4.0 for model weights. The
  manifest records this discrepancy; redistribution should be reviewed before
  shipping the artifact outside this machine.

The model-card metrics are recorded as publisher-reported only (not Botanika
validation): YOLO11n held-out mAP@50 0.960, mAP@50–95 0.684, precision 0.931,
recall 0.885; Wisconsin-lawn frame detection rate 0.78 full-frame and 0.86
tiled. The beta must remain visibly scoped to `weed`, Wisconsin turf/lawn, and
experimental use until local acceptance data exists.

## Local instruct model: installed and evidence-gated

The installed GGUF is [Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF),
file `qwen2.5-1.5b-instruct-q4_k_m.gguf`, under Apache-2.0. Its SHA-256 is
`6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` and its
size is 1,117,320,736 bytes. The Pi uses the official
[llama.cpp b10797 arm64 release](https://github.com/ggml-org/llama.cpp/releases/tag/b10797),
whose downloaded archive SHA-256 is
`2ecebe067cae4b8ceea858e0fbad793fca2cba5203acd039ccee564ae4ecd455`.

The runtime is configured explicitly through `BOTANIKA_LLAMA_CLI_PATH`, uses
single-turn non-interactive CLI mode, and strips the CLI's human banner before
the existing citation validator. Qwen loaded and generated on the Pi, but the
benchmark prompt did not consistently emit the required local chunk ID; those
outputs are rejected rather than relabeled as grounded. The deterministic
extractive answer remains the authoritative fallback. See the tracked
benchmark evidence under `docs/evidence/phase9/` after the service benchmark
is rerun.
