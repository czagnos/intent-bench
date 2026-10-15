import copy
import json
import sys
import threading
import time
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.contracts import EvaluationRequest
from app.main import create_app
from app.store import fingerprint
from test_evaluation_controls import embedding_response, selection_response, settings, wait_job


def test_repetitions_preserve_cohort_and_settings_with_unique_results(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post('/v1/evaluations', json={
            'methods': ['lexical'], 'limit': 3, 'repetitions': 2,
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'completed'
        assert job['progress'] == job['total'] == 6
        assert list(job['results']) == ['lexical__repeat_1', 'lexical__repeat_2']
        assert [variant['id'] for variant in job['variants']] == list(job['results'])
        first, second = job['results'].values()
        assert first['group_id'] == second['group_id'] == 'lexical'
        assert [first['repeat_index'], second['repeat_index']] == [1, 2]
        assert first['catalog'] == second['catalog']
        for key in ('model', 'embedding', 'llm', 'candidate_k', 'prompt_version', 'calibration'):
            assert first[key] == second[key]
        first_cases = [record['case_id'] for record in first['records']]
        assert first_cases == [record['case_id'] for record in second['records']]
        assert len(set(first_cases)) == 3
        assert all(result['complete'] and result['completed_count'] == result['selected_count'] == 3
                   for result in job['results'].values())


@pytest.mark.parametrize('repetitions', [0, 6, True, False, 1.5, 2.0, '2', None])
def test_repetitions_are_strict_bounded_integers_before_job_or_snapshot(settings, repetitions):
    with TestClient(create_app(settings)) as client:
        response = client.post('/v1/evaluations', json={'repetitions': repetitions})
        assert response.status_code == 422, response.text
        assert client.get('/v1/evaluations').json() == []
        with client.app.state.studio.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM catalog_snapshots').fetchone()[0] == 0


def test_default_single_repeat_keeps_legacy_identity(settings):
    assert EvaluationRequest().repetitions == 1
    with TestClient(create_app(settings)) as client:
        response = client.post('/v1/evaluations', json={'methods': ['lexical'], 'limit': 1})
        job = wait_job(client, response.json()['id'])
        assert list(job['results']) == ['lexical']
        assert job['variants'][0]['id'] == 'lexical'
        assert job['results']['lexical']['group_id'] == 'lexical'
        assert job['results']['lexical']['repeat_index'] == 1


@pytest.mark.parametrize('expected_status', [422, 202])
def test_total_planned_work_limit_precedes_snapshots_jobs_and_provider_requests(settings, expected_status):
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        cases = [{
            'case_id': f'cap-{index}', 'source': 'customer', 'dataset_version': 'synthetic',
            'reviewed': True, 'split': 'test', 'question': f'Synthetic question {index}',
            'expected_decision': 'route', 'expected_intent_id': 'card.limit.change',
        } for index in range(2000)]
        studio.store.save_cases('demo', cases)
        requests = []
        studio.embeddings.transport = httpx.MockTransport(lambda request: requests.append(request) or embedding_response(request))
        response = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'source': 'customer', 'limit': 2000, 'repetitions': 5,
            'embedding_ids': ['default', 'bge-m3', 'qwen3-4b', 'multilingual-e5-large'] if expected_status == 422 else ['default', 'bge-m3'],
            'catalog_sizes': [48, 100, 800] if expected_status == 422 else [48, 100, 200, 400, 800],
            'semantic_rejection': 'off',
            'execution_limits': {'max_provider_requests': 0},
        })
        assert response.status_code == expected_status, response.text
        if expected_status == 202:
            job = wait_job(client, response.json()['id'])
            assert job['status'] == 'stopped' and job['stop_reason'] == 'request_limit'
            assert job['total'] == 100000 and requests == []
            return
        assert '100000' in response.json()['detail']
        assert client.get('/v1/evaluations').json() == [] and requests == []
        with studio.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM catalog_snapshots').fetchone()[0] == 0


def test_matrix_limit_remains_32_independent_of_repetitions(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post('/v1/evaluations', json={
            'methods': ['e5', 'hybrid_llm'], 'semantic_rejection': 'off', 'limit': 1, 'repetitions': 2,
            'embedding_ids': ['default', 'bge-m3', 'qwen3-4b', 'multilingual-e5-large'],
            'llm_ids': ['gpt-oss-20b', 'gpt-oss-120b'], 'catalog_sizes': [48, 100, 800],
            'execution_limits': {'max_provider_requests': 0},
        })
        assert response.status_code == 422 and '32' in response.json()['detail']
        assert client.get('/v1/evaluations').json() == []
        with client.app.state.studio.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM catalog_snapshots').fetchone()[0] == 0


def test_completed_repeats_summarize_run_metrics_and_lexical_disagreement(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post('/v1/evaluations', json={
            'methods': ['lexical'], 'limit': 3, 'repetitions': 2,
        })
        job = wait_job(client, response.json()['id'])
        assert len(job.get('group_summaries', [])) == 1
        summary = job['group_summaries'][0]
        assert summary['group_id'] == 'lexical'
        assert [summary[key] for key in ('planned_count', 'complete_count', 'partial_count', 'missing_count')] == [2, 2, 0, 0]
        accuracy = summary['metrics']['routing_accuracy']
        run_accuracy = job['results']['lexical__repeat_1']['metrics']['routing_accuracy']
        assert accuracy == {'count': 2, 'mean': run_accuracy, 'sample_sd': 0, 'min': run_accuracy, 'max': run_accuracy}
        assert summary['metrics']['latency_p95_ms']['count'] == 2
        assert summary['latency_label'] == 'Mean of per-run p95 latency (ms)'
        assert summary['disagreement']['compared_repeat_count'] == 2
        assert summary['disagreement']['eligible_case_count'] == 3
        assert summary['disagreement']['disagreement_rate'] == 0
        assert summary['disagreement']['excluded_technical_error_case_count'] == 0
        assert 'routing_accuracy_ci95' not in summary['metrics']
        for result in job['results'].values():
            assert result['metrics']['total'] == 3
            assert result['metrics']['routing_accuracy_ci95'] is not None


def test_queued_cancellation_keeps_all_planned_repeats_missing(settings):
    entered, release = threading.Event(), threading.Event()
    def respond(request):
        entered.set()
        assert release.wait(60)
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = httpx.MockTransport(respond)
        try:
            first = client.post('/v1/evaluations', json={
                'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 1,
                'execution_limits': {'max_provider_requests': 1},
            }).json()['id']
            assert entered.wait(30)
            queued = client.post('/v1/evaluations', json={
                'methods': ['lexical'], 'limit': 2, 'repetitions': 3,
            }).json()['id']
            snapshot = client.get('/v1/evaluations/' + queued).json()
            assert snapshot['status'] == 'queued'
            assert len(snapshot.get('group_summaries', [])) == 1
            summary = snapshot['group_summaries'][0]
            assert [summary[key] for key in ('planned_count', 'complete_count', 'partial_count', 'missing_count')] == [3, 0, 0, 3]
            cancelled = client.post('/v1/evaluations/' + queued + '/cancel').json()
            assert cancelled['status'] == 'cancelled'
            assert cancelled['group_summaries'] == snapshot['group_summaries']
        finally:
            release.set()
        wait_job(client, first)
        assert client.get('/v1/evaluations/' + queued).json()['results'] == {}


@pytest.mark.parametrize('stop', ['budget', 'cancel', 'failure'])
def test_partial_repeat_summary_survives_each_terminal_path(settings, stop):
    requests = []
    entered, release = threading.Event(), threading.Event()
    def respond(request):
        requests.append(request)
        if stop == 'cancel' and len(requests) == 3:
            entered.set()
            assert release.wait(60)
        if stop == 'failure' and len(requests) == 4:
            raise RuntimeError('Synthetic unexpected transport failure')
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = httpx.MockTransport(embedding_response)
        studio.retriever('demo').prepare_index()
        studio.embeddings.transport = httpx.MockTransport(respond)
        try:
            response = client.post('/v1/evaluations', json={
                'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 2, 'repetitions': 3,
                'execution_limits': {'max_provider_requests': 3} if stop == 'budget' else {},
            })
            assert response.status_code == 202, response.text
            job_id = response.json()['id']
            if stop == 'cancel':
                assert entered.wait(30)
                live = client.get('/v1/evaluations/' + job_id).json()
                assert len(live.get('group_summaries', [])) == 1
                assert live['group_summaries'][0]['complete_count'] == 1
                assert live['group_summaries'][0]['partial_count'] == 1
                assert client.post('/v1/evaluations/' + job_id + '/cancel').json()['status'] == 'running'
        finally:
            release.set()
        job = wait_job(client, job_id)
        assert job['status'] == {'budget': 'stopped', 'cancel': 'cancelled', 'failure': 'failed'}[stop]
        assert len(job.get('group_summaries', [])) == 1
        assert job['progress'] == 3 and job['total'] == 6
        first, second = job['results'].values()
        assert first['complete'] is True and first['completed_count'] == 2
        assert second['complete'] is False and second['completed_count'] == 1
        assert all(value is None for value in second['scaling'].values())
        summary = job['group_summaries'][0]
        assert [summary[key] for key in ('planned_count', 'complete_count', 'partial_count', 'missing_count')] == [3, 1, 1, 1]
        assert summary['metrics']['routing_accuracy']['count'] == 1
        assert summary['metrics']['routing_accuracy']['sample_sd'] is None
        assert summary['disagreement']['disagreement_rate'] is None
        assert job['accounting']['provider_requests'] == len(requests) == (4 if stop == 'failure' else 3)
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get('/v1/evaluations/' + job_id).json() == job


@pytest.mark.parametrize('second_baseline_error', [False, True])
def test_scaling_baselines_belong_to_each_repeat(settings, monkeypatch, second_baseline_error):
    clock = [0.]
    queries = []
    monkeypatch.setattr('time.perf_counter', lambda: clock[0])
    def respond(request):
        body = json.loads(request.content)
        if len(body['input']) == 1:
            queries.append(body['input'][0])
            clock[0] += [0.01, 0.02, 0.1, 0.2][len(queries)-1]
            if second_baseline_error and len(queries) == 3:
                return httpx.Response(503, json={'error': {'message': 'Synthetic unavailable embedding'}})
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = httpx.MockTransport(respond)
        response = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'semantic_rejection': 'off', 'catalog_sizes': [48, 100],
            'limit': 1, 'repetitions': 2,
        })
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'completed'
        results = list(job['results'].values())
        assert [result['repeat_index'] for result in results] == [1, 1, 2, 2]
        assert [result['catalog']['intent_count'] for result in results] == [48, 100, 48, 100]
        assert results[0]['scaling']['p95_ratio'] == 1
        assert results[1]['scaling']['p95_ratio'] == pytest.approx(2)
        assert results[2]['scaling']['p95_ratio'] == (None if second_baseline_error else 1)
        assert results[3]['scaling']['p95_ratio'] == (None if second_baseline_error else pytest.approx(2))
        assert all(result['scaling']['baseline_intent_count'] == 48 for result in results)
        if second_baseline_error:
            summary = job['group_summaries'][0]
            assert summary['complete_count'] == 2
            assert summary['metrics']['technical_error_rate']['mean'] == .5
            assert summary['disagreement']['excluded_technical_error_case_count'] == 1


def test_queued_repeats_freeze_cases_context_catalog_and_actual_model_requests(settings):
    entered, release = threading.Event(), threading.Event()
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            entered.set()
            assert release.wait(60)
        return embedding_response(request) if request.url.path.endswith('/embeddings') else selection_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        original_catalog = studio.store.catalog('demo')
        cases = [{
            'case_id': f'frozen-{index}', 'source': 'customer', 'dataset_version': 'synthetic',
            'reviewed': True, 'split': 'test', 'question': f'Please increase my credit card limit today {index}',
            'expected_decision': 'route', 'expected_intent_id': 'card.limit.change',
            'context': {'active_intent': 'card.limit.change', 'slots': {'new_limit': '2500'},
                        'messages': [{'role': 'user', 'content': f'Original context {index}'}]},
        } for index in range(2)]
        studio.store.save_cases('demo', cases)
        original_cases = studio.store.cases('demo', 'customer', split='test')
        original_embedding, original_llm, original_k = settings.embedding_model, settings.llm_model, settings.candidate_k
        studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
        try:
            blocker = client.post('/v1/evaluations', json={
                'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 1,
                'execution_limits': {'max_provider_requests': 1},
            }).json()['id']
            assert entered.wait(30)
            queued = client.post('/v1/evaluations', json={
                'methods': ['hybrid_llm'], 'source': 'customer', 'limit': 2, 'repetitions': 2,
            }).json()['id']
            assert client.get('/v1/evaluations/' + queued).json()['status'] == 'queued'
            for case in cases:
                changed = copy.deepcopy(case)
                changed.update(question='Edited after queue', expected_decision='out_of_scope', expected_intent_id=None)
                changed['context']['slots']['new_limit'] = '9999'
                studio.store.save_cases('demo', [changed])
            changed_catalog = copy.deepcopy(original_catalog['intents'])
            changed_catalog[0]['description'] = 'Catalog description edited after queue.'
            studio.store.save_catalog('demo', changed_catalog)
            settings.embedding_model = 'changed-embedding'
            settings.embedding_provider_only.append('changed-provider')
            settings.llm_model = 'changed-selector'
            settings.candidate_k = 1
        finally:
            release.set()
        wait_job(client, blocker)
        job = wait_job(client, queued)
        assert job['status'] == 'completed'
        assert job['dataset_fingerprint'] == fingerprint(original_cases)
        assert job['catalog_version'] == original_catalog['version']
        for result in job['results'].values():
            assert result['model'] == original_llm and result['candidate_k'] == original_k
            assert [record['question'] for record in result['records']] == [case['question'] for case in original_cases]
            assert [record['expected_intent_id'] for record in result['records']] == ['card.limit.change'] * 2
        embedding_queries = [request for request in requests if 'input' in request and len(request['input']) == 1]
        assert len(embedding_queries) == 4
        assert all(request['model'] == original_embedding for request in embedding_queries)
        assert all('changed-provider' not in request.get('provider', {}).get('only', []) for request in embedding_queries)
        llm_requests = [request for request in requests if 'messages' in request]
        assert len(llm_requests) == 4 and all(request['model'] == original_llm for request in llm_requests)
        payloads = [json.loads(request['messages'][1]['content']) for request in llm_requests]
        assert payloads[:2] == payloads[2:]
        assert all(len(payload['candidates']) == original_k for payload in payloads)


def test_repeats_freeze_reranker_credentials_and_model_during_inflight_edits(settings):
    settings.reranker_mode = 'http'
    settings.reranker_base_url = 'https://reranker.test/v1'
    settings.reranker_model = 'original-reranker'
    settings.reranker_api_key = 'original-synthetic-key'
    rerank_requests = []
    def respond(request):
        if request.url.path.endswith('/embeddings'):
            return embedding_response(request)
        if request.url.path.endswith('/rerank'):
            rerank_requests.append(request)
            body = json.loads(request.content)
            response = httpx.Response(200, json={'results': [
                {'index': index, 'relevance_score': 1 - index / 100}
                for index in range(len(body['documents']))
            ]})
            settings.reranker_model = 'edited-reranker'
            settings.reranker_api_key = 'edited-synthetic-key'
            return response
        return selection_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = studio.selector.transport = studio.reranker.transport = httpx.MockTransport(respond)
        studio.get_reranker(settings).prepare()
        response = client.post('/v1/evaluations', json={
            'methods': ['hybrid_llm'], 'limit': 1, 'repetitions': 2,
            'retrieval_profiles': [{'reranker_id': 'default'}],
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'completed'
        assert len(rerank_requests) == 2
        assert all(json.loads(request.content)['model'] == 'original-reranker' for request in rerank_requests)
        assert all(request.headers['Authorization'] == 'Bearer original-synthetic-key' for request in rerank_requests)


def test_repeats_reuse_indexes_and_frozen_scope_calibration_at_http_boundary(settings):
    settings.embedding_batch_size = 256
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        fit_cases = studio.calibrator.cases('demo', 'seed')
        fit_questions = [case['question'] for case in fit_cases]
        requests = []
        changed = False
        def respond(request):
            nonlocal changed
            body = json.loads(request.content)
            requests.append(body)
            if len(body['input']) == 1 and body['input'][0] in fit_questions and not changed:
                changed = True
                edited = copy.deepcopy(fit_cases[-1])
                edited['question'] = 'Calibration question edited after planning'
                studio.store.save_cases('demo', [edited])
            return embedding_response(request)
        studio.embeddings.transport = httpx.MockTransport(respond)
        response = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'catalog_sizes': [48, 100], 'limit': 2, 'repetitions': 2,
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'completed'
        results = list(job['results'].values())
        assert [result['index_preparation']['source'] for result in results] == ['built', 'built', 'memory', 'memory']
        assert [result['index_cache_hit'] for result in results] == [False, False, True, True]
        assert sum(len(body['input']) for body in requests if len(body['input']) > 1) == sum(
            result['index_preparation']['document_count'] for result in results[:2])
        queries = Counter(body['input'][0] for body in requests if len(body['input']) == 1)
        assert all(queries[question] == 2 for question in fit_questions)
        assert sum(queries.values()) == len(fit_questions) * 2 + 2 * 2 * 2
        fits = job['calibration_fits']
        assert len(fits) == 2
        assert all([record['question'] for record in fit['records']] == fit_questions for fit in fits)
        assert set(job['calibrations']) == {result['group_id'] for result in results}
        assert results[0]['calibration'] == results[2]['calibration']
        assert results[1]['calibration'] == results[3]['calibration']
        assert all(result['calibration'] == job['calibrations'][result['group_id']] for result in results)


def test_repeated_index_failures_are_not_retried_or_excluded_from_metrics(settings):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(503, json={'error': {'message': 'Synthetic index unavailable'}})
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = httpx.MockTransport(respond)
        response = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 2, 'repetitions': 3,
        })
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'completed'
        assert len(requests) == job['accounting']['provider_requests'] == 1
        assert all(result['complete'] and result['metrics']['errors'] == 2 for result in job['results'].values())
        summary = job['group_summaries'][0]
        assert summary['complete_count'] == 3
        assert summary['metrics']['routing_accuracy']['count'] == 3
        assert summary['metrics']['technical_error_rate']['mean'] == 1
        assert summary['disagreement']['excluded_technical_error_case_count'] == 2
        assert summary['disagreement']['eligible_case_count'] == 0
        assert summary['disagreement']['disagreement_rate'] is None


@pytest.mark.parametrize('limit', ['duration', 'cost'])
def test_duration_and_cost_limits_are_shared_across_repetitions(settings, monkeypatch, limit):
    worker_clock = [100.]
    actual_monotonic = time.monotonic
    monkeypatch.setattr(time, 'monotonic', lambda: worker_clock[0] if threading.current_thread().name.startswith('evaluation') else actual_monotonic())
    requests = []
    def respond(request):
        requests.append(request)
        worker_clock[0] += .4
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = httpx.MockTransport(embedding_response)
        studio.retriever('demo').prepare_index()
        studio.embeddings.transport = httpx.MockTransport(respond)
        response = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 2, 'repetitions': 3,
            'execution_limits': {'max_duration_seconds': 1} if limit == 'duration' else {'max_reported_cost_usd': .03},
        })
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'stopped'
        assert job['stop_reason'] == {'duration': 'duration_limit', 'cost': 'reported_cost_limit'}[limit]
        assert len(requests) == job['accounting']['provider_requests'] == 3
        assert job['accounting']['reported_cost_usd'] == .03
        summary = job['group_summaries'][0]
        assert [summary[key] for key in ('complete_count', 'partial_count', 'missing_count')] == [1, 1, 1]


