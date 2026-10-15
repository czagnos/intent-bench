# Intent boundaries, workflow ownership, and taxonomy versions

Intent recognition selects a business goal and its destination workflow. IntentBench measures that decision separately from retrieving candidates, collecting workflow fields, or executing a business operation. Current selector protocols are `router-en-v6-multisector-array-contract` (OpenAI-compatible) and `router-en-typesafe-v2-multisector-choice` (TypeSafe).

## Designing a useful intent catalog

An intent should represent an atomic goal with a distinct routing outcome. Use stable IDs, precise descriptions, varied positive examples, explicit exclusions, and nearby confusable IDs. Write a `selection_rule` for difficult boundaries. Functional categories are `domain` values; the sector is a separate workspace.

Distinguish information requests, starting an operation, changing it, checking its status, and canceling it when those requests lead to different workflows. Avoid making every parameter a new intent: booking reference, date, amount, product variant, or delivery address often belongs to the destination workflow. Split a product-specific intent only when the routing destination or business scope requires it.

| Request | Decision boundary |
|---|---|
| “Change my flight” | Route to ticket change; collect booking reference and date later |
| “Where is my refund?” | Refund status, not starting a return or requesting a new refund |
| “What does my policy cover?” | Coverage information, not reporting a claim |
| “Close my card” | Clarify temporary blocking versus permanent cancellation if both are available |
| “Book a flight and cancel my insurance” | Multiple goals require clarification or an explicit supported multi-goal policy |

Review these boundaries against actual operations. Starter catalogs cover common lifecycles but cannot define every organization's products or permissions. Add realistic paraphrases and speech-transcript noise to reviewed test data without copying held-out questions into catalog examples.

## Generic versus product-specific intents

The banking taxonomy chooses a specific intent when the request explicitly identifies the relevant product/channel and operation. Otherwise it chooses the appropriate general intent. Missing a product name alone need not trigger clarification, and the model must not invent a currency or channel.

| Request | Expected intent | Reason |
|---|---|---|
| “What is the status of my EFT?” | `bank.transfer.eft.status` | Transfer type and operation are explicit |
| “I sent money; what is its status?” | `transfer.status` | Transfer type is unspecified |
| “I forgot my debit card PIN” | `bank.card.debit.pin_reset` | Debit card is explicit |
| “I changed phones and now my SIM is blocked” | `digital.device` | Changing a device does not imply telephone banking |
| “Calculate my term-deposit return” | `deposit.rate` | No local/foreign-currency product was identified |
| “Increase my credit card limit” | `card.limit.change` | Total credit limit differs from a daily spending cap |

These examples illustrate current boundaries in English; older measurements used Turkish utterances. Exact intent IDs are scored, not an equivalence group of broad and narrow labels. Selection rules are supplied to the selector and reranker. Test labels and test questions are not added to the embedding index.

## Selector versus workflow

The model-facing selector contract excludes `slots`, candidate `required_slots`, `pending_slot`, and collected workflow fields. Recent conversation text remains available as context. Legacy endpoint `slots` output is discarded rather than trusted as workflow input.

A clear “Increase my card limit” request produces `route → card.limit.change`; the workflow then asks for a new limit. That field question is not counted as intent clarification. Supported banking simulations also handle a lost card's last four digits and a transfer reference. Related specific workflows inherit those fields where appropriate.

Explicit values can be extracted conservatively after selection. “Set my limit to 5000” supplies a target; “increase it by 500” supplies a delta and must not become the new limit. Negated targets must not be extracted. English confirmation/cancellation and supported numeric formats, including `5,000 TRY`, are checked alongside retained Turkish input rules. This is a limited simulator, not a general slot-extraction model. Custom fields without a parser remain a workflow preview; the destination workflow is responsible for collecting them.

True uncertainty between intents produces `clarify`. For the OpenAI-compatible protocol, a clarification needs a question and no chosen intent ID; `mentioned_intent_ids` is always a JSON array. A known single intent uses `[]`; genuine ambiguity or multiple goals retains the relevant candidate IDs. Invalid responses remain technical errors, and unnecessary clarification remains incorrect in accuracy denominators. The schema uses `strict: false` for endpoint compatibility while application validation enforces the contract.

Banking-specific deterministic rules apply only when their relevant intents are available. A card-related request in a loyalty catalog must not invent banking intent IDs. Workflow previews and handoff states never execute a real transaction.

## Sector workspaces and custom intents

