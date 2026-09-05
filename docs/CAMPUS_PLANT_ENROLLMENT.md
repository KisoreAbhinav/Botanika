# Campus plant and tree recognition

Botanika now supports an extensible few-shot index for photographs collected
on campus.  It does not train a new neural network on the Pi.  Instead it uses
the frozen **MobileNetV2 1.0 fp32** ONNX model from the official ONNX Model
Zoo as a CPU visual encoder, then combines a label prototype and nearest
enrolled-photo similarity.  The encoder is small enough for a Pi 5 and is
licensed Apache-2.0.  The exact source, model-card URL, SHA-256, preprocessing,
and the important limitation that this is an ImageNet-trained, non-plant-specific
feature vector are
in [`config/models/mobilenetv2-campus-embedding.json`](../config/models/mobilenetv2-campus-embedding.json).

The app never downloads a model at startup.  The operator installs the
machine-local file at:

```text
/opt/botanika/models/embeddings/mobilenetv2-10-embedding.onnx
```

For the reviewed campus upload in this repository, run the preparation step
before enrollment:

```bash
cd /opt/botanika
.venv/bin/python tools/prepare_campus_enrollment.py \
  --archive "Campus Flora.zip" \
  --manifest data/campus/enrollment-manifest.json \
  --output data/campus/enrollment \
  --replace
```

The manifest records the archive checksum and a SHA-256 for every image. The
preparer checks ZIP CRCs, rejects unsafe member paths, requires every image to
be declared exactly once as accepted or excluded, verifies those per-file
hashes, and writes only accepted files below the ignored `train/` tree. Raw
operator photos and the archive are intentionally not source-controlled.

## Dataset convention

For the first pass, five or more photos per campus label are useful.  Use a
folder for every name you want displayed; both plants and trees are ordinary
labels:

```text
campus-plants/
├── Neem/
│   ├── photo-01.jpg
│   ├── photo-02.jpg
│   └── ...
├── Rain tree/
│   ├── photo-01.jpg
│   └── ...
└── Ashoka tree/
    └── ...
```

For a release-quality evaluation, keep training, independent held-out, and
unknown images in one bundle:

```text
campus-bundle/
├── train/<label>/*.jpg
├── held-out/<label>/<plant-or-session>/*.jpg
└── unknown/*.jpg
```

The nested plant/session directory is important.  Five views of one tree are
excellent enrollment examples but are not five independent accuracy samples.
The tool rejects exact duplicates and perceptual near-duplicates, but it
cannot infer whether two photographs show the same physical plant.  Keep the
held-out plant/session separate yourself.  Record image licenses/consent in
your own manifest; the tool records source hashes and never invents rights.

If a folder name exactly matches a reviewed name or alias in the immutable
model catalog or the larger Vellore regional reference catalog, the artifact
records a catalog join and the normal sourced facts may be shown. The runtime
also records the catalog version and digest used for that join and fails closed
if the reference catalog changes underneath the artifact. Cultivar and
horticultural-group labels (for example, `Alpinia zerumbet 'Variegata'`,
`Tradescantia pallida 'Purpurea'`, or `Caladium horticultural group`) are joined
only to explicitly qualified species/group records; colour alone never creates
a cultivar or species claim. Any other campus label is stored as
`campus:<slug>` and is shown as “Uncatalogued campus label”; it receives no
fabricated scientific name, family, conservation status, ecology, or
knowledge-base facts.

## One-command enrollment

Install the encoder once (on the Pi, with network access):

```bash
cd /opt/botanika
mkdir -p models/embeddings
  curl -L --fail -o /tmp/mobilenetv2-10.onnx \
  https://github.com/onnx/models/raw/main/validated/vision/classification/mobilenet/model/mobilenetv2-10.onnx
sha256sum /tmp/mobilenetv2-10.onnx
```

The downloaded source checksum must equal the `derived_from_sha256` value in
`config/models/mobilenetv2-campus-embedding.json`.  Prepare the frozen
penultimate-feature graph (the `onnx` package is needed only on this setup
machine, not by the running app):

```bash
.venv/bin/python -m pip install --target /tmp/botanika-onnx-tooling 'onnx>=1.16,<2'
PYTHONPATH=/tmp/botanika-onnx-tooling python3 tools/prepare_embedding_model.py \
  /tmp/mobilenetv2-10.onnx models/embeddings/mobilenetv2-10-embedding.onnx
sha256sum models/embeddings/mobilenetv2-10-embedding.onnx
```

The derived checksum must equal the `sha256` value in
`config/models/mobilenetv2-campus-embedding.json`.  Then build the provisional
index:

```bash
cd /opt/botanika
.venv/bin/python tools/enroll_plants.py \
  --dataset /path/to/campus-plants
```

The default output is
`/opt/botanika/models/plant_classifier/campus-fewshot-v1.json` plus a `.sha256`
sidecar.  The app detects this artifact on its next backend restart.  It can
produce suggestions immediately, but it remains **not production validated**
and will not save an uncertain identification.

When independent evidence is available, run the same command against the
bundle layout:

```bash
.venv/bin/python tools/enroll_plants.py \
  --dataset /path/to/campus-bundle \
  --approve-production
```

`--approve-production` is deliberately not enough by itself.  Promotion also
requires at least five training photos per label, at least three independent
held-out photos per label, five unknown photos, no duplicate leakage, held-out
macro-F1 ≥ 0.80, unknown rejection ≥ 0.80, a CPU embedding benchmark, and
plant/session-separated held-out folders.  If any gate fails, the artifact is
still written as provisional and the exact blocker list is printed.

The app uses two views per query (original plus horizontal flip), a prototype
plus nearest-photo score, a confidence threshold, and a margin threshold.  A
low-similarity or ambiguous image abstains instead of forcing the nearest
campus label.  A campus index is incremental in the practical sense: rerun
the command with the complete label-folder tree to atomically replace the
versioned artifact; no model weights are retrained and no old partial index is
left active.

Enrollment-only runs also report leave-one-out coverage, abstentions, and
wrong-label counts. Those figures describe consistency among the supplied
photos, not field accuracy: views of the same physical plant are not
independent validation. A provisional artifact can offer suggestions while
the runtime continues to abstain from production saves until independent
held-out and unknown-image gates pass.

## Verification and model status

Run the bounded installed-model check after enrollment:

```bash
cd /opt/botanika
.venv/bin/python tools/verify_models.py --images /path/to/test-images
```

This checks the generic YOLO detector, MobileNet embedding runtime and (when
the campus artifact exists) few-shot inference, Qwen/grounded fallback, Vosk,
Piper, and the weed ONNX load plus existing publisher-fixture smoke.  It
records latency/RSS/temperature where the Pi exposes those values.  Weed
field testing is intentionally left to the final operator checkpoint.

No GPIO pins or LEDs are required.  The supported operator controls remain
the screen and keyboard hotkeys (`1`, `2`, `3`, `A`, `H`/`Esc`, `N`, `F1`).
On the Scan screen, `Space` performs a deliberate manual capture.  When the
generic detector has no eligible `potted plant` box (as is common for outdoor
trees), that manual action captures the full visible frame for classification;
automatic capture remains restricted to stable detector boxes.
