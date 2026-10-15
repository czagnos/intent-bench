# Controlled, repeated benchmark experiments

The UI and `scripts/evaluate.py` use the same evaluation service. A job freezes its reviewed cases, case order, catalog scopes, model/retrieval settings, calibration inputs, and pre-turn context when queued. Every repetition uses that same cohort, with fresh context for each case. These experiments measure observed variability on existing examples; repeating them does not create new held-out data or guarantee provider determinism.

The bundled catalogs and the [transcript template](../data/demo/transcript-example.csv) are synthetic software fixtures. No real transcript dataset is bundled or validated by this workflow. Import readiness, offline checks, and controlled HTTP tests do not establish live model accuracy. See [data provenance](../data/README.md), [model comparison](model-comparison.md), [catalog scaling](catalog-scaling.md), and [calibration](calibration-and-language.md).

## Start a controlled run

In **Experiments**, select methods, models, retrieval profiles, catalog sizes, and a reviewed cohort; then choose repetitions and optional execution limits. Planned work is selected cases × variant/catalog combinations × repetitions. At most 32 variant/catalog combinations and 100,000 case executions are accepted. The CLI still defaults to one lexical run, `source=seed`, workspace `demo`, and at most 100 cases. Use `--limit 153` for the full fresh banking test cohort or `--limit 430` for each other sector.

An offline lexical run with temporary workspace storage:

```bash
experiment_dir="$(mktemp -d)"
INTENT_DATA_DIR="$experiment_dir/data" \
INTENT_MODEL_CREDENTIALS_FILE="$experiment_dir/absent.env" \
INTENT_EMBEDDING_MODE=disabled INTENT_LLM_BASE_URL= \
  python3 scripts/evaluate.py --workspace demo --methods lexical --limit 153 \
  --repetitions 2 --max-provider-requests 0
```

No provider request is needed. The normal CLI export remains `artifacts/runs/<job-id>.json`, relative to the working directory, regardless of `INTENT_DATA_DIR`. Both default private data and artifacts are ignored by Git. Use the same data directory as the API when operating on its existing workspaces. Use your environment's Python executable if different.

For a configured remote comparison, add the controls to an existing evaluation command:

```bash
python3 scripts/evaluate.py --workspace airline --methods hybrid_llm --limit 100 \
  --repetitions 3 --max-provider-requests 500 --max-duration-seconds 900 \
  --max-reported-cost-usd 1.50
```

This command can send catalog, queries, and context to the configured providers. The USD threshold requires supported OpenRouter remote inference for every selected remote model; local models are allowed. Remote rerankers and other remote endpoints cannot use this USD threshold. An unused remote configuration does not prevent a lexical run.

| CLI flag | API field | Accepted values |
|---|---|---|
| `--repetitions` | `repetitions` | Integer 1–5; default 1 |
| `--max-provider-requests` | `execution_limits.max_provider_requests` | Integer 0–100000 |
| `--max-duration-seconds` | `execution_limits.max_duration_seconds` | Finite number 1–86400 |
| `--max-reported-cost-usd` | `execution_limits.max_reported_cost_usd` | Finite number greater than 0, at most 10000 |

Omitted limits are unlimited. Booleans, nonfinite numbers, unknown API fields, and out-of-range limits are rejected. Zero requests is valid for lexical/local work. Limits apply to the whole job, including every variant and repetition; they never reset per result. Request fields are at the top level of `POST /v1/evaluations?workspace=demo`; saved jobs retain them under `options.repetitions` and `options.execution_limits`.

## Status, cancellation, and partial results

| Status | Meaning | Evaluation CLI exit |
|---|---|---:|
| `queued` | Waiting for the evaluation worker | Still running |
| `running` | Preparing or evaluating; cancellation may be pending | Still running |
| `completed` | Planned case processing finished; inspect technical errors too | 0 |
| `stopped` | An execution limit stopped further work | 2 |
| `cancelled` | Cooperative user cancellation acknowledged | 130 |
| `failed` | The job could not finish | 1 |

Invalid options or local configuration/output errors also return nonzero. A completed job can contain technical-error records; completion alone is not model success.

The UI cancel action and `POST /v1/evaluations/{id}/cancel?workspace=demo` are workspace-scoped and idempotent. A queued job is cancelled immediately. A running job retains `status=running` and `cancel_requested=true` until its worker acknowledges the request. Cancelling a terminal job returns its unchanged final state. Missing or non-evaluation jobs return 404.

Press **Ctrl+C** in the evaluation CLI to request cancellation. The command waits cooperatively, writes the available JSON, and exits 130. Further Ctrl+C signals do not discard the artifact while waiting or saving. An operation already completed before cancellation can remain completed in the export. Started synchronous HTTP calls finish or reach their existing timeout; local model work, downloads, or index-lock waits may take longer. Cancellation and duration limits are not forced thread termination or a hard wall-clock deadline.

