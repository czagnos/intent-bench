# IntentBench documentation

Start with [getting started](getting-started.md) for installation and [benchmarking](benchmarking.md) for your first evaluation. See the [project README](../README.md) for an overview.

## Core guides

| Guide | Covers |
|---|---|
| [Getting started](getting-started.md) | Local setup, model configuration, frontend development, Windows, and Docker |
| [Architecture](architecture.md) | Routing methods, candidate retrieval, model selection, and workflow policy |
| [Routing strategy](taxonomy-and-routing.md) | Intent boundaries, sector workspaces, custom catalogs, and migrations |
| [Benchmarking](benchmarking.md) | Running benchmarks, reproducible comparisons, metrics, and failure diagnosis |
| [Research](research.md) | Papers behind the design and limits of their applicability |

## Models and experiments

| Guide | Covers |
|---|---|
| [Model connections](model-registry.md) | Provider registration, credentials, readiness checks, and vector indexes |
| [Embedding selection](embedding-selection.md) | Embedding profiles and retrieval representations |
| [Model comparison](model-comparison.md) | Comparing decision and embedding models |
| [TypeSafe Jev](typesafe-jev.md) | Native protocol, setup, and comparison experiments |
| [Retrieval quality](retrieval-quality.md) | Retrieval controls, rerankers, diagnostics, and catalog audits |
| [Calibration and language](calibration-and-language.md) | Semantic rejection, data separation, and multilingual inputs |
| [Catalog scaling](catalog-scaling.md) | Fixed cohorts, catalog subsets, and scaling measurements |
| [Controlled experiments](benchmark-experiments.md) | Repetitions, execution limits, accounting, and transcript import/review |
| [Live views](live-demo-views.md) | Conversation simulation, replay, and measurements |

## Data and contribution

- [Data handling and provenance](../data/README.md)
- [Synthetic conversation sample pack](../data/samples/synthetic-v1/README.md)
- [Contributing and project structure](../CONTRIBUTING.md)
- [Security](../SECURITY.md)
- [Release preparation](public-release.md)

Historical measurements in these guides describe their recorded versions and conditions; rerun comparisons on your current fixed dataset.
