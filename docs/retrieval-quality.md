# Diagnosing retrieval and decision quality

Compare candidate retrieval, fusion, reranking, and final selection using the same models and cases. The purpose is to identify which stage limits the decision pipeline before changing models or investing in training. No weights are trained by these controls.

Historical observations below used earlier Turkish banking catalogs. The current English sector catalogs and prompts require fresh measurements; percentages across different label/language versions are not directly comparable. See [taxonomy and routing](taxonomy-and-routing.md).

## Hold models fixed and vary retrieval

1. Select the sector workspace and open **Experiments**. For this comparison, choose only **Hybrid retrieval + LLM**.
2. Choose one working embedding connection and one decision model.
3. Enable **Compare retrieval strategies**, then **Compare the first three strategies**.
4. Choose valid catalog sizes. For the complete banking cohort, `100, 200, 800` and a case limit of 153 create nine combinations. Each complete nonbank cohort requires a case limit of 430 and all 200 sector intents; smaller catalog comparisons need a smaller fixed cohort.
5. Run and download JSON containing candidate traces and the actual settings.

| Preset | Candidate source | Source / pool / final budget | Main change |
|---|---|---|---|
| Current hybrid | Semantic + lexical, equal RRF | 40 / 20 / 20 | Reference |
| Semantic candidates + LLM | Semantic only | 40 / 20 / 20 | Removes lexical retrieval |
| Semantic-weighted hybrid | 75% semantic, 25% lexical RRF | 40 / 20 / 20 | Fusion weighting |
| Hybrid + reranker + LLM | Equal RRF, then reranker | 60 / 40 / 8 | Larger pool and narrower final list |
| Separate description/example vectors | Equal RRF with separate texts | 40 / 20 / 20 | Catalog representation |
| Control: semantic + LLM | Semantic only | 40 / 20 / 8 | Reranker-off control |
| Control: semantic + reranker + LLM | Semantic, then reranker | 40 / 20 / 8 | Reranker-only intervention |

Sources, representation, weights, and budgets are editable. Keep `final candidates ≤ pool ≤ source candidates`. The source limit is 100 and final-list limit is 40. Method/model/strategy/catalog-size combinations must total at most 32. All combinations retain the same selected test cases and labels.

**Semantic candidates + LLM** still uses a decision model after retrieval. It differs from **Semantic search**, which makes no LLM call and can use a calibrated score threshold. Live demo also exposes retrieval strategies when hybrid selection is active.

## What the controls change

**Candidates per source** counts unique intents in semantic/lexical rankings; multiple examples of one intent do not become multiple fusion votes. **Pool** follows source fusion and supported context/neighbor additions. **Final candidates** are passed to the decision model after optional reranking.

Reciprocal rank fusion combines rank positions rather than directly summing incompatible source scores. Weights change those contributions; the fused score is not a confidence probability. Semantic-only retrieval ignores the RRF weight.

**Combined description + example** indexes each example with its intent name/description. **Separate description and example** indexes individual examples and each intent's name/description separately. Both alter the shared retrieval corpus, including the lexical source. To isolate embedding representation, use semantic-only candidates in both configurations and hold other settings fixed. Each representation has a separate index.

A reranker can only reorder the pool; it cannot recover a missing intent. The broad **Hybrid + reranker + LLM** preset changes multiple budgets. Use **Compare reranker on/off** to isolate reranking: it resets both control strategies to semantic source, combined representation, and `40 / 20 / 8`, differing only by the reranker.

## Connecting a reranker