def test_local_reranker_is_reused_across_compatible_matrix_variants(settings, monkeypatch):
    settings.reranker_mode = 'local'
    settings.reranker_local_files_only = True
    loads: list[str] = []
    class CrossEncoder:
        def __init__(self, model: str, *, local_files_only: bool, max_length: int):
            loads.append(model)

        def predict(self, pairs: list[list[str]], *, batch_size: int, show_progress_bar: bool) -> list[float]:
            return [1 - index / 100 for index in range(len(pairs))]

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(CrossEncoder=CrossEncoder))
    def respond(request):
        return embedding_response(request) if request.url.path.endswith('/embeddings') else selection_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
        response = client.post('/v1/evaluations', json={
            'methods': ['hybrid_llm'], 'limit': 1, 'repetitions': 2,
            'llm_ids': ['gpt-oss-20b', 'gpt-oss-120b'],
            'retrieval_profiles': [{'id': 'five', 'reranker_id': 'default', 'candidate_k': 5},
                                   {'id': 'ten', 'reranker_id': 'default', 'candidate_k': 10}],
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'completed'
        assert job['progress'] == job['total'] == 8
        assert all(result['metrics']['errors'] == 0 for result in job['results'].values())
        assert loads == [settings.reranker_model]


def test_reranker_runtime_cache_preserves_local_inference_settings(settings, monkeypatch):
    settings.reranker_mode = 'local'
    settings.reranker_local_files_only = True
    local_loads: list[bool] = []
    class CrossEncoder:
        def __init__(self, model: str, *, local_files_only: bool, max_length: int):
            local_loads.append(local_files_only)

        def predict(self, pairs: list[list[str]], *, batch_size: int, show_progress_bar: bool) -> list[float]:
            return [float(batch_size) for _ in pairs]

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(CrossEncoder=CrossEncoder))
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        assert studio.get_reranker(settings).scores('query', ['first']) == [settings.reranker_batch_size]
        changed_batch = settings.model_copy(update={'reranker_batch_size': settings.reranker_batch_size + 7})
        assert studio.get_reranker(changed_batch).scores('query', ['first']) == [changed_batch.reranker_batch_size]
        changed_loading = changed_batch.model_copy(update={'reranker_local_files_only': False})
        assert studio.get_reranker(changed_loading).scores('query', ['first']) == [changed_loading.reranker_batch_size]
        assert local_loads == [True, True, False]
