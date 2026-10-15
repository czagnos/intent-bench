import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import OPENROUTER_BASE_URL


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path, model_credentials_file=tmp_path / 'absent.env',
                    openrouter_api_key='synthetic-control-key', embedding_mode='http',
                    embedding_base_url=OPENROUTER_BASE_URL, embedding_model='test-embedding',
                    embedding_profile='plain', embedding_batch_size=32,
                    llm_base_url=OPENROUTER_BASE_URL, llm_model='test-selector')


def wait_job(client, job_id):
    for _ in range(1000):
        job = client.get('/v1/evaluations/' + job_id).json()
        if job['status'] not in ('queued', 'running'):
            return job
        time.sleep(.01)
    pytest.fail('Evaluation did not reach a terminal state')


def embedding_response(request):
    body = json.loads(request.content)
    return httpx.Response(200, json={
        'data': [{'index': i, 'embedding': [1., 0.]} for i in range(len(body['input']))],
        'usage': {'prompt_tokens': 5, 'total_tokens': 5, 'cost': .01},
    })


def test_request_budget_stops_during_index_preparation(settings):
    requests = []
    def respond(request):
        requests.append(request)
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = httpx.MockTransport(respond)
        response = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 2,
            'execution_limits': {'max_provider_requests': 1},
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'stopped'
        assert job['stop_reason'] == 'request_limit'
        assert len(requests) == job['accounting']['provider_requests'] == 1
        assert job['accounting']['by_service_stage'][0]['stage'] == 'index'
        assert job['progress'] == 0 and job['total'] == 2


@pytest.mark.parametrize('service', ['embedding', 'llm', 'reranker'])
def test_reported_cost_rejects_selected_unsupported_remote_before_snapshots(settings, service):
    setattr(settings, service + '_base_url', 'https://private-provider.example/v1')
    if service == 'reranker':
        settings.reranker_mode = 'http'
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        sent = []
        transport = httpx.MockTransport(lambda request: sent.append(request) or embedding_response(request))
        studio.embeddings.transport = studio.selector.transport = studio.reranker.transport = transport
        body = {'methods': ['hybrid_llm'], 'limit': 1, 'execution_limits': {'max_reported_cost_usd': .1}}
        if service == 'reranker':
            body['retrieval_profiles'] = [{'reranker_id': 'default'}]
        response = client.post('/v1/evaluations', json=body)
        assert response.status_code == 422, response.text
        assert 'OpenRouter' in response.json()['detail']
        assert studio.store.jobs('demo') == [] and sent == []
        with studio.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM catalog_snapshots').fetchone()[0] == 0