`GET /v1/catalog/presets` returns an array of `id`, `name`, `description`, `workspace`, and `intent_count`. Banking uses `demo`; the other named workspaces are `airline`, `insurance`, and `ecommerce`. Their catalogs, cases, calibration, sessions, registrations, and jobs are isolated.

The three nonbank catalogs each contain 200 English definitions. The expansion adds 130 airline, 126 insurance, and 116 e-commerce operations while retaining original IDs. Broad intents remain valid for general requests; explicit specialist operations select their own workflow. For example, an ordinary flight-date change stays with ticket change. Same-day change requires an explicit request for today's flight or the named same-day-change facility; merely mentioning another flight on the same calendar date is insufficient.

**Intent catalog → Add intent** submits `POST /v1/catalog/intents?workspace=airline` with `{ "expected_version": "…", "intent": { ... } }`. The complete intent follows the shared schema, including channels and optional workflow fields. It appends to the existing catalog after validation; duplicate IDs, invalid neighbors, missing field questions, excessive size, or a stale version are rejected. A successful response includes `version`, `intent_count`, and `intent`.

The form retains edits after an error. **Refresh catalog** loads the latest version before retrying a conflict. **Export** saves the whole catalog; **Import JSON** replaces it with a complete list. Versioned definition editing from audit findings changes names, descriptions, examples, exclusions, and selection boundaries while retaining workflow mappings. It does not relabel cases automatically.

## Historical taxonomy v2 and current English migration

On **10 September 2026**, `demo-taxonomy-v2` revised five expected labels in the 29-case Turkish banking test set without changing those test utterances:

| Case | Previous label | Revised label |
|---|---|---|
| `seed-007` | `card.pin` | `bank.card.debit.pin_reset` |
| `seed-011` | `transfer.status` | `bank.transfer.eft.status` |
| `seed-012` | `transfer.create` | `bank.transfer.internal.create` |
| `seed-019` | `digital.password` | `bank.digital.mobile.password_reset` |
| `seed-021` | `loan.status` | `bank.loan.personal.application_status` |

That release used test dataset `seed-specificity-v2`, revised 12 of the 72 calibration labels, and simplified `calibration-seed-v1-034`. Its calibration version was `calibration-seed-specificity-v2`. The [taxonomy manifest](../data/demo/migrations/taxonomy-v2.json) records changes; [historical targets](../data/demo/migrations/taxonomy-v2-targets.json) preserve the original language stage. A later 15 September contract fix required explicit candidate arrays under `router-tr-v5-array-contract`.

The current `demo-english-v3` migration translates recognized untouched banking content and uses English selector protocols. Stable case and intent IDs retain history. A migration updates only records matching known normalized prior fingerprints; edited definitions, reviewed labels, customer inputs, custom catalogs, and archived snapshots are preserved. A changed target intent can also cause its seed label migration to be preserved for review. Existing jobs are never rescored automatically.

Inspect **Intent catalog → Audit catalog → Demo taxonomy version** or `GET /v1/catalog/migrations?workspace=demo`. Case history is available from `GET /v1/cases/{case_id}/versions?workspace=demo`. New sector workspaces seed their own matching datasets when empty. Refit calibration after a changed catalog and rerun experiments; old Turkish percentages do not quantify an English-language improvement.

## Nonbank expansion v2

The immutable `data/presets/<sector>/migrations/expansion-v2.json` manifests record original intent fingerprints and case IDs. Migration IDs are `airline-expansion-v2`, `insurance-expansion-v2`, and `ecommerce-expansion-v2`. Recognition requires every v1 intent ID plus at least one unchanged sector-specific v1 definition, or the complete current starter catalog. A shared `service.human` definition alone does not establish provenance.

An applicable migration updates unchanged original definitions and appends missing v2 IDs. It preserves edited/custom definitions and all existing cases, including reviewed labels and imports; it does not recreate intentionally deleted original cases. New cases are added only when their referenced intent definitions are safe. Trimmed or unrelated catalogs, and expansions that would exceed 2,000 intents, are skipped. The report, completion marker, catalog version, and case additions commit together, making retries safe after failure and completed migrations idempotent.

Read `GET /v1/catalog/migrations?workspace=airline` (or the other sector) for applied/preserved records and any skipped reason. Existing workspaces can have fewer or different cases than a fresh workspace because preserving user records takes precedence over reproducing the starter cohort. Refit calibration and rerun comparisons after expansion; archived jobs and catalog snapshots remain unchanged.

