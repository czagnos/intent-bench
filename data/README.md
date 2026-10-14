# Data provenance and handling

## Bundled examples

`demo/` contains a Turkish banking example catalog, synthetic routing cases, calibration cases, and taxonomy migration fixtures. The expanded catalog is generated from reusable definitions by `scripts/build_demo_catalog.py`; core definitions and scenarios are maintained in the repository. These examples exercise software behavior and catalog scaling. They are not representative customer traffic, an independent held-out benchmark, or proof of production accuracy.

The bundled definitions and examples are distributed under the project’s [Apache-2.0 license](../LICENSE), unless a file states otherwise. This grant does not cover imported third-party datasets, model weights, or hosted services. For new data, record provenance and permissions; a synthetic label alone is not proof of origin.

## Private inputs and outputs

Keep imported CSVs and other datasets under `data/private/` or outside the repository. This directory also stores the default SQLite database, credentials, and vector indexes. `artifacts/` contains local runs and analysis outputs. Both locations are ignored by Git and excluded from the Docker build context. Never force-add their contents or copy them into public documentation/tests.

Imported rows may retain question text, source answers, identifiers, and selected source metadata for review. Experiment exports can include per-case outcomes and context. Embedding vectors and fingerprints also require a sharing decision; they are not automatically anonymous. Review files and screenshots before sharing them.

Use separate, reviewed development, calibration, and test splits. Keep all turns of a conversation and near-duplicates together. Never send labels, source answers, or held-out test utterances into retrieval indexing or prompt tuning. Check the actual workspace contents before enabling a remote provider.

## Adding a publishable dataset

Document its source, owner, license, collection/creation method, permitted uses, languages, domain, labeling process, known limitations, split method, and version/fingerprint. Obtain permission for any upstream material and remove personal or confidential data. Confirm that both redistribution and sending data to selected model providers are allowed. Keep this provenance record alongside the released dataset, without including private approval documents.