`progress`/`total` are completed/planned case executions; `selected_count` is the frozen cohort size. Active phases include `index`, `calibration`, and `cases`. An active result exists before preparation, and each completed case is checkpointed. Partial results retain finished records without inventing errors for unexecuted cases. Inspect their metrics as incomplete observations; they are excluded from repeat summaries and catalog scaling comparisons. Restart recovery preserves checkpointed records/accounting and terminates interrupted jobs.

| `stop_reason` | Meaning |
|---|---|
| `request_limit` | Another outbound inference attempt would exceed the request count |
| `duration_limit` | A checkpoint observed the elapsed worker duration threshold |
| `reported_cost_limit` | Known reported USD reached the threshold |
| `reported_cost_unknown` | At least one attempted request had unknown reported USD while a USD threshold was active |
| `user_cancelled` | User cancellation was acknowledged |
| `interrupted` | Restart recovery found unfinished work |
| `null` | No recorded control stop reason, including ordinary completion/failure |

## Accounting and cost interpretation

One provider request is reserved immediately before each outbound inference POST, including attempts that fail or time out. Embedding batches for index preparation and calibration, case embeddings, reranking, LLM selection, and TypeSafe selection all count when used by an evaluation. Local computation and downloads are not inference requests. Accounting belongs to this evaluation; unrelated live routes, standalone calibration/index commands, and other jobs are outside its totals.

Duration starts when the worker claims the job, excludes queue wait, and includes preparation. Query latency metrics exclude preparation; index building, calibration fitting, and reranker preparation have separate timings. Compatible frozen indexes, calibration fits, and model runtimes can be reused across repeats, so a later repeat need not repeat all preparation requests.

The JSON `accounting` includes `provider_requests`, known prompt/completion/total token subtotals and their `unknown_*_token_requests` counts, `known_cost_usd`, `unknown_cost_requests`, nullable `reported_cost_usd`, and `by_service_stage` subtotals. Usage is captured before validating task output, so an invalid selection or error response can still be billed. Tokens are not added twice by summing both the reported total and its components. Only allowlisted usage fields are retained; the ledger contains no raw provider response or credentials.

