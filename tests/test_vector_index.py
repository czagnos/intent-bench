"""Persistent index behavior at the filesystem and embedding HTTP boundaries."""
import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.config import Settings
from app.contracts import Intent
from app.service import Studio
from app.store import Store


def index_settings(directory: Path, **changes) -> Settings:
    return Settings(_env_file=None, data_dir=directory, embedding_mode="http",
                    embedding_base_url="https://vectors.example/v1", embedding_model="test-model",
                    embedding_api_key="first-secret", embedding_connection_id="saved-model",
                    embedding_profile="plain", **changes)


def catalog() -> list[Intent]:
    return [Intent(intent_id="card.limit", name="Card limit", domain="card",
                   description="Change card limit", examples=["Raise my limit", "Lower my limit"],
                   workflow_id="card_limit"),
            Intent(intent_id="account.balance", name="Account balance", domain="account",
                   description="Show balance", examples=["What is my balance?"],
                   workflow_id="account_balance")]


def save_catalog(directory: Path, workspace: str = "bank") -> str:
    return Store(directory).save_catalog(workspace, [i.model_dump() for i in catalog()])


def embedding_transport(requests: list[httpx.Request]) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": n, "embedding": [1., float(n + 1)]}
                                                 for n in range(len(texts))]})
    return httpx.MockTransport(respond)


def test_fresh_studio_reuses_persisted_corpus_and_embeds_only_its_query(tmp_path):
    settings = index_settings(tmp_path)
    save_catalog(tmp_path)
    requests = []
    first = Studio(settings)
    first.embeddings.transport = embedding_transport(requests)
    try:
        first_candidates = first.retriever("bank").search("Raise my limit", "e5")
    finally:
        first.close()
    requests.clear()
    second = Studio(settings)
    second.embeddings.transport = embedding_transport(requests)
    try:
        second_candidates = second.retriever("bank").search("Raise my limit", "e5")
    finally:
        second.close()
    assert [json.loads(r.content)["input"] for r in requests] == [["Raise my limit"]]
    assert second_candidates == first_candidates
    assert len(list((tmp_path / "vector-indexes").glob("*.npz"))) == 1


def test_default_credential_rotation_reuses_disk_vectors_with_fresh_http_auth(tmp_path):
    settings = index_settings(tmp_path)
    settings.embedding_connection_id = None
    save_catalog(tmp_path)
    requests = []
    studio = Studio(settings)
    studio.embeddings.transport = embedding_transport(requests)
    try:
        original = studio.retriever("bank")
        original.prepare_index()
        requests.clear()
        rotated = settings.model_copy(update={"embedding_api_key": "second-secret"})
        refreshed = studio.retriever("bank", settings=rotated)
        refreshed.search("fresh private query", "e5")
        assert [r.headers["Authorization"] for r in requests] == ["Bearer second-secret"]
        assert len(list((tmp_path / "vector-indexes").glob("*.npz"))) == 1
        artifact = next((tmp_path / "vector-indexes").glob("*.npz")).read_bytes()
        for secret in (b"first-secret", b"second-secret", b"fresh private query"):
            assert secret not in artifact
    finally:
        studio.close()


def test_disk_identity_isolates_corpus_and_embedding_configuration(tmp_path):
    from app.model_catalog import embedding_key
    from app.retrieval import Embeddings
    from app.vector_index import CorpusRow, build_corpus, make_identity

    settings = index_settings(tmp_path)
    rows = build_corpus(catalog(), "combined")
    original = make_identity("bank", "version", embedding_key(settings), "combined", rows)
    variants = [
        make_identity("other", "version", embedding_key(settings), "combined", rows),
        make_identity("bank", "other", embedding_key(settings), "combined", rows),
        make_identity("bank", "version", embedding_key(settings), "combined", list(reversed(rows))),
        make_identity("bank", "version", embedding_key(settings), "combined",
                      [rows[0]._replace(evidence="different evidence"), *rows[1:]]),
        make_identity("bank", "version", embedding_key(settings), "combined",
                      [rows[0]._replace(text="different model input"), *rows[1:]]),
        make_identity("bank", "version", embedding_key(settings), "combined",
                      [rows[0]._replace(intent_id="other.intent"), *rows[1:]]),
    ]
    changes = [{"embedding_model": "other"}, {"embedding_base_url": "https://other.example/v1"},
               {"embedding_base_url": "https://openrouter.ai/api/v1", "embedding_provider_only": ["nebius"]},
               {"embedding_profile": "e5"}, {"retrieval_representation": "separate"}]
    for change in changes:
        modified = settings.model_copy(update=change)
        documents = build_corpus(catalog(), modified.retrieval_representation)
        texts = Embeddings(modified).prepare_texts([r.text for r in documents])
        variants.append(make_identity("bank", "version", embedding_key(modified), modified.retrieval_representation,
                                      [CorpusRow(row.intent_id, row.evidence, text) for row, text in zip(documents, texts)]))
    assert len({i.digest for i in [original, *variants]}) == len(variants) + 1
    for change in ({"llm_model": "other"}, {"candidate_k": 5}, {"embedding_api_key": "rotated"}):
        modified = settings.model_copy(update=change)
        assert make_identity("bank", "version", embedding_key(modified), "combined", rows) == original


