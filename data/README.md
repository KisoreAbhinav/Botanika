# Data boundary

This tree separates reproducible seed/knowledge inputs from generated SQLite
databases, vector indexes, temporary uploads, and discovery crops. Generated or
personal data is ignored by Git; only documentation and small manifests belong
in the repository.

Phase 6 seed inputs live in `config/catalog/`, `models/plant_classifier/`, and
`data/seed/`. The image manifest is intentionally a reference-only release
input until licensed field assets, hashes, observation IDs, and held-out
location groups are supplied. The runtime never downloads remote images.