OpenRouter documents usage returned with complete responses and its reported cost as the account charge; its credits are denominated in USD. See [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting) and [OpenRouter support](https://openrouter.ai/support). IntentBench trusts `usage.cost` only from its supported exact OpenRouter embedding/chat endpoints. It does not infer currency from other endpoints or estimate prices from token counts. Embedding responses can omit cost. No extra billing lookup, automatic retry, or deprecated usage-inclusion flag is added.

Missing, malformed, negative, boolean, or nonfinite cost is **unknown**, not zero. `known_cost_usd` remains a useful subtotal; `reported_cost_usd=null` means the total is incomplete. With a USD threshold active, unknown cost stops further work at the next checkpoint/request. With no remote attempts, external reported cost is known zero; this says nothing about local hardware or hosting costs. Older artifacts without accounting display unavailable values, never invented zeros.

The USD control is a **soft reported-cost threshold, not a guaranteed billing cap**: an in-flight request can exceed it, and accounting can be incomplete. The request count prevents another outbound call beyond its limit. None of these controls changes provider keys, billing settings, or account-wide spending.

## Reading repetitions

Each result has `group_id`, one-based `repeat_index`, `complete`, `completed_count`, and `selected_count`. Single-repeat result IDs keep their previous form; multiple repeats append `__repeat_<index>`. Case IDs remain unique within each result. Catalog-size baselines belong to the same base variant and repeat; latency scaling requires full cohorts without technical errors in either compared result.

`group_summaries` reports planned, complete, partial, and missing repeat counts. Only complete full-cohort repeats contribute run-level metrics: routing accuracy, decision accuracy, macro-F1, Recall@K, technical-error rate, and **mean of per-run p95 latency**. Each aggregate includes defined observation count, mean, sample standard deviation, minimum, and maximum. Undefined values remain null; sample SD is null for fewer than two defined observations. The mean of per-run p95 values is not the p95 of pooled case latencies.

Completed runs containing technical errors remain in accuracy and error-rate statistics. Disagreement compares the same case across at least two complete repeats, excluding a case if any compared repeat has a technical-error response. The report gives eligible-case and excluded-error-case counts. It compares decision plus intent ID for `route`, `continue`, and `cancel`, ignoring irrelevant IDs for other decisions. No eligible cases means an undefined rate, not measured 0%. Deterministic lexical decisions should have zero disagreement; their measured latency can still vary.

Existing Wilson intervals remain per run. Do not pool repeated records into a larger Wilson interval, claim independent observations, or treat repetition as more held-out data. Provider routing, caching, load, and ordering can influence observed variability.

New evaluations use `latency_protocol=sequential-warm-index-v3`. Case compute/stage latency and index, reranker, and calibration preparation latency exclude the evaluation controller's cancellation checks and accounting persistence. Provider elapsed time, including failed responses, and model/index computation remain measured. Repeat latency summaries use these corrected case measurements. Earlier artifacts retain their recorded protocol and timings; compare protocols before combining historical results. Job elapsed duration and the duration limit still include control bookkeeping and preparation, excluding only queue wait. Live routing without an evaluation controller retains ordinary elapsed timing.

## Import transcripts without changing their meaning

Use **Cases → Import benchmark CSV** or:

```bash
python3 scripts/import_benchmark.py data/private/benchmark.csv --workspace airline
# Synthetic banking template; review it before evaluation:
python3 scripts/import_benchmark.py data/demo/transcript-example.csv --workspace demo
```

The fixed template is also available at `GET /v1/cases/template`. Its four turns across three conversations illustrate standalone, clarification, continuation, and cancellation snapshots. It is explicitly synthetic, is never seeded automatically, and is intended for the banking demo catalog. There is no audio ingestion, automatic ASR, rolling replay, or automatic history reconstruction.

CSV accepts UTF-8/BOM, comma/semicolon/tab separators, and multiline quoted fields. Preserve the original language and wording; imports are not automatically translated. Questions are bounded to 2,000 characters; outer question whitespace is trimmed. Empty questions are skipped. The file limit is 100 MiB.

| Column | Meaning |
|---|---|
| `Question` | Required header; the current user utterance |
| `BenchmarkSessionId` | Source conversation/session identifier |
| `BenchmarkSessionMessageId` | Source turn identifier |
| `Answer` | Reference text for human review, never a gold label/model input |
| `Message Flow` | Optional historical diagnostic trace, never inferred context/gold |
| `TRUE/FALSE` | Preserved source flag, never assumed accuracy |
| `SourceDatasetId` | Optional stable source namespace across file versions |
| `Context` | Optional JSON object containing the explicit state immediately before this turn |
| `Split` | Optional `dev`, `calibration`, or `test`; absent defaults to test for a new conversation |

Legacy files remain accepted. Without a source namespace, IDs retain their legacy file-fingerprint scope; changing file content can create different IDs. With `SourceDatasetId`, namespace + session identifies a conversation and namespace + session + message identifies a stable turn across files. The file content fingerprint remains a separate `dataset_version`. Namespace/session/message IDs must be nonblank and at most 200 characters when namespace or explicit context is supplied. Keep namespaces stable for the same source; use different namespaces for independent sources that reuse session IDs.

`Context` accepts only these fields:

| Field | Bound / rule |
|---|---|
| `active_intent` | Valid workspace intent ID or null |
| `slots` | At most 10 string values; keys 1–80 and values 0–2000 characters |
| `pending_slot` | Active workflow slot not already supplied |
| `pending_confirmation` | Boolean; requires every required slot in a compatible active workflow |
| `clarification_options` | At most 4 valid workspace intent IDs |
| `clarifications` | Integer 0–10 |
| `messages` | At most 12 prior user/assistant messages, each at most 2000 characters |

Workflow fields require an active intent and compatible catalog slots. A snapshot cannot await both a slot and confirmation. Unknown fields, invalid references, malformed/nonobject JSON, and oversized structures are rejected. Empty context remains `{}`. Supply only facts available before the current turn; never include future answers, model-derived history, or gold labels. Import validates all contexts against the selected workspace catalog before an atomic cases/report transaction. No model is called by import or review.

All imported turns start unreviewed, even with source flags. The report distinguishes `imported` unique parsed candidates, same-file `duplicates`, actual `inserted` rows, and `already_present` replays. Identical reimports preserve human labels, review timestamps/history, and moved splits. A changed immutable question, source content, or explicit context under an existing turn ID rejects the whole import, as do conflicting duplicate turns. No earlier valid rows or report are partially committed.

## Review and keep conversations together

Review the original utterance, source/session/turn IDs, and explicit pre-turn state in **Cases**. `route` needs a valid catalog intent. `continue` and `cancel` require a valid active context intent and that exact expected intent ID. `clarify`, `out_of_scope`, and `handoff` use a null expected intent ID. Full-decision correctness includes the intent match for route/continue/cancel. Route-only accuracy and macro-F1 retain their route denominator; context-only intent labels do not add route support.

Use the whole-conversation split action to move turns together. `PATCH /v1/conversations/{conversation_id}/split?workspace=demo` accepts `{"split":"dev"}` (also calibration/test), preserves labels and reviewed/unreviewed state, and records changed rows in history. URL-encode identifiers, including legacy IDs containing slashes. Reviewing one row cannot silently split its siblings.

New implicit turns inherit an existing conversation's split. A new explicit conflicting split rejects the whole import. An identical replay carrying the file's old Split does not undo or reject a later human move; conflict checks distinguish replays from new turns inside the transaction.

Evaluation and calibration preflight check the selected conversations against every stored split, including legacy/manual rows and unreviewed siblings. Unrelated leaking conversations do not block an independent selected cohort. Different IDs or namespaces cannot prove semantic independence; keep near-duplicates together manually too.

Calibration accepts only reviewed, context-free route/handoff/OOS cases and retains its minimum sample requirements. Context cases and clarify/continue/cancel labels are rejected for fitting. Exact normalized utterance overlap with tests/catalog examples is blocked. Changed calibration labels/splits invalidate saved fits, and reuse rechecks conversation separation. Tune on development/calibration data and reserve final tests; see [calibration and language](calibration-and-language.md#data-separation-and-provenance).

## Maintenance pitfalls

- Track accepted capability requirements through implementation and verification. Saving or committing existing changes does not fulfill outstanding requirements; check each requested behavior before declaring the work complete.
- Accumulate reported currency with decimal arithmetic. Binary floating-point sums can permit an extra request at an exact threshold; do not hide that with an arbitrary epsilon. Persist usage before task/status validation, and keep control-stop exceptions outside broad error-to-record conversion handlers.
- Reserve request counts at the outbound boundary. A zero budget must still allow local/lexical work. Capture each completed case and active partial result before later work can fail; terminal writes must atomically reread cancellation so stale completion cannot overwrite it.
- Choose the CLI exit code after cleanup finishes. Python evaluates a pending return before `finally`, so a SIGINT received during shutdown can otherwise be swallowed as an earlier success/stop code. Keep signal handling active through saving and shutdown, restore the prior handler, then return 130 when interrupted.
- Freeze actual provider client settings as well as metadata. Reuse runtimes only across compatible model/endpoint/credential/local-runtime settings. Deep-copy nested context per case and key scaling baselines by repeat index.
- Keep evaluation control bookkeeping out of model/preparation timers. Repeated full-job cancellation reads and accounting writes grow with saved records and can create artificial latency drift across repetitions. Exclude their elapsed time once across nested control calls, including failing callbacks; keep the duration limit on the full wall clock and retain every persistence/cancellation checkpoint.
- Reject nonfinite numeric inputs without echoing them into JSON validation errors; otherwise a valid rejection can become a serialization 500. Keep new checkpoint/accounting contracts structured even where older artifacts use untyped JSON. Pydantic/FastAPI-exposed TypedDicts must use `typing_extensions.TypedDict` while Python 3.11 is supported.
- Distinguish absent Split from explicit test, and `{}` from explicitly populated default context. Preserve stable namespace identity separately from file fingerprints. Reconcile immutable replays before applying persisted split conflicts; an old export must not erase human review or moves. Keep catalog-version validation in the atomic import transaction.
- Whole-conversation moves update split only; implementing them as repeated row reviews incorrectly marks unreviewed turns reviewed. Recheck relevant siblings when reusing calibration, since an unchanged fit fingerprint cannot detect a newly inserted sibling in another split.
- Preserve legacy identifier semantics and allowlisted historical trace extraction. URL-encode IDs without treating them as paths. Source answers, flags, and historical actions remain diagnostic data and never become automatic labels.
- Pending cancellation still has an active lifecycle status; a terminal job can retain `cancel_requested=true`. Saved options are nested under `options`, unlike request fields. Old missing accounting and undefined statistics remain unavailable. Type-check response-shaped fixtures as well as DOM tests.
- Partial preparation results can have `model=null`; omit absent model segments from result labels instead of displaying a literal null or an empty separator.
- Preserve an accepted evaluation ID while the first status GET is pending or fails. Keep cancellation available as soon as POST returns the ID; cancelling must abort and invalidate that pending read. Resume status polling after failures and prevent duplicate submission until terminal state; a failed status read does not undo a successful submission.
- Test public outcomes using real service/store components and only external boundaries. Read public field names instead of inventing fixtures; keep HTTP gates bounded and release them in `finally`. Inspect an actual behavioral RED assertion before implementation; import/collection failures are not behavior evidence. Run backend tests and frontend production builds sequentially.
- Start evaluation tests through the public request path so frozen catalogs, options, and repetition metadata are created together. Do not hand-build worker tuples that couple fixtures to orchestration internals. For completion-only assertions, synchronize the running worker at an external boundary and join it; a short polling deadline accidentally turns functional coverage into a machine-speed benchmark.
