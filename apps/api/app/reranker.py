"""Optional cross-encoder ranking; no generative answer or probability claim."""
import math
import threading

import httpx
import numpy as np

from .providers import ModelUnavailable, response_json


class Reranker:
    def __init__(self, settings, transport=None):
        self.settings, self.transport = settings, transport
        self.model = None
        self.lock = threading.Lock()

    @property
    def enabled(self):
        return self.settings.reranker_mode == "local" or (
            self.settings.reranker_mode == "http" and bool(self.settings.reranker_base_url.strip()))

    @property
    def metadata(self):
        s = self.settings
        return {"model": s.reranker_model, "mode": s.reranker_mode,
                "protocol": s.reranker_protocol if s.reranker_mode == "http" else "cross_encoder",
                "connection_id": s.reranker_connection_id or None,
                "timeout_seconds": s.reranker_timeout_seconds,
                "document_format": "intent-description-example-exclusions-rule-v1"}

    def prepare(self):
        if not self.enabled:
            raise ModelUnavailable("Reranker connection is not configured.")
        if self.settings.reranker_mode == "local":
            with self.lock:
                if self.model is None:
                    try:
                        from sentence_transformers import CrossEncoder
                        self.model = CrossEncoder(self.settings.reranker_model,
                                                  local_files_only=self.settings.reranker_local_files_only,
                                                  max_length=512)
                    except Exception as exc:
                        raise ModelUnavailable("Could not load the reranker. Check ML dependencies and local model files.") from exc

    def scores(self, query, documents):
        self.prepare()
        if not documents:
            return []
        s = self.settings
        if s.reranker_mode == "local":
            try:
                with self.lock:
                    values = np.asarray(self.model.predict([[query, text] for text in documents],
                                        batch_size=s.reranker_batch_size, show_progress_bar=False)).reshape(-1).tolist()
            except Exception as exc:
                raise ModelUnavailable("The local reranker request failed.") from exc
        else:
            headers = {"Authorization": "Bearer " + s.reranker_api_key.strip()} if s.reranker_api_key.strip() else {}
            payload = ({"query": query, "texts": documents, "raw_scores": True}
                       if s.reranker_protocol == "tei" else
                       {"model": s.reranker_model, "query": query, "documents": documents, "top_n": len(documents)})
            try:
                with httpx.Client(timeout=s.reranker_timeout_seconds, transport=self.transport) as client:
                    response = client.post(s.reranker_base_url.strip().rstrip("/") + "/rerank", headers=headers, json=payload)
                    data = response_json(response, "Reranker", allow_list=s.reranker_protocol == "tei")
                rows = data if s.reranker_protocol == "tei" else data["results"]
                if not isinstance(rows, list) or len(rows) != len(documents):
                    raise ValueError("Incomplete ranking")
                by_index = {}
                for row in rows:
                    index = row["index"]
                    if type(index) is not int or index in by_index or not 0 <= index < len(documents):
                        raise ValueError("Invalid ranking index")
                    by_index[index] = row["score" if s.reranker_protocol == "tei" else "relevance_score"]
                values = [by_index[i] for i in range(len(documents))]
            except httpx.TimeoutException as exc:
                raise ModelUnavailable("The reranker request timed out.") from exc
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise ModelUnavailable("Invalid reranker connection or ranking response.") from exc
        if len(values) != len(documents) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ModelUnavailable("The reranker must return finite numeric scores.")
        return values

    def rank(self, query, candidates, catalog, k):
        documents = []
        for c in candidates:
            intent = catalog[c.intent_id]
            text = f"{intent.name}. {intent.description}\nExample: {c.evidence}"
            if intent.exclusions:
                text += "\nExclusions: " + " | ".join(intent.exclusions)
            if intent.selection_rule:
                text += "\nSelection rule: " + intent.selection_rule
            documents.append(text)
        scores = self.scores(query, documents)
        order = sorted(range(len(scores)), key=lambda j: (-scores[j], j))
        return [candidates[j].model_copy(update={"score": round(scores[j], 6), "score_type": "reranker_score"}) for j in order[:k]]
