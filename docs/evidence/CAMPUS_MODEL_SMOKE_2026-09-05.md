# Campus model smoke evidence — 2026-09-05

This run was performed on the Raspberry Pi (`aarch64`) with downloaded images
kept under `/tmp`; the images and generated provisional artifact are not part
of the repository or production deployment.  SHA-256 values below identify the
exact 1,280 px Wikimedia thumbnails used.

| Purpose | Wikimedia source / author | License | SHA-256 |
| --- | --- | --- | --- |
| fruit/plant input | [Red Apple](https://commons.wikimedia.org/wiki/File:Red_Apple.jpg), Abhijit Tembhekar | CC BY 2.0 | `326bf157694b1e1b8672579ea6da8d5173e7fe3fb4df9cd674bcc4b1df44447c` |
| flowering-plant input | [Common sunflower](https://commons.wikimedia.org/wiki/File:Common_sunflower.jpg), Md Joni Hossain | CC BY 4.0 | `1da4a992c51f794c7fb6a1be642e356ae7ec3b067a80a168a8ae48ff87f447f8` |
| tree input | [Albizia versicolor tree](https://commons.wikimedia.org/wiki/File:Albizia_versicolor_tree.jpg), StoffelLombard | CC BY-SA 4.0 | `2ebc2375e1683f451ddd5e2a365df454f269b31396263165d79c83de8ab6fad1` |
| second tree input | [A fig tree](https://commons.wikimedia.org/wiki/File:A_fig_tree.jpg), CharMel Creations | CC BY 4.0 | `d9f6125aeafe0bbcf5a11558c2132e080b9bd80bc1733095d7884a2336f872bf` |
| non-plant negative | [SKY KISSES ON MOUNTAIN](https://commons.wikimedia.org/wiki/File:SKY_KISSES_ON_MOUNTAIN.jpg), apelmusa | CC BY-SA 3.0 | `d1dd11b7e670cf8321e5a3f34a3e9c9f2d73beec66404e6e84d463428bb14126` |

## Installed-model results

`tools/verify_models.py` returned overall `ok` when run outside the sandbox so
the local llama runtime could use its loopback transport:

- YOLO11n loaded with its pinned checksum and ran on four images at about
  512 ms p50.  The saturation guard passed (0/4 images hit the 100-box cap).
  It found the apple at 0.9158 confidence, but called the sunflower `banana`
  at 0.3587 and did not box the outdoor tree.  This is why COCO detections are
  used only for proposing crops, never as plant identity, and why the manual
  `Space`/button central-frame capture exists for trees.
- The derived MobileNetV2 encoder loaded with SHA-256
  `10ddb16ca5df7d3fde89ec18aa99f768a75c16e700e680d03f25d1b3b8b720c4`
  and produced finite, unit-normalized 1,280-dimensional vectors for every
  plant, tree, and negative input at about 114 ms p50 (original + horizontal
  flip).
- Qwen GGUF loaded and completed one inference in about 18.2 seconds.  Its
  sample wording did not pass the strict per-statement citation gate, so the
  application correctly selected its grounded offline-extractive fallback.
- Vosk and Piper both loaded; the same unsandboxed status check enumerated the
  Pi microphone and speaker and reported the voice pipeline ready.
- The weed ONNX loaded and ran without persisting any image.  It produced
  false-positive visual cues on this out-of-domain set, including the mountain;
  no field-accuracy claim is made and the physical weed test remains last.

## Campus-index path smoke

A deliberately tiny **non-production** index was built under `/tmp` with two
coarse labels (`Flowering-plants` and `Trees`), two images each.  It wrote a
checksummed artifact and measured approximately 131 ms p50 embedding time, but
leave-one-out accuracy was 0.0.  The release gate correctly kept
`deployment_ready=false` because there were fewer than five training images per
label, no independent held-out sessions, and no unknown set.  This fixture was
not copied into `/opt/botanika/models/plant_classifier`.

That result is useful negative evidence: load/inference, arbitrary labels, and
safe abstention work, but a few unrelated internet images cannot establish
campus species accuracy.  Only the real campus, plant/session-separated bundle
described in `docs/CAMPUS_PLANT_ENROLLMENT.md` can promote the classifier.