@pytest.mark.parametrize("corruption", ["identity", "shape", "dtype", "nan", "zero", "unnormalized", "truncated", "pickle"])
def test_corrupt_artifact_requires_reindex_without_corpus_rebuild(tmp_path, corruption):
    from app.providers import ModelUnavailable

    settings = index_settings(tmp_path)
    save_catalog(tmp_path)
    requests = []
    studio = Studio(settings)
    studio.embeddings.transport = embedding_transport(requests)
    try:
        studio.retriever("bank").prepare_index()
    finally:
        studio.close()
    path = next((tmp_path / "vector-indexes").glob("*.npz"))
    with np.load(path, allow_pickle=False) as bundle:
        matrix = bundle["matrix"]
        metadata = json.loads(str(bundle["metadata"].item()))
    if corruption == "identity":
        metadata["identity"]["workspace"] = "other"
    elif corruption == "shape":
        matrix = matrix[:-1]
    elif corruption == "dtype":
        matrix = matrix.astype(np.float64)
    elif corruption == "nan":
        matrix[0, 0] = float("nan")
    elif corruption == "zero":
        matrix[0] = 0
    elif corruption == "unnormalized":
        matrix[0] *= 2
    elif corruption == "pickle":
        matrix = np.asarray([[object()]], dtype=object)
    if corruption == "truncated":
        path.write_bytes(b"raw-private-secret-corruption")
    else:
        np.savez(path, matrix=matrix, metadata=np.asarray(json.dumps(metadata)))
    requests.clear()
    fresh = Studio(settings)
    fresh.embeddings.transport = embedding_transport(requests)
    try:
        with pytest.raises(ModelUnavailable, match="reindex") as error:
            fresh.retriever("bank").search("new query", "e5")
        assert "private-secret" not in str(error.value)
        assert not requests
    finally:
        fresh.close()


def test_failed_atomic_publication_preserves_previous_generation(tmp_path, monkeypatch):
    import os
    from app.providers import ModelUnavailable

    settings = index_settings(tmp_path)
    save_catalog(tmp_path)
    requests = []
    studio = Studio(settings)
    studio.embeddings.transport = embedding_transport(requests)
    try:
        retriever = studio.retriever("bank")
        first = retriever.prepare_index()
        artifact = retriever.vector_index.path
        previous = artifact.read_bytes()
        def fail_replace(source, destination):
            raise OSError("sensitive filesystem details")
        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(ModelUnavailable, match="yazılamadı") as error:
            retriever.vector_index.rebuild(lambda: retriever.embeddings.encode([d.text for d in retriever.documents]))
        assert "sensitive" not in str(error.value)
        assert artifact.read_bytes() == previous
        assert retriever.vector_index.load().metadata.generation == first.generation
        assert not list(artifact.parent.glob("*.tmp"))
    finally:
        studio.close()


def _prepare_in_process(directory, barrier, results):
    import time

    studio = Studio(index_settings(Path(directory)))
    requests = []
    def respond(request):
        requests.append(request)
        time.sleep(.15)  # Keep the independent embedding boundary calls overlapping.
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1., 1.]} for i in range(len(texts))]})
    studio.embeddings.transport = httpx.MockTransport(respond)
    try:
        retriever = studio.retriever("bank")
        barrier.wait(timeout=10)
        preparation = retriever.prepare_index()
        results.put((preparation.source, preparation.generation, len(requests)))
    finally:
        studio.close()