def test_unused_remote_configuration_does_not_block_zero_request_lexical_run(settings):
    settings.embedding_base_url = settings.llm_base_url = 'https://private-provider.example/v1'
    with TestClient(create_app(settings)) as client:
        response = client.post('/v1/evaluations', json={
            'methods': ['lexical'], 'limit': 1,
            'execution_limits': {'max_provider_requests': 0, 'max_reported_cost_usd': .1},
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'completed'
        assert job['accounting']['provider_requests'] == 0
        assert job['accounting']['reported_cost_usd'] == 0


def test_real_queue_cancellation_prevents_start_and_running_waits_for_ack(settings):
    entered, release = threading.Event(), threading.Event()
    requests = []
    def respond(request):
        requests.append(request)
        entered.set()
        assert release.wait(60), 'Test did not release the external request'
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = httpx.MockTransport(respond)
        try:
            first = client.post('/v1/evaluations', json={'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 2}).json()['id']
            assert entered.wait(30)
            second = client.post('/v1/evaluations', json={'methods': ['lexical'], 'limit': 1}).json()['id']
            assert client.get('/v1/evaluations/' + second).json()['status'] == 'queued'
            cancelled = client.post('/v1/evaluations/' + second + '/cancel')
            assert cancelled.status_code == 200
            assert cancelled.json()['status'] == 'cancelled'
            assert cancelled.json()['cancel_requested'] is True
            assert cancelled.json()['stop_reason'] == 'user_cancelled'
            pending = client.post('/v1/evaluations/' + first + '/cancel').json()
            assert pending['status'] == 'running' and pending['cancel_requested'] is True
            assert client.post('/v1/evaluations/' + first + '/cancel').json() == pending
        finally:
            release.set()
        finished = wait_job(client, first)
        assert finished['status'] == 'cancelled' and finished['stop_reason'] == 'user_cancelled'
        assert finished['accounting']['provider_requests'] == len(requests) == 1
        # A third run drains the real queue, proving the cancelled worker cannot later claim it.
        third = client.post('/v1/evaluations', json={'methods': ['lexical'], 'limit': 1}).json()['id']
        assert wait_job(client, third)['status'] == 'completed'
        assert client.get('/v1/evaluations/' + second).json() == cancelled.json()
        assert client.post('/v1/evaluations/' + first + '/cancel').json() == finished
        completed = client.get('/v1/evaluations/' + third).json()
        assert client.post('/v1/evaluations/' + third + '/cancel').json() == completed
        assert client.post('/v1/evaluations/' + first + '/cancel', params={'workspace': 'other'}).status_code == 404
        assert client.post('/v1/evaluations/missing/cancel').status_code == 404
        route = studio.store.create_job('demo', 'route', {})
        assert client.post('/v1/evaluations/' + route['id'] + '/cancel').status_code == 404


def selection_response(request):
    body = json.loads(request.content)
    intent_id = json.loads(body['messages'][1]['content'])['candidates'][0]['intent_id']
    return httpx.Response(200, json={
        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'decision': 'route', 'intent_id': intent_id})}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12, 'cost': .01},
    })


def test_active_incomplete_result_exists_before_preparation_finishes(settings):
    entered, release = threading.Event(), threading.Event()
    def respond(request):
        entered.set()
        assert release.wait(60)
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = httpx.MockTransport(respond)
        try:
            job_id = client.post('/v1/evaluations', json={
                'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 2,
                'execution_limits': {'max_provider_requests': 1},
            }).json()['id']
            assert entered.wait(30)
            running = client.get('/v1/evaluations/' + job_id).json()
            assert len(running['results']) == 1
            result = next(iter(running['results'].values()))
            assert result['complete'] is False and result['completed_count'] == 0
            assert result['selected_count'] == 2 and result['records'] == []
            assert all(value is None for value in result['scaling'].values())
            assert running['accounting']['provider_requests'] == 1
            assert running['accounting']['reported_cost_usd'] is None
        finally:
            release.set()
        stopped = wait_job(client, job_id)
        assert stopped['status'] == 'stopped'
        assert next(iter(stopped['results'].values()))['records'] == []


@pytest.mark.parametrize('outcome', ['failure', 'cancel'])
def test_finished_case_is_checkpointed_and_retained_when_next_case_interrupts(settings, outcome):
    entered, release = threading.Event(), threading.Event()
    chats = []
    def respond(request):
        if request.url.path.endswith('/embeddings'):
            return embedding_response(request)
        chats.append(request)
        if len(chats) == 2:
            entered.set()
            assert release.wait(60)
            if outcome == 'failure':
                raise RuntimeError('SECRET raw provider payload must never escape')
        return selection_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
        try:
            job_id = client.post('/v1/evaluations', json={'methods': ['hybrid_llm'], 'limit': 3}).json()['id']
            assert entered.wait(30)
            running = client.get('/v1/evaluations/' + job_id).json()
            assert running['progress'] == 1
            result = next(iter(running['results'].values()))
            assert result['completed_count'] == len(result['records']) == 1
            assert result['complete'] is False and result['metrics']['total'] == 1
            assert all(value is None for value in result['scaling'].values())
            if outcome == 'cancel':
                assert client.post('/v1/evaluations/' + job_id + '/cancel').json()['status'] == 'running'
        finally:
            release.set()
        terminal = wait_job(client, job_id)
        assert terminal['status'] == ('failed' if outcome == 'failure' else 'cancelled')
        result = next(iter(terminal['results'].values()))
        expected_count = 1 if outcome == 'failure' else 2
        assert result['completed_count'] == len(result['records']) == terminal['progress'] == expected_count
        assert result['selected_count'] == 3 and result['complete'] is False
        assert result['records'][0] == running['results'][result['id']]['records'][0]
        assert 'SECRET' not in json.dumps(terminal)
        assert all(value is None for value in result['scaling'].values())