## Fair catalog-size and reranker comparisons

`fixed-cohort-nested-domain-v2` retains expected test/calibration intents, conversation targets, and supported deterministic dialogue targets in every subset. Core intents fill the remaining budget first, followed by deterministic domain-balanced distractors. Larger subsets contain smaller subsets. The 48-intent subset after taxonomy v2 is not identical to the original 48 core definitions.

The complete 153-case banking cohort requires 59 intents, or 67 when paired with the unchanged calibration cohort. Use `100, 200, 800` for full-cohort comparisons across methods. It covers all 47 routable core definitions and selected specific operations, with 58 distinct route labels; it does not cover all 800 generated definitions. Smaller fixed cohorts can require fewer intents. Other catalogs and edited cohorts have different minima; the server validates coverage before model calls.

The complete 430-case airline, insurance, or e-commerce test cohort requires all 200 sector intents: 199 route targets and the human handoff target. Select a smaller fixed cohort before comparing smaller catalogs, keep that cohort unchanged across sizes, and account for calibration targets too. The CLI's default 100-case limit does not run a full bundled cohort; use `--limit 153` for banking or `--limit 430` for other sectors, or set **Maximum cases** to the corresponding count in the interface.

Start with one embedding/decision-model pair and **Experiments → Hybrid retrieval + LLM → Compare retrieval strategies → Compare the first three strategies**. Then use **Compare reranker on/off** to hold both strategies at semantic source, combined representation, 40 source candidates, 20 pool candidates, and eight final candidates. Only reranking changes. One model pair at three sizes produces six combinations.

A strategy that also changes pool/final budgets cannot isolate a reranker's contribution. Inspect final candidate recall, accuracy when the expected candidate is present, OOS behavior, errors, and p95 together. Repeat timing measurements before drawing speed conclusions. See [retrieval settings and reranker connections](retrieval-quality.md).

```bash
.venv/bin/python scripts/evaluate.py --workspace demo --source seed --methods hybrid_llm --limit 153 --catalog-sizes 100 200 800 --retrieval-profiles data/reranker-comparison-profiles.json
```

Replace `reranker_id` in the profile file with your registered connection ID when needed. This command uses the configured providers and can incur charges.

## Supplemental benchmark depth v1

Every sector keeps its original tests and calibration unchanged and publishes additional English cases in `benchmark-cases.json`. Banking adds 94 core paraphrases and 30 challenge/context cases. Each other sector adds 199 paraphrases, 24 challenges, and two context cases. Challenges include near-neighbor negation, self-correction, synthetic noisy transcripts, underspecified requests, out-of-scope goals, and explicit human handoff. Expected labels follow existing selection rules, including product-specific banking precedence; decision policies are not changed to fit these cases.

The supplements are curated synthetic robustness checks, not recorded speech or an independent held-out benchmark. Test questions remain outside retrieval examples and calibration. Written noise cannot establish ASR accuracy or end-to-end voice quality. See [data provenance and cohort counts](../data/README.md).

After all historical releases, `<sector>-case-depth-v1` uses an immutable manifest of the complete preceding catalog to add eligible cases. Historical migrations receive only their original base-case files. The depth migration preserves all existing rows, rejects new cases whose target or context definitions were customized, and skips unrecognized or trimmed catalogs. It creates no catalog snapshot and never revives deleted supplemental cases after completion. Fresh bootstrap includes the supplement atomically; a failed upgrade rolls back new rows, its report, and its completion marker together. Existing workspace counts can be lower than the published complete cohort because user edits and deletions take precedence.

## Pitfalls

