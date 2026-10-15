import math
import re
import threading
import time
from collections import Counter

import httpx
import numpy as np

from .config import Settings
from .contracts import Candidate, Intent
from .providers import ModelUnavailable, is_openrouter, response_json
from .vector_index import IndexPreparation, IndexSnapshot, VectorIndex, build_corpus


def normalize(text: str) -> str:
    return text.translate(str.maketrans("İIıŞşĞğÜüÖöÇç", "iiissgguuoocc")).lower()


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def grams(text: str) -> Counter:
    value = " " + " ".join(tokens(text)) + " "
    return Counter(value[i:i+n] for n in (3, 4, 5) for i in range(len(value)-n+1))


class Embeddings:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.transport = transport
        self.model = None
        self.lock = threading.Lock()

    @property
    def enabled(self):
        return self.settings.embedding_mode == "local" or (
            self.settings.embedding_mode == "http"
            and bool(self.settings.embedding_base_url.strip())
            and (not is_openrouter(self.settings.embedding_base_url) or bool(self.settings.resolved_embedding_api_key))
        )

    def prepare_texts(self, texts: list[str], query=False) -> list[str]:
        profile = self.settings.resolved_embedding_profile
        if profile == "e5":
            return [("query: " if query else "passage: ") + text for text in texts]
        if profile == "qwen3" and query:
            return [f"Instruct: {self.settings.embedding_query_instruction}\nQuery:{text}" for text in texts]
        return list(texts)

    @property
    def metadata(self) -> dict:
        return {
            **({"connection_id": self.settings.embedding_connection_id} if self.settings.embedding_connection_id else {}),
            "model": self.settings.embedding_model,
            "mode": self.settings.embedding_mode,
            "profile": self.settings.resolved_embedding_profile,
            "query_instruction": self.settings.embedding_query_instruction if self.settings.resolved_embedding_profile == "qwen3" else None,
            "provider": "local" if self.settings.embedding_mode == "local" else ("openrouter" if is_openrouter(self.settings.embedding_base_url) else "openai_compatible"),
            "provider_only": list(self.settings.embedding_provider_only) if self.settings.embedding_mode == "http" and is_openrouter(self.settings.embedding_base_url) else [],
        }

    def encode(self, texts: list[str], query=False):
        if not self.enabled:
            raise ModelUnavailable("The embedding connection is not configured. Set the model mode, endpoint and API key if required.")
        prepared = self.prepare_texts(texts, query)
        if self.settings.embedding_mode == "local":
            with self.lock:
                if self.model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                        import torch
                        torch.set_num_threads(self.settings.embedding_cpu_threads)
                        self.model = SentenceTransformer(self.settings.embedding_model, local_files_only=self.settings.embedding_local_files_only)
                    except Exception as exc:
                        raise ModelUnavailable("The embedding model could not be loaded. Check ML dependencies and access to model files.") from exc
                # Input formatting is already applied for this model family.
                values = self.model.encode(prepared, prompt="", normalize_embeddings=True, show_progress_bar=False, batch_size=self.settings.embedding_batch_size)
        else:
            key = self.settings.resolved_embedding_api_key
            headers = {"Authorization": "Bearer " + key} if key else {}
            try:
                values = []
                with httpx.Client(timeout=self.settings.embedding_timeout_seconds, transport=self.transport) as client:
                    for offset in range(0, len(prepared), self.settings.embedding_batch_size):
                        batch = prepared[offset:offset+self.settings.embedding_batch_size]
                        payload = {"model": self.settings.embedding_model, "input": batch, "encoding_format": "float"}
                        if is_openrouter(self.settings.embedding_base_url) and self.settings.embedding_provider_only:
                            payload["provider"] = {"only": self.settings.embedding_provider_only}
                        response = client.post(self.settings.embedding_base_url.strip().rstrip("/") + "/embeddings", headers=headers, json=payload)
                        data = sorted(response_json(response, "Embedding")["data"], key=lambda item: item["index"])
                        if [item["index"] for item in data] != list(range(len(batch))):
                            raise ModelUnavailable("The embedding response has missing or duplicate indices.")
                        values.extend(item["embedding"] for item in data)
            except httpx.TimeoutException as exc:
                raise ModelUnavailable("The embedding service timed out.") from exc
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                raise ModelUnavailable("The embedding service could not be reached or returned an invalid response.") from exc
        try:
            array = np.asarray(values, dtype=np.float32)
        except (ValueError, TypeError) as exc:
            raise ModelUnavailable("Invalid embedding dimensions or values.") from exc
        if array.ndim != 2 or len(array) != len(texts) or not array.shape[1] or not np.isfinite(array).all():
            raise ModelUnavailable("Invalid embedding dimensions or values.")
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        if not np.isfinite(norms).all() or (norms <= 1e-12).any():
            raise ModelUnavailable("The embedding service returned an invalid zero vector.")
        return array / norms


