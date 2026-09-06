# Phase 11 plant reference check

Date: 2026-09-06 (Asia/Kolkata)  
Scope: seven operator-owned campus enrollment photographs, selected from `data/campus/enrollment/train`. The photos were inspected locally before assessment. They were not uploaded to Google or any other outside service. Web lookup was used only for taxonomic and morphology references.

This is a demo consistency check, not held-out accuracy. Each query is one of the images used to enroll its label, so agreement can demonstrate the current pipeline is wired to the enrolled class but cannot establish generalization. The current artifact is explicitly provisional: `deployment_ready=false`, with blockers requiring five images per label, independent held-out and unknown sets, and the corresponding metrics.

## Results

| Query image (SHA-256 prefix) | Enrolled label | Visual/reference-supported assessment | Current CampusFewShotClassifier top suggestion | Confidence / status | Agreement |
|---|---|---|---|---|---|
| `Plumeria rubra/IMG_20260905_173704157.jpg` (`260e8233`) | *Plumeria rubra* | **Likely *Plumeria* sp., supports *P. rubra***: branched tree, thick branches, long entire leaves, pink flowers. Species/cultivar separation from *P. obtusa* is limited in this view; the pink flowers and pointed leaves favor *P. rubra*. Kew describes a small tree with white/pink/red fragrant flowers. | *Plumeria rubra* | 0.9838 / `uncertain` | Yes, at enrolled-label level; species remains provisional |
| `Serissa japonica/IMG_20260905_163408082.jpg` (`551ef270`) | *Serissa japonica* | **Unresolved; possible mislabeled *Wrightia antidysenterica***: this frame shows broad elliptic opposite leaves, long slender tubes/pedicels, and clusters of flat white flowers. NParks describes *Serissa* as having much smaller (0.6–2.2 cm), thick leaves and tubular pinkish-white flowers; petal count is variable (4–6 in NC State’s reference), so count alone is not decisive. The visible whole morphology is closer to *Wrightia*; the photo lacks a decisive close-up, so no relabel is made. | *Serissa japonica* | 0.9763 / `uncertain` | Model agrees with folder label; botanical identity **does not pass** |
| `Combretum indicum/IMG_20260905_164348365_HDR.jpg` (`a49abc86`) | *Combretum indicum* | **Supports *Combretum indicum***: woody climber, opposite broad leaves, and the diagnostic-looking flowers progressing white/pink to red. Kew’s *Combretum* treatment includes *Quisqualis indica* and describes a woody climber with showy colour-changing flowers. | *Combretum indicum* | 0.9720 / `uncertain` | Yes, provisional; one of the previously weak labels |
| `Hibiscus × rosa-sinensis/IMG_20260905_164205316.jpg` (`20a71b79`) | *Hibiscus × rosa-sinensis* | **Likely cultivated hibiscus**: glossy ovate serrated leaves and large red double flowers with an exserted staminal column. Cultivar-level identity is not asserted. Kew treats this as an accepted hybrid cultigen and notes many colour forms. | *Hibiscus × rosa-sinensis* | 0.9922 / `uncertain` | Yes, provisional |
| `Alpinia zerumbet 'Variegata'/IMG_20260905_163024390.jpg` (`90d1f94f`) | *Alpinia zerumbet* 'Variegata' | **Supports *Alpinia zerumbet***: clumping ginger habit and broad lanceolate leaves with strong cream longitudinal striping. The cultivar name is horticultural; the image does not show flowers. Kew accepts *A. zerumbet* as a rhizomatous geophyte and lists shell ginger as a common name. | *Alpinia zerumbet* | 0.9946 / `uncertain` | Yes at species level; cultivar not tested |
| `Dracaena trifasciata/IMG_20260905_171328769.jpg` (`cf8ce9fd`) | *Dracaena trifasciata* | **Strongly supports *D. trifasciata***: dense acaulescent rosette of erect, transversely banded sword leaves. Kew accepts *D. trifasciata* and lists *Sansevieria trifasciata* as a synonym; its Flora description matches erect banded leaves. | *Dracaena trifasciata* | 0.9886 / `uncertain` | Yes, including accepted-name/synonym handling |
| `Sphagneticola trilobata/IMG_20260905_163854121.jpg` (`c55d3f9e`) | *Sphagneticola trilobata* | **Likely *S. trilobata* (Wedelia)**: dense low herb with opposite leaves and clearly visible yellow radiate heads. The frame supports the genus/species habit, though leaf lobing is shallow or obscured; this is a useful demo image with species certainty still provisional. Kew describes trailing stems, often strongly 3-lobed leaves, and yellow heads. | *Sphagneticola trilobata* | 0.9839 / `uncertain` | Yes, provisional |
| `Hymenocallis littoralis/IMG_20260905_173620885.jpg` (`b7f80742`) | *Hymenocallis littoralis* | **Supports *H. littoralis***: strap-like leaves and unmistakable white spider-lily flowers with a corona and long narrow tepals. Kew accepts it as a bulbous geophyte and describes white flowers in umbels. | *Hymenocallis littoralis* | 0.9939 / `uncertain` | Yes, supported |

The classifier suggestions were generated with the local ignored artifact `models/plant_classifier/campus-fewshot-v1.json` and the configured MobileNetV2 embedding model. All eight top suggestions agree with the enrolled folder label, but independent visual validation supports seven cases and leaves Serissa unresolved/possibly mislabeled (7/8 visual support; 8/8 folder/model agreement). Every result still reports `uncertain` because the artifact’s provisional deployment gate is not bypassed by high similarity.

## References

The independent references are Kew Plants of the World Online pages, which provide accepted names, synonyms, distribution, and morphology accounts:

- [*Plumeria rubra* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A81275-1/general-information)
- [*Serissa japonica* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A766327-1/general-information)
- [*Serissa japonica* — NParks Flora&FaunaWeb](https://www.nparks.gov.sg/florafaunaweb/flora/2/4/2453)
- [*Wrightia antidysenterica* — NParks Flora&FaunaWeb](https://www.nparks.gov.sg/florafaunaweb/flora/2/5/2554)
- [*Serissa japonica* — NC State Plant Toolbox](https://plants.ces.ncsu.edu/plants/serissa-japonica/common-name/tree-of-a-thousand-stars/)
- [*Combretum indicum* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A77101543-1/general-information)
- [*Hibiscus × rosa-sinensis* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A560756-1/general-information)
- [*Alpinia zerumbet* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A872083-1/general-information)
- [*Dracaena trifasciata* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A77164235-1/general-information)
- [*Sphagneticola trilobata* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A1093589-2/general-information)
- [*Hymenocallis littoralis* — Kew POWO](https://powo.science.kew.org/taxon/urn%3Alsid%3Aipni.org%3Anames%3A30048918-2/general-information)

## Demo-readiness and limitations

The local smoke run completed on the Raspberry Pi (`aarch64`): classifier, embedding model, detector, and weed service loaded successfully across the eight selected images. The generic YOLO detector is an object detector and does not identify plant species; on these frames it returned a `potted plant` for Alpinia, `apple` false positives for Combretum, and no generic boxes for the other six. Those outputs must not be presented as botanical identity. The classifier is the component whose top suggestions are compared above.

The seven images are single views from enrollment runs, not independent plants or held-out images. Several frames are crowded or lack fruit, full habit, underside, or close floral details. Consequently, labels marked likely/support are suitable as demo catalog labels with a visible provisional/uncertain state; they are not evidence to relabel the dataset or promote production saves. Keep the Serissa folder flagged for expert review before any relabel/retrain, and retain caution around *Plumeria* species/cultivar.
