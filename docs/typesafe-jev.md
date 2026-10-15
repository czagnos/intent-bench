# TypeSafe Jev for intent selection

Jev is a direct TypeSafe connection for choosing among intent candidates. Existing embedding and retrieval stages remain in place, so you can compare it with other decision models using the same sector catalog and reviewed cases.

TypeSafe describes its approach as Reinforcement Learning for Calibrated Decisions (RLCD). That is a provider description, not an IntentBench measurement of calibration, speed, or accuracy. See the [provider primer](https://docs.typesafe.ai/introduction/machine-learning-primer).

## Setup

1. Add the key to the server `.env`:

   ```dotenv
   INTENT_TYPESAFE_API_KEY=your_typesafe_key
   ```

2. In the selected sector, open **Model catalog → Add TypeSafe Jev**. Defaults are connection **TypeSafe**, kind **LLM**, model `jev-1.13.0`, base URL `https://api.typesafe.ai/v1`, and key-variable name `INTENT_TYPESAFE_API_KEY`. Do not paste the key into the variable-name field.
3. Use **Save model** and **Test connection**. The synthetic probe checks access and the decision protocol and can incur charges. If you add the key after saving, use **Refresh connections**.
4. In **Live demo → Hybrid retrieval + LLM → Decision model (LLM)**, select Jev and an available embedding connection.

The registration stores the variable name, not its value. Custom names such as `INTENT_MODEL_KEY_TYPESAFE_TRIAL` are supported. OpenRouter keys are not inherited. File-based credentials are read for new operations; process environment variables take precedence. Restart after changing a process/Docker `env_file` value. `INTENT_MODEL_CREDENTIALS_FILE` selects another credential file.

```bash
.venv/bin/python scripts/check_models.py --llm-only --llm-id model_REPLACE_WITH_ID --workspace airline
```

## API and decisions

The native request uses `POST /systemone`, bearer authentication, and `model`, `state`, and `questions`. Choice responses contain an allowed option, probabilities, and confidence metadata. See the [API](https://docs.typesafe.ai/api) and [Choice reference](https://docs.typesafe.ai/primitives/choice).

IntentBench asks for the main decision and potential clarification candidates in one HTTP request. Inputs include the current utterance, recent conversation, active intent, and candidate definitions/rules. Expected test labels are excluded. TypeSafe questions in one request are independent; additional clarification answers are used only when the main decision needs them.

Jev does not generate conversation or slot-collection text. The server constructs clarification text from candidate names and applies the normal workflow policy. Unknown candidates, invalid probability distributions, or malformed responses become technical errors. No automatic confidence threshold is added; TypeSafe confidence is separate from embedding OOS calibration.

The adapter sends no OpenAI `messages`, `response_format`, temperature, reasoning, or output-token parameter. The form hides those options but exposes timeout. There is no automatic retry or model fallback. Provider input/output token usage maps to the shared prompt/completion/total fields. Results record provider and prompt version; the current selector protocol is `router-en-typesafe-v2-multisector-choice`.

## Model versions and cost

The form pins `jev-1.13.0`. Aliases such as `jev-latest` can change over time. Consult the [provider's model/pricing page](https://docs.typesafe.ai/models) for current access, prices, and limits.

The original guide recorded a **17 September 2026** price of $0.042 per million input tokens and no output-token charge. This is a historical record, not a current quote. Calculate observed usage from the provider's input-token report, including state and all questions, rather than from the user's utterance alone. IntentBench does not provide billing or automatic price updates.

## Controlled comparison

Choose only **Hybrid retrieval + LLM** in **Experiments**. Hold one embedding, retrieval strategy, candidate budget, catalog size, source, and case cohort fixed. Select Jev and the comparison model together. Inspect routing and decision accuracy, unnecessary clarification, OOS false acceptance, technical errors, selection time, and total p95.

Use starter cases to check behavior, then evaluate on independent reviewed data. Changing a selector cannot recover a correct intent that retrieval never supplies. Controlled HTTP/UI tests prove integration behavior, not real Jev speed, accuracy, or cost superiority.

## Two-stage experiment without embeddings

`scripts/evaluate_direct_jev.py` implements a fixed banking 800-intent experiment separate from the ordinary retrieval pipeline. Before inference it validates a source evaluation's catalog snapshot, ordered reviewed seed/test cohort, fingerprints, registered `jev-1.13.0` settings, and current selector prompt version. It rejects changed data/configuration. Historical pre-English evaluations need a matching new source run; they are not silently upgraded.

The first stage sorts IDs alphabetically into four groups of 200. One request contains four independent Choice questions, each with 200 intents plus `@none`. The rubric contains only names and descriptions. Five intents are selected from each group's own probability order; probabilities are not compared across groups. ID order breaks ties. Zero-probability entries can fill the fixed budget, and their presence and fifth-place ties are recorded.

The second call passes those 20 candidates to the normal TypeSafe selector with complete descriptions, one fixed catalog example, exclusions, and rules. No embedding, lexical retrieval, or contextual early decision is used. Server policy runs after selection. Interpret outcomes as results of this specific two-stage protocol.

```bash
.venv/bin/python scripts/evaluate_direct_jev.py \
  --source-evaluation /absolute/path/evaluation.json \
  --output artifacts/runs/jev-direct-800-two-stage.json
```

Use `--limit 1` for a subset probe. Output must be a new path under `artifacts/runs`; each case creates a checkpoint. Both calls' usage is summed and stage timings stay separate. If stage two fails, known stage-one usage/candidates remain. The first technical failure stops the run without retry, silent truncation, or fallback.

The historical `jev-1.13` limits documented 64k tokens for state plus all questions, and 32k for state plus the longest question. A full-text first-stage request returned `400 / max_tokens_exceeded`; name/description-only shortlisting was fixed before the full experiment. The current English shortlist protocol is `jev-partition-shortlist-v3-english-multisector`. Longer inputs can still exceed limits. Check [the provider's version-specific limits](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md).

## Historical live probe: 17 September 2026

The original Turkish banking probe used four synthetic utterances, the 48-core catalog, lexical top-20 candidates, no embeddings, and three Choice questions per request. It was not a semantic/hybrid benchmark or customer-data evaluation.

| Scenario | Observed result |
|---|---|
| Clear routing request | Correct `route → card.limit.change` |
| Ambiguous card-closure request | Incorrect `route → card.cancel` instead of clarification |
| Multiple goals | Correct `clarify / multiple_intents`, with `card.limit.change` and `account.balance` |
| Out-of-scope request | Correct `out_of_scope` |

All four responses passed technical validation. Individual calls took approximately 0.85–1.20 seconds and reported 12,984–15,521 input and 632–647 output tokens. Each scenario had one observation; these are not p95 estimates, general accuracy, or evidence of superiority. The ambiguity error was retained rather than tuned away. Current English catalogs and prompts must be evaluated separately.