class Retriever:
    def __init__(self, intents: list[Intent], version: str, embeddings: Embeddings, vector_index: VectorIndex | None = None):
        self.intents = {i.intent_id: i for i in intents}
        self.version = version
        self.embeddings = embeddings
        self.documents = build_corpus(intents, getattr(getattr(embeddings, "settings", None), "retrieval_representation", "combined"))
        self.vector_index = vector_index
        self.snapshot: IndexSnapshot | None = None
        counts = [grams(text) for _, _, text in self.documents]
        dfs = Counter(g for count in counts for g in count)
        self.idf = {g: math.log((len(counts)+1)/(df+1))+1 for g, df in dfs.items()}
        self.vectors = [self._vector(count) for count in counts]
        self.words = [Counter(tokens(text)) for _, _, text in self.documents]
        self.word_df = Counter(t for c in self.words for t in c)
        self.avg_len = sum(sum(c.values()) for c in self.words) / max(1, len(self.words))
        self.matrix = None
        self.index_lock = threading.Lock()

    def prepare_index(self) -> IndexPreparation:
        started = time.perf_counter()
        source = "memory"
        with self.index_lock:
            if self.matrix is None:
                if self.vector_index is None:
                    self.matrix = self.embeddings.encode([d.text for d in self.documents])
                    self.matrix.setflags(write=False)
                    source = "built"
                else:
                    acquired = self.vector_index.create_missing(
                        lambda: self.embeddings.encode([d.text for d in self.documents]))
                    self.snapshot = acquired.snapshot
                    self.matrix = self.snapshot.matrix
                    source = acquired.source
        return IndexPreparation(source=source, generation=self.snapshot.metadata.generation if self.snapshot else None,
                                document_count=len(self.documents), dimensions=self.matrix.shape[1],
                                elapsed_ms=round((time.perf_counter() - started) * 1000, 2))

    def rebuild_index(self) -> IndexPreparation:
        """Publish a new generation; callers already holding this matrix keep it."""
        if self.vector_index is None:
            raise ModelUnavailable("A persistent index is not configured.")
        started = time.perf_counter()
        acquired = self.vector_index.rebuild(lambda: self.embeddings.encode([d.text for d in self.documents]))
        return IndexPreparation(source=acquired.source, generation=acquired.snapshot.metadata.generation,
                                document_count=len(self.documents), dimensions=acquired.snapshot.metadata.dimensions,
                                elapsed_ms=round((time.perf_counter() - started) * 1000, 2))

    def index_is_current(self) -> bool:
        return self.snapshot is None or self.vector_index is None or self.snapshot.revision == self.vector_index.revision()

    def _vector(self, counts):
        vector = {g: (1+math.log(c))*self.idf.get(g, 1) for g, c in counts.items() if g in self.idf}
        norm = math.sqrt(sum(v*v for v in vector.values())) or 1
        return {g: v/norm for g, v in vector.items()}

    def search(self, query: str, mode="lexical", k=20, active_intent=None) -> list[Candidate]:
        return self.search_with_trace(query, mode, k, active_intent)[0]

    def search_with_trace(self, query: str, mode="lexical", k=20, active_intent=None,
                          source_k=40, semantic_weight=.5):
        trace = {"executed": True, "completed": False, "source": mode,
                 "source_k": source_k, "semantic": [], "lexical": [], "fusion": [], "pool": []}
        if not self.documents:
            trace["completed"] = True
            return [], trace
        def intent_ids(order):
            return list(dict.fromkeys(self.documents[j][0] for j in order))
        lexical, lex_order = None, []
        if mode != "e5":
            vector = self._vector(grams(query))
            qwords = set(tokens(query))
            lexical = []
            for c, words in zip(self.vectors, self.words):
                cosine = sum(value*c.get(g, 0) for g, value in vector.items())
                bm25 = 0.0
                for token in qwords:
                    tf = words.get(token, 0)
                    if tf:
                        idf = math.log(1+(len(self.words)-self.word_df[token]+.5)/(self.word_df[token]+.5))
                        bm25 += idf * tf*2.2/(tf+1.2*(.25+.75*sum(words.values())/self.avg_len))
                lexical.append(.75*cosine+.25*(1-math.exp(-bm25/8)))
            lex_order = sorted(range(len(lexical)), key=lambda j: (-lexical[j], j))
            trace["lexical"] = intent_ids(lex_order)[:source_k]
        scores, semantic = {}, None
        if mode in ("e5", "hybrid"):
            trace["index_preparation"] = self.prepare_index().model_dump()
            qvector = self.embeddings.encode([query], query=True)
            if qvector.shape[1] != self.matrix.shape[1]:
                raise ModelUnavailable("Query and index embedding dimensions differ.")
            semantic = (self.matrix @ qvector[0]).tolist()
            sem_order = sorted(range(len(semantic)), key=lambda j: (-semantic[j], j))
            trace["semantic"] = intent_ids(sem_order)[:source_k]
            if mode == "e5":
                scores = {j: semantic[j] for j in sem_order}
            else:
                # Rank lists are deduplicated by intent before fusion: many exemplars cannot crowd out classes.
                representatives = {}
                for order, weight in [(sem_order, semantic_weight), (lex_order, 1-semantic_weight)]:
                    seen, rank = set(), 0
                    for j in order:
                        iid = self.documents[j][0]
                        if iid in seen:
                            continue
                        seen.add(iid)
                        rank += 1
                        if rank > source_k:
                            break
                        representative = representatives.setdefault(iid, j)
                        scores[representative] = scores.get(representative, 0) + 2*weight/(60+rank)
        else:
            scores = {j: lexical[j] for j in lex_order}
        grouped = {}
        for j, score in scores.items():
            iid, example, _ = self.documents[j]
            if iid not in grouped or score > grouped[iid].score:
                intent = self.intents[iid]
                grouped[iid] = Candidate(intent_id=iid, name=intent.name, domain=intent.domain, score=round(score, 6), score_type={"lexical":"lexical_similarity", "e5":"cosine_similarity", "hybrid":"reciprocal_rank_fusion"}[mode], evidence=example, lexical_score=round(lexical[j], 6) if lexical is not None else None, semantic_score=round(semantic[j], 6) if semantic else None)
        ranked = sorted(grouped.values(), key=lambda c: (-c.score, c.intent_id))
        trace["fusion"] = [c.intent_id for c in ranked[:source_k]]
        result = ranked[:k]
        # Soft context and close neighbors never remove the global search path.
        additions = ([active_intent] if active_intent in grouped else [])
        for candidate in ranked[:3]:
            additions += self.intents[candidate.intent_id].confusable_with
        forced = [grouped[iid] for iid in dict.fromkeys(additions) if iid in grouped][:min(k, 5)]
        forced_ids = {c.intent_id for c in forced}
        result = [c for c in ranked if c.intent_id not in forced_ids][:k-len(forced)] + forced
        result = sorted(result, key=lambda c: (-c.score, c.intent_id))
        trace.update(completed=True, pool=[c.intent_id for c in result])
        return result, trace
