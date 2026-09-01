# Model asset boundary

Each model family gets an isolated directory containing a future model card,
labels, preprocessing contract, checksums, license/provenance, benchmark data,
and the runtime artifact. Large weights are intentionally ignored by Git.

No model should be activated merely because a file exists. The future registry
must require a complete contract and successful Pi benchmark first.