@pytest.mark.parametrize('status,cancel_requested,expected_status,reason', [
    ('queued', False, 'failed', 'interrupted'),
    ('running', False, 'failed', 'interrupted'),
    ('running', True, 'cancelled', 'user_cancelled'),
])
def test_restart_preserves_checkpointed_partial_results_and_accounting(settings, status, cancel_requested, expected_status, reason):
    from app.execution import ExecutionAccounting
    from app.store import Store
    store = Store(settings.data_dir)
    saved = store.create_job('demo', 'evaluation', {
        'status': status, 'cancel_requested': cancel_requested,
        'progress': 1, 'total': 3,
        'results': {'lexical': {'complete': False, 'completed_count': 1, 'selected_count': 3,
                                'records': [{'case_id': 'finished-synthetic-case', 'decision': 'handoff'}]}},
        'accounting': ExecutionAccounting(provider_requests=2, unknown_cost_requests=1, reported_cost_usd=None).model_dump(),
    })
    with TestClient(create_app(settings)) as client:
        recovered = client.get('/v1/evaluations/' + saved['id']).json()
        assert recovered['status'] == expected_status
        assert recovered.get('stop_reason') == reason
        assert recovered['results'] == saved['results'] and recovered['accounting'] == saved['accounting']
        assert recovered['progress'] == 1 and recovered['total'] == 3
        assert client.post('/v1/evaluations/' + saved['id'] + '/cancel').json() == recovered
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get('/v1/evaluations/' + saved['id']).json() == recovered


@pytest.mark.parametrize('cost', [None, -1, True, '0.2', .2])
def test_billed_malformed_output_retains_case_and_stops_without_another_http_request(settings, cost):
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path.endswith('/embeddings'):
            return embedding_response(request)
        usage = {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}
        if cost is not None:
            usage['cost'] = cost
        return httpx.Response(200, json={
            'choices': [{'finish_reason': 'stop', 'message': {'content': 'invalid selection PRIVATE'}}],
            'usage': usage,
        })
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
        studio.retriever('demo').prepare_index()
        requests.clear()
        response = client.post('/v1/evaluations', json={
            'methods': ['hybrid_llm'], 'limit': 3,
            'execution_limits': {'max_reported_cost_usd': .1},
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'stopped'
        assert job['stop_reason'] == ('reported_cost_limit' if cost == .2 else 'reported_cost_unknown')
        assert len(requests) == job['accounting']['provider_requests'] == 2
        assert job['accounting']['known_total_tokens'] == 17
        result = next(iter(job['results'].values()))
        assert job['progress'] == result['completed_count'] == len(result['records']) == 1
        assert result['complete'] is False and result['records'][0]['decision'] == 'error'
        assert result['metrics']['errors'] == 1
        assert all(value is None for value in result['scaling'].values())
        assert 'PRIVATE' not in json.dumps(job)
        if cost == .2:
            assert job['accounting']['reported_cost_usd'] == .21
        else:
            assert job['accounting']['reported_cost_usd'] is None
            assert job['accounting']['known_cost_usd'] == .01
            assert job['accounting']['unknown_cost_requests'] == 1


def test_unknown_cost_timeout_stops_before_second_request(settings):
    requests = []
    def respond(request):
        requests.append(request)
        raise httpx.ReadTimeout('PRIVATE transport detail', request=request)
    with TestClient(create_app(settings)) as client:
        client.app.state.studio.embeddings.transport = httpx.MockTransport(respond)
        job_id = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 3,
            'execution_limits': {'max_reported_cost_usd': 1},
        }).json()['id']
        job = wait_job(client, job_id)
        assert job['status'] == 'stopped' and job['stop_reason'] == 'reported_cost_unknown'
        assert len(requests) == job['accounting']['provider_requests'] == 1
        assert job['accounting']['reported_cost_usd'] is None
        assert job['accounting']['unknown_cost_requests'] == 1
        assert job['progress'] == 0 and next(iter(job['results'].values()))['records'] == []
        assert 'PRIVATE' not in json.dumps(job)