def test_concurrent_processes_build_missing_corpus_only_once(tmp_path):
    import multiprocessing

    save_catalog(tmp_path)
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(3), context.Queue()
    processes = [context.Process(target=_prepare_in_process, args=(str(tmp_path), barrier, results)) for _ in range(3)]
    try:
        for process in processes:
            process.start()
        observed = [results.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=5)
            assert process.exitcode == 0
        assert sum(calls for _, _, calls in observed) == 1
        assert sorted(source for source, _, _ in observed) == ["built", "disk", "disk"]
        assert len({generation for _, generation, _ in observed}) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()


def test_reindex_refreshes_next_lookup_without_mutating_held_retriever(tmp_path):
    settings = index_settings(tmp_path)
    save_catalog(tmp_path)
    current_matrix = [[1., 0.], [1., 0.], [0., 1.]]
    def respond(request):
        texts = json.loads(request.content)["input"]
        values = [[1., 0.]] if len(texts) == 1 else current_matrix
        return httpx.Response(200, json={"data": [{"index": n, "embedding": value} for n, value in enumerate(values)]})
    studio = Studio(settings)
    studio.embeddings.transport = httpx.MockTransport(respond)
    try:
        held = studio.retriever("bank")
        assert held.search("query", "e5", k=1)[0].intent_id == "card.limit"
        generation = held.prepare_index().generation
        current_matrix = [[0., 1.], [0., 1.], [1., 0.]]
        held.vector_index.rebuild(lambda: held.embeddings.encode([d.text for d in held.documents]))
        fresh = studio.retriever("bank")
        assert fresh.search("query", "e5", k=1)[0].intent_id == "account.balance"
        assert fresh.prepare_index().generation != generation
        assert held.search("query", "e5", k=1)[0].intent_id == "card.limit"
        assert held.prepare_index().generation == generation
        with pytest.raises(ValueError):
            held.matrix[0, 0] = 0
    finally:
        studio.close()


def test_evaluation_pins_one_generation_across_variants(tmp_path):
    from app.model_catalog import Variant

    settings = index_settings(tmp_path)
    version = save_catalog(tmp_path)
    studio = Studio(settings)
    query_count = 0
    current_matrix = [[1., 0.], [1., 0.], [0., 1.]]
    def respond(request):
        nonlocal query_count, current_matrix
        texts = json.loads(request.content)["input"]
        if len(texts) == 1:
            query_count += 1
            if query_count == 1:
                current_matrix = [[0., 1.], [0., 1.], [1., 0.]]
                studio.retriever("bank").rebuild_index()
            values = [[1., 0.]]
        else:
            values = current_matrix
        return httpx.Response(200, json={"data": [{"index": n, "embedding": value} for n, value in enumerate(values)]})
    studio.embeddings.transport = httpx.MockTransport(respond)
    scope = {"version": version, "metadata": {"intent_count": 2}}
    variants = [Variant(name, "e5", settings, "default", None) for name in ("first", "second")]
    runs = [(v, scope, {**v.metadata, "catalog": scope["metadata"]}) for v in variants]
    case = {"case_id": "case1", "question": "Raise my limit", "expected_decision": "route", "expected_intent_id": "card.limit"}
    try:
        job = studio.store.create_job("bank", "evaluation", {"total": 2})
        studio.run_evaluation("bank", job["id"], [case], runs, {}, [])
        output = studio.store.job("bank", job["id"])
        assert output["status"] == "completed"
        assert [r["records"][0]["intent_id"] for r in output["results"].values()] == ["card.limit", "card.limit"]
        assert studio.retriever("bank").search("later route", "e5", k=1)[0].intent_id == "account.balance"
    finally:
        studio.close()


