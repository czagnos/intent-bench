# Selecting embedding models for intent retrieval

Choose embeddings by their ability to retrieve the correct intent under your actual taxonomy, language, and transcript conditions. Measure candidate Recall@5/10/20 first, then end-to-end decision accuracy, OOS behavior, and warm-query p95. A better retrieval score does not establish a better final decision model.

The application supports multiple registered embedding connections and model combinations. Use **Model catalog**, **Calibration**, and **Experiments** rather than changing `.env` between every run. Keep catalog, cases, K, decision model, and policy fixed when comparing embeddings. See [model comparison](model-comparison.md).

## Input formatting and candidates

| Model/profile family | Supported formatting | Comparison purpose |
|---|---|---|
| Qwen3 Embedding 4B / 8B | `qwen3`: English task instruction plus the original request | Compare model sizes while keeping formatting fixed |
| Qwen3 Embedding 0.6B | Local or supported provider with the matching profile | Evaluate a smaller model under measured hardware conditions |
| Multilingual E5 | `e5`: query and passage prefixes | Compare with earlier E5 experiments |
| BGE-M3 | `plain`: dense embedding without a prefix | Compare a different multilingual embedding family |

Current retrieval instructions describe matching a request to a supported intent definition without fixing the sector to banking. User text is preserved. A custom served-model name can hide the family from automatic detection; select its profile explicitly. Do not apply a Qwen/E5 prefix to an unrelated model without checking that model's input contract.

This adapter uses BGE-M3's dense vectors. Its sparse and multiple-vector modes are not enabled; the separate lexical source remains BM25/character TF-IDF. Consult the original model cards for deployment and licensing requirements: [Qwen3 4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B), [Qwen3 8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B), [BGE-M3](https://huggingface.co/BAAI/bge-m3), and [E5](https://huggingface.co/intfloat/multilingual-e5-large).

## Historical selection rationale: 8 September 2026

The original Turkish banking prototype selected Qwen3 Embedding 4B as its first cloud trial candidate. Its recorded rationale was downloadable Apache-2.0 weights, multilingual/task-instruction support, a published comparison positioning 4B between 0.6B and 8B, and availability in the OpenRouter catalog checked that day. Published multilingual benchmark scores were not Turkish banking accuracy measurements.

The recorded candidate order was 4B, 8B, 0.6B, E5, and BGE-M3. Qwen3 0.6B was absent from that historical OpenRouter embedding listing; a model page alone did not establish account access. [OpenRouter's embedding API](https://openrouter.ai/docs/api_reference/embeddings) and live discovery should be checked for a new experiment.

[Microsoft Harrier-oss-v1-0.6b](https://huggingface.co/microsoft/harrier-oss-v1-0.6b) was noted as another possible family in the original investigation. No Harrier-specific formatting integration or benchmark was completed. These historical notes are not current recommendations or rankings for the new English sector catalogs.

## Separate preparation, retrieval, and decisions

Comparing catalog vectors and computing a new query embedding are different costs. Each intent can have multiple indexed examples, so an 800-intent catalog contains more than 800 vectors. Compatible catalog vectors persist on disk; query embeddings are computed per new request. Report cold/index preparation separately from warm-query latency. HTTP transport, provider queues, and hardware remain part of measured query time.

An older Turkish 26-route-case E5 snapshot reported Recall@20 of 26/26, routing accuracy of 23/26, and false acceptance of all three OOS cases. The candidate stage had already found every expected intent; changing embeddings alone could not demonstrate that the final decision problem was solved. Those figures describe the earlier dataset and policy, not current English catalogs or customer traffic.

If the expected intent is absent, inspect taxonomy, examples, input formatting, and retrieval. If it is present but the final decision fails, inspect the selector, clarification contract, and policy. Refit rejection thresholds after embedding/catalog changes, and evaluate on an independent test split.

## Verification limits

Provider adapters have controlled HTTP tests for formatting, key resolution, batch ordering, errors, and routing integration. Those tests do not establish live access, model accuracy, latency, or cost. Record the actual provider/model identity and conditions for every real comparison.