- Ambiguous benchmark requests should sound like natural underspecified speech. Avoid meta commentary that tells a classifier which ambiguity or expected label the author intended; record the challenge category separately.
- Check product aliases as well as canonical product names when assigning benchmark labels. In the banking catalog, “bank card” explicitly aliases a debit card, so a core lost-card or delivery example must use an unqualified “card” unless it is labeled with the specific debit-card operation.
- Keep supplemental cases out of historical migration inputs. Otherwise an older migration may publish them prematurely or recreate them before the depth revision's completion marker can protect intentional deletions. Restrict historical revision discovery to its release filename pattern and apply the explicit depth revision last.
- Updating bundled JSON alone does not upgrade existing workspaces. Use immutable prior fingerprints and a versioned, conservative migration; publish the catalog, cases, report, and completion marker atomically and verify retry/idempotency behavior.
- Do not count omitted new cases as preserved user edits. Migration reports distinguish `skipped_cases`, whose required definitions are unsafe, from `preserved_cases`, which already exist and differ from the bundled revision.
- New specific operations can invalidate examples under an older broad intent. Review the broad definition's examples, exclusions, and selection rule alongside the new neighbors and their expected labels.
- Normalize all example/test/calibration texts for duplicate checks, and re-evaluate OOS requests against the expanded scope. More cases do not automatically provide independent coverage.
- Same-day flight change needs explicit "today" or the named same-day-change facility. A request for a different departure on the same calendar date can still be ordinary ticket change.
- An English UI alone does not make an English benchmark. Check source utterances, prompts, retrieval instructions, server messages, confirmation/cancellation, number grouping, currencies, and negated amount targets through public requests.
- Keep seed tests and calibration paired with their catalog. An OOS banking request may be in scope for another sector. Nonbank scaling needs a positive minimum without assuming banking core IDs.
- Seed a workspace catalog and its test/calibration cases in one transaction. A failed case insert must roll back the catalog too, so retrying can recover the complete workspace instead of leaving a partial seed.
- Match English routing keywords at word boundaries. Substring matching makes "unblock" trigger "block"; verify that unblocking routes directly while an ambiguous card closure still asks for clarification.
- Capture old normalized fingerprints before translating. Earlier taxonomy manifests cannot substitute for the actual preceding language revision. Determine legacy targets from content fingerprints, not merely whether a workspace exists; otherwise an already-English partial catalog can briefly acquire a Turkish expansion and an unnecessary version.
- Guard specialized rules by available catalog/candidate IDs. Keep unsupported custom-field workflows as bounded previews rather than unanswerable collection loops.
- Model registrations are workspace-scoped. Reload choices on sector changes and never copy credentials implicitly. Bind request/SSE/poll clients immutably; remount workspace state and suppress callbacks after abort or settlement.
- HTTP 200 alone does not prove a valid model decision. Check protocol version, model ID, allowed questions/options, token usage, and schema. Use top-level provider usage once; do not double-count per-answer usage or treat conditional option scores as calibrated confidence.
- Update availability, UI descriptions, typed provider metadata, and HTTP fixtures together when adding a protocol. TypeSafe's `protocol`/`prompt_version` fields do not imply OpenAI `reasoning`, `max_tokens`, or `response_format` fields exist.
- Provider URL, protocol, and availability validation must agree at registration, listing, and inference. Reject a provider-specific endpoint under an incompatible generic protocol. Invalidate prior probe results after connection changes.
- If a future credential editor separates model and secret writes, retain the created model ID for retries, preserve an existing key on blank edits, never redisplay it, clear transient input on cancel/type changes/success, and make provider changes rollback-safe. Do not permanently remove a key before its model transaction succeeds.
- HTTP fixtures must clone or serialize responses. Sharing a mutable object with React state can hide missing state updates. Test provider failures at the network boundary instead of replacing internal embedding collaborators with incomplete mocks.
- Run backend tests and Vite builds sequentially: rebuilding `dist/assets` can race with FastAPI static-directory initialization. Confirm a process belongs to this project before stopping it; a port number alone is insufficient.
- Distinguish multiprocess startup timeouts from vector-index locking defects. A queue timeout alone does not identify the cause; rerun the failing test in isolation and then the full suite before attributing the failure. Retain assertions that concurrent callers build the corpus once and share the same index generation.
- Verify actual catalog provenance and endpoint before reindexing. A workspace called `demo` can contain imports. Preparation commands should report index preparation directly, without an extra query embedding. Disk vector identity excludes credentials; HTTP-client identity must track credential changes.
- TypeSafe evaluates questions in one request independently. Do not assume one answer becomes another question's input. Validate full option coverage, finite bounded probabilities, sum tolerance, and consistency between the selected option and maximum probability.
- A Choice option-count limit does not establish token-budget compliance. The historical full-text 800-intent request exceeded provider limits; reduced name/description shortlisting was frozen before the experiment rather than silently truncating after failure. See [the direct experiment](typesafe-jev.md#two-stage-experiment-without-embeddings).
- Distinguish a missing list field from explicit `null`. Safe diagnostics report field path, error code, and JSON type, never raw user/model values. Do not coerce malformed responses into successful empty arrays.
- A single user goal can still be ambiguous between two intents. Require an empty candidate array only when one intent is known or no candidate can be named; deleting genuine ambiguity candidates breaks clarification.