def test_catalog_import_persists_before_publication_and_fresh_studio_reuses_it(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    settings = index_settings(tmp_path)
    requests = []
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = embedding_transport(requests)
        response = client.post("/v1/catalog/import?workspace=bank", json=[i.model_dump() for i in catalog()])
        assert response.status_code == 200
    requests.clear()
    fresh = Studio(settings)
    fresh.embeddings.transport = embedding_transport(requests)
    try:
        fresh.retriever("bank").search("query", "e5")
        assert [json.loads(r.content)["input"] for r in requests] == [["query"]]
    finally:
        fresh.close()


def test_catalog_import_storage_failure_keeps_active_catalog(tmp_path, monkeypatch):
    import os
    from fastapi.testclient import TestClient
    from app.main import create_app

    settings = index_settings(tmp_path)
    original = save_catalog(tmp_path)
    requests = []
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = embedding_transport(requests)
        updated = catalog()
        updated[0].description = "Changed catalog description"
        def fail_replace(source, destination):
            raise OSError("private disk detail")
        monkeypatch.setattr(os, "replace", fail_replace)
        response = client.post("/v1/catalog/import?workspace=bank", json=[i.model_dump() for i in updated])
        assert response.status_code == 503
        assert "private disk detail" not in response.text
        assert client.app.state.studio.store.catalog("bank")["version"] == original


def test_route_reports_its_actual_index_preparation_source(tmp_path):
    settings = index_settings(tmp_path)
    save_catalog(tmp_path)
    requests = []
    observed = []
    generations = []
    for _ in range(2):
        studio = Studio(settings)
        studio.embeddings.transport = embedding_transport(requests)
        try:
            for _ in range(2):
                result, _ = studio.compute("Raise my limit", {"messages": []}, "e5", studio.retriever("bank"))
                preparation = result.get("index_preparation")
                assert preparation is not None
                observed.append(preparation["source"])
                generations.append(preparation["generation"])
                assert preparation["document_count"] == 3
                assert preparation["dimensions"] == 2
                assert preparation["elapsed_ms"] >= 0
        finally:
            studio.close()
    assert observed == ["built", "memory", "disk", "memory"]
    assert len(set(generations)) == 1


def test_evaluation_counts_disk_reuse_as_cache_hit(tmp_path):
    from app.model_catalog import Variant

    settings = index_settings(tmp_path)
    version = save_catalog(tmp_path)
    requests = []
    first = Studio(settings)
    first.embeddings.transport = embedding_transport(requests)
    try:
        generation = first.retriever("bank").prepare_index().generation
    finally:
        first.close()
    fresh = Studio(settings)
    fresh.embeddings.transport = embedding_transport(requests)
    variant = Variant("semantic", "e5", settings, "default", None)
    scope = {"version": version, "metadata": {"intent_count": 2}}
    case = {"case_id": "case1", "question": "Raise my limit", "expected_decision": "route", "expected_intent_id": "card.limit"}
    try:
        job = fresh.store.create_job("bank", "evaluation", {"total": 1})
        fresh.run_evaluation("bank", job["id"], [case], [(variant, scope, {**variant.metadata, "catalog": scope["metadata"]})], {}, [])
        result = fresh.store.job("bank", job["id"])["results"]["semantic"]
        assert result["index_cache_hit"] is True
        assert result["index_preparation"]["source"] == "disk"
        assert result["index_preparation"]["generation"] == generation
        assert result["records"][0]["index_preparation"]["source"] == "memory"
    finally:
        fresh.close()


def test_loaded_revision_tracks_open_descriptor_when_path_is_replaced(tmp_path, monkeypatch):
    from app.vector_index import IndexMetadata

    settings = index_settings(tmp_path)
    save_catalog(tmp_path)
    requests = []
    first = Studio(settings)
    first.embeddings.transport = embedding_transport(requests)
    try:
        first_retriever = first.retriever("bank")
        initial = first_retriever.prepare_index()
        artifact = first_retriever.vector_index.path
        with np.load(artifact, allow_pickle=False) as bundle:
            metadata = IndexMetadata.model_validate_json(str(bundle["metadata"].item()))
            matrix = bundle["matrix"]
        replacement = artifact.with_suffix(".replacement")
        with replacement.open("wb") as stream:
            np.savez(stream, matrix=matrix, metadata=np.asarray(metadata.model_copy(update={"generation": "replacement-generation"}).model_dump_json()))
    finally:
        first.close()
    original_open = Path.open
    def replace_after_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == artifact and mode == "rb" and replacement.exists():
            replacement.replace(artifact)
        return stream
    monkeypatch.setattr(Path, "open", replace_after_open)
    fresh = Studio(settings)
    fresh.embeddings.transport = embedding_transport(requests)
    try:
        held = fresh.retriever("bank")
        assert held.prepare_index().generation == initial.generation
        assert held.index_is_current() is False
        assert fresh.retriever("bank").prepare_index().generation == "replacement-generation"
    finally:
        fresh.close()