def test_duration_starts_in_worker_excludes_queue_wait_and_checks_preparation(settings, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    worker_clock = [100.]
    actual_monotonic = time.monotonic
    monkeypatch.setattr(time, 'monotonic', lambda: worker_clock[0] if threading.current_thread().name.startswith('evaluation') else actual_monotonic())
    def respond(request):
        entered.set()
        assert release.wait(60)
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = httpx.MockTransport(respond)
        try:
            first = client.post('/v1/evaluations', json={
                'methods': ['e5'], 'semantic_rejection': 'off', 'limit': 2,
                'execution_limits': {'max_duration_seconds': 1},
            }).json()['id']
            assert entered.wait(30)
            second = client.post('/v1/evaluations', json={
                'methods': ['lexical'], 'limit': 1, 'execution_limits': {'max_duration_seconds': 1},
            }).json()['id']
            worker_clock[0] += 100
        finally:
            release.set()
        stopped = wait_job(client, first)
        assert stopped['status'] == 'stopped' and stopped['stop_reason'] == 'duration_limit'
        assert stopped['accounting']['provider_requests'] == 1 and stopped['progress'] == 0
        assert wait_job(client, second)['status'] == 'completed'


def test_calibration_requests_share_the_preparation_budget(settings):
    settings.embedding_batch_size = 256
    requests = []
    def respond(request):
        requests.append(request)
        return embedding_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = httpx.MockTransport(respond)
        response = client.post('/v1/evaluations', json={
            'methods': ['e5'], 'catalog_sizes': [48], 'limit': 2,
            'execution_limits': {'max_provider_requests': 2},
        })
        assert response.status_code == 202, response.text
        job = wait_job(client, response.json()['id'])
        assert job['status'] == 'stopped' and job['stop_reason'] == 'request_limit'
        assert len(requests) == job['accounting']['provider_requests'] == 2
        assert {row['stage']: row['provider_requests'] for row in job['accounting']['by_service_stage']} == {'index': 1, 'calibration': 1}
        assert job['progress'] == 0 and next(iter(job['results'].values()))['records'] == []
        assert studio.store.latest_calibration('demo', 'unused') is None


def test_live_route_remains_unbound_while_evaluation_cancellation_is_pending(settings):
    entered, release = threading.Event(), threading.Event()
    evaluation_calls, live_calls = [], []
    def respond(request):
        if threading.current_thread().name.startswith('evaluation'):
            evaluation_calls.append(request)
            if request.url.path.endswith('/chat/completions'):
                entered.set()
                assert release.wait(60)
        else:
            live_calls.append(request)
        return embedding_response(request) if request.url.path.endswith('/embeddings') else selection_response(request)
    with TestClient(create_app(settings)) as client:
        studio = client.app.state.studio
        studio.embeddings.transport = studio.selector.transport = httpx.MockTransport(respond)
        studio.retriever('demo').prepare_index()
        live_calls.clear()
        try:
            job_id = client.post('/v1/evaluations', json={
                'methods': ['hybrid_llm'], 'limit': 1,
                'execution_limits': {'max_provider_requests': 2},
            }).json()['id']
            assert entered.wait(30)
            assert client.post('/v1/evaluations/' + job_id + '/cancel').json()['status'] == 'running'
            session_id = client.post('/v1/sessions').json()['session_id']
            route = client.post('/v1/route', json={
                'session_id': session_id, 'turn_revision': 1,
                'user_text': 'Increase my credit card limit', 'method': 'hybrid_llm',
            })
            assert route.status_code == 202, route.text
            for _ in range(1000):
                routed = client.get('/v1/requests/' + route.json()['request_id']).json()
                if routed['status'] not in ('queued', 'running'):
                    break
                time.sleep(.01)
            assert routed['status'] == 'completed'
            assert len(live_calls) == 2
        finally:
            release.set()
        cancelled = wait_job(client, job_id)
        assert cancelled['status'] == 'cancelled'
        assert len(evaluation_calls) == cancelled['accounting']['provider_requests'] == 2
        result = next(iter(cancelled['results'].values()))
        assert result['complete'] is True and result['completed_count'] == 1


@pytest.mark.parametrize('updates', [
    {'max_provider_requests': True}, {'max_provider_requests': -1}, {'max_provider_requests': 1.5},
    {'max_duration_seconds': True}, {'max_duration_seconds': 0},
    {'max_reported_cost_usd': True}, {'max_reported_cost_usd': 0}, {'extra': 1},
])
def test_execution_limits_validate_before_any_job_or_snapshot(settings, updates):
    with TestClient(create_app(settings)) as client:
        assert client.post('/v1/evaluations', json={'execution_limits': updates}).status_code == 422
        assert client.get('/v1/evaluations').json() == []
        with client.app.state.studio.store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM catalog_snapshots').fetchone()[0] == 0


@pytest.mark.parametrize('field,value', [
    ('max_duration_seconds', '1e999'), ('max_duration_seconds', 'NaN'),
    ('max_reported_cost_usd', '-1e999'), ('max_reported_cost_usd', 'Infinity'),
])
def test_nonfinite_limit_input_is_a_safe_422_response(settings, field, value):
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.post('/v1/evaluations', content='{"execution_limits":{"' + field + '":' + value + '}}',
                               headers={'Content-Type': 'application/json'})
        assert response.status_code == 422, response.text
        assert field in response.text
        assert client.get('/v1/evaluations').json() == []


def test_store_finalization_rereads_accepted_cancellation_and_rejects_stale_state(settings):
    from app.store import Store
    store = Store(settings.data_dir)
    job = store.create_job('demo', 'evaluation', {'cancel_requested': False, 'progress': 0, 'total': 1})
    assert store.claim_evaluation('demo', job['id'])['status'] == 'running'
    assert store.cancel_evaluation('demo', job['id'])['cancel_requested'] is True
    checkpoint = store.checkpoint_evaluation('demo', job['id'], {
        'progress': 1, 'status': 'completed', 'cancel_requested': False, 'stop_reason': None,
    })
    assert checkpoint['status'] == 'running' and checkpoint['cancel_requested'] is True
    terminal = store.finalize_evaluation('demo', job['id'], 'completed')
    assert terminal['status'] == 'cancelled' and terminal['stop_reason'] == 'user_cancelled'
    assert terminal['progress'] == 1
    assert store.claim_evaluation('demo', job['id']) is None
    assert store.checkpoint_evaluation('demo', job['id'], {'progress': 0}) == terminal
    assert store.finalize_evaluation('demo', job['id'], 'failed', error='late failure') == terminal


@pytest.mark.parametrize('status,reason', [('stopped', 'request_limit'), ('cancelled', 'user_cancelled')])
def test_terminal_control_jobs_survive_restart_and_close_event_stream(settings, status, reason):
    from app.store import Store
    saved = Store(settings.data_dir).create_job('demo', 'evaluation', {
        'status': status, 'stop_reason': reason, 'cancel_requested': status == 'cancelled',
        'results': {}, 'progress': 0, 'total': 2,
    })
    with TestClient(create_app(settings)) as client:
        assert client.get('/v1/evaluations/' + saved['id']).json() == saved
        assert client.post('/v1/evaluations/' + saved['id'] + '/cancel').json() == saved
        response = client.get('/v1/requests/' + saved['id'] + '/events')
        assert response.status_code == 200
        assert 'event: result' in response.text and json.loads(response.text.split('data: ', 1)[1]) == saved