`BAAI/bge-reranker-v2-m3` is the bundled local example, not a measured winner for every sector/language. Consult its [official model card](https://huggingface.co/BAAI/bge-reranker-v2-m3).

### Local model

```bash
.venv/bin/pip install '.[ml]'
```

Add to the existing `.env`:

```dotenv
INTENT_RERANKER_MODE=local
INTENT_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
INTENT_RERANKER_BATCH_SIZE=16
```

Restart the API. First use can download weights; CPU/GPU capacity affects timing. No separate API key is required. For offline use, set a local model directory and `INTENT_RERANKER_LOCAL_FILES_ONLY=true`. The CrossEncoder processes each query/candidate pair with a 512-token maximum; long definitions can be truncated. Scores are not calibrated probabilities.

### HTTP service

In the chosen workspace, **Model catalog → Add reranker** registers the model, base URL, protocol, and optional server key-variable name. For a server variable `INTENT_MODEL_KEY_RANK=...`, enter only `INTENT_MODEL_KEY_RANK`. Secrets are excluded from browser and experiment payloads.

| Protocol | Request fields | Response |
|---|---|---|
| Cohere / vLLM | `model`, `query`, `documents`, `top_n` | `results[]` with `index`, `relevance_score` |
| Hugging Face TEI | `query`, `texts`, `raw_scores: true` | List with `index`, `score` |

The adapter appends `/rerank`. Use `http://127.0.0.1:8081` for a service exposing `/rerank`, or a base ending `/v1` for `/v1/rerank`. The service must return a unique index and finite score for every document. Invalid data, timeouts, and 429s become technical errors; selection does not silently bypass the reranker. See the [TEI protocol](https://huggingface.co/docs/text-embeddings-inference/quick_tour#re-rankers).

Rerankers are not connected through OpenRouter in this implementation, and OpenRouter keys are not forwarded. Model-family membership alone does not establish compatibility with CrossEncoder or these HTTP protocols. Test the actual connection.

## Reading diagnostics

**Where is accuracy lost?** uses expected-route cases whose retrieval completed. An unexecuted stage displays `—`; K and denominators are explicit. Overall accuracy still counts technical errors, wrong rejection, and unnecessary clarification as failures.

| Diagnostic | Question | Inspect next |
|---|---|---|
| Semantic source Recall@K | Is the expected intent among semantic candidates? | Embedding, formatting, examples, representation |
| Lexical source Recall@K | Is it among lexical candidates? | Terminology, competing names, repeated descriptions |
| Pool Recall@K | Did it survive fusion/context additions? | Fusion weights and pool budget |
| Final Recall@K | Was it actually shown to the selector? | Reranker and final-list cutoff |
| Accuracy when candidate is present | Did the model route correctly when it could choose the expected intent? | Selection, clarification, rejection, workflow policy |

The last denominator retains selector/policy errors that occur after a final list exists. A reranker failure has no completed final list. Contextual replies that bypass retrieval are counted separately, not as retrieval successes. The historical top-level Recall@K metric uses all expected-route cases; stage diagnostics use completed retrieval cases, so their denominators can differ under failure.

**Show candidate trace** displays the expected intent's rank at each stage. Each failed case receives one group: retrieval miss, fusion/context cutoff, reranker/final cutoff, wrong selection, unnecessary clarification, false rejection, policy decision, or technical failure. These groups describe observed failure location; they do not prove causation or correct labeling.

Exports include model/strategy settings, catalog/dataset versions, source/pool/final IDs, final scores, outcomes, and stage timings. Reranker p95 covers per-query reranking; local weight preparation is separate. Total query p95 excludes index/model preparation and any upstream ASR or downstream TTS. Failed-request durations remain in overall latency summaries.

## Catalog audits and boundary editing

**Intent catalog → Audit catalog** reports possible scope overlaps, duplicate examples, test/index overlap, conflicting labels, split overlap, and tested-intent coverage. This deterministic check makes no extra model calls and is not a complete semantic audit.

Open an intent from a finding to edit its name, description, examples, exclusions, and **Disambiguation rule**. The rule enters selector and reranker text. The API also supports validated confusable-neighbor updates. The current OpenAI-compatible prompt is `router-en-v6-multisector-array-contract`.

Saving creates a new catalog version and preserves historical results. A stale edit returns 409. Compatible indexes are versioned, and calibrated semantic routing needs a fit for the new catalog. The definition editor does not change workflow/slot mappings. Case labels are not migrated automatically; review them separately in **Cases** if a boundary change requires new labels.

The old v1 banking audit found 148 possible general/specific scope pairs; v2 inspects more pairs. Such findings are review candidates, not proven taxonomy errors. The current 153-case banking cohort represents 58 distinct route intent IDs out of 800, including all 47 routable core definitions. Do not confuse competing against 800 candidates with testing every intent. Do not copy test questions into catalog examples to improve a score.

## Historical lexical measurement before taxonomy v2

This earlier **Turkish banking** snapshot held the same 26 expected-route cases and subset-selection protocol fixed:

| Searchable intents | Recall@1 | Recall@5 | Recall@20 | Recall@40 |
|---|---|---|---|---|
| 48 | 20/26 (76.9%) | 26/26 (100%) | 26/26 (100%) | 26/26 (100%) |
| 200 | 16/26 (61.5%) | 22/26 (84.6%) | 24/26 (92.3%) | 26/26 (100%) |
| 800 | 14/26 (53.8%) | 20/26 (76.9%) | 22/26 (84.6%) | 22/26 (84.6%) |

The four expected IDs missing from the 800-intent top 40 were `card.online`, `transfer.status`, `loan.status`, and `service.branch`. More-specific transfer/loan definitions ranked above some broad labels, motivating taxonomy review. Labels were not changed in that measurement. [Historical measurement file](retrieval-quality-verification.json).

No live LLM/reranker connection was available for that check, and local embeddings did not load offline. No new embedding/hybrid/reranker improvement was claimed. Controlled HTTP/UI tests were not visual browser verification. These values do not describe the English release.

To inspect the original 29-case file against the current banking catalog, or evaluate the complete 153-case cohort:

```bash
.venv/bin/python scripts/analyze_retrieval.py --mode lexical --cases data/demo/cases.json --catalog-sizes 48 200 800
.venv/bin/python scripts/evaluate.py --workspace demo --source seed --methods hybrid_llm --limit 153 --catalog-sizes 100 200 800 --retrieval-profiles data/retrieval-profiles.json
```

The first command needs no model service and reads only the original baseline file, not `benchmark-cases.json`; its results must be labeled as that smaller cohort. The second invokes configured providers on the full current banking test cohort. Analysis also supports `--mode semantic`, `--mode hybrid`, `--representation separate`, and `--local-files-only` for suitable local weights. Outputs go under ignored `artifacts/runs`.

## When to consider training

First validate operation boundaries and labels on reviewed data. Then compare retrieval sources, representation, and controlled reranking. Low source recall suggests examining embeddings and hard negatives; losing a correct pooled candidate suggests reranking; choosing incorrectly with the candidate present suggests selector behavior. Fix connection/schema failures before treating them as a modeling problem. Evaluate any training decision on independent cases while tracking accuracy, OOS false acceptance, false rejection, and p95 together.
