import asyncio

from app import database
from tests.conftest import AUTH, metrics_payload


def stored(collection: str) -> list:
    """Everything in a collection of the in-memory database."""
    async def read():
        return [doc async for doc in database.get_db()[collection].find({})]
    return asyncio.run(read())


# --- health and app setup ---------------------------------------------------

def test_health_unchanged(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_ready_reports_database(client):
    assert client.get('/health/ready').json() == {'status': 'ok'}


def test_security_headers_and_request_id(client):
    response = client.get('/health')
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['x-frame-options'] == 'DENY'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-request-id']


def test_api_responses_forbid_scripts_but_docs_still_load(client):
    assert client.get('/health').headers['content-security-policy'] == "default-src 'none'; frame-ancestors 'none'"
    assert 'content-security-policy' not in client.get('/docs').headers


def test_hsts_only_in_production(make_client):
    assert 'strict-transport-security' not in make_client().get('/health').headers
    production = make_client(environment='production')
    assert production.get('/health').headers['strict-transport-security'].startswith('max-age=31536000')


def test_cors_allows_no_browser_origin_by_default(client):
    response = client.get('/health', headers={'Origin': 'https://example.org'})
    assert 'access-control-allow-origin' not in response.headers


def test_cors_allows_only_listed_origins_without_credentials(make_client):
    client = make_client(cors_origins=['https://dashboard.example.org'])
    allowed = client.get('/health', headers={'Origin': 'https://dashboard.example.org'})
    assert allowed.headers['access-control-allow-origin'] == 'https://dashboard.example.org'
    assert 'access-control-allow-credentials' not in allowed.headers
    other = client.get('/health', headers={'Origin': 'https://evil.example'})
    assert 'access-control-allow-origin' not in other.headers


def test_remaining_security_headers(client):
    headers = client.get('/health').headers
    assert headers['x-xss-protection'] == '0'
    assert headers['cross-origin-opener-policy'] == 'same-origin'
    assert headers['cross-origin-resource-policy'] == 'same-origin'
    assert 'camera=()' in headers['permissions-policy']


def test_ip_flood_guard(make_client):
    client = make_client(ip_rate_limit_per_minute=5)
    codes = [client.get('/health', headers={'X-Forwarded-For': '203.0.113.7'}).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    # A different address is not affected.
    assert client.get('/health', headers={'X-Forwarded-For': '198.51.100.2'}).status_code == 200


def test_docs_on_in_development_off_in_production(make_client):
    assert make_client().get('/docs').status_code == 200
    production = make_client(environment='production')
    assert production.get('/docs').status_code == 404
    assert production.get('/openapi.json').status_code == 404


# --- auth -------------------------------------------------------------------

def test_missing_auth_header_is_401(client):
    response = client.post('/metrics/', json=metrics_payload())
    assert response.status_code == 401
    assert response.headers['www-authenticate'] == 'Bearer'


def test_malformed_and_invalid_tokens_are_401_without_details(client):
    for header in ('Token abc', 'Bearer', 'Bearer not-a-user'):
        response = client.post('/metrics/', json=metrics_payload(), headers={'Authorization': header})
        assert response.status_code == 401
        assert 'bad token' not in response.text


def test_register_is_idempotent(client):
    first = client.post('/auth/register', json={'display_name': 'Exoskeleton User'}, headers=AUTH)
    second = client.post('/auth/register', json={'display_name': 'Exoskeleton User'}, headers=AUTH)
    assert first.json()['message'] == 'User created'
    assert second.json() == {'message': 'User already exists', 'id': first.json()['id']}
    assert len(stored('users')) == 1


def test_preferences_reject_mongodb_operator_keys(client):
    client.post('/auth/register', json={'display_name': 'Exoskeleton User'}, headers=AUTH)
    for bad in ({'$where': 'sleep(1000)'}, {'a.b': 1}, {'nested': {'$gt': ''}}):
        response = client.patch('/auth/me', json={'preferences': bad}, headers=AUTH)
        assert response.status_code == 422
    ok = client.patch('/auth/me', json={'preferences': {'units': 'metric'}}, headers=AUTH)
    assert ok.status_code == 200


def test_me_returns_profile(client):
    client.post('/auth/register', json={'display_name': 'Exoskeleton User'}, headers=AUTH)
    me = client.get('/auth/me', headers=AUTH).json()
    assert me['firebase_uid'] == 'alice'
    assert '_id' not in me and me['id']


def test_rate_limit_returns_429_with_retry_after(make_client):
    client = make_client(rate_limit_per_minute=3)
    codes = [client.get('/metrics/events', headers=AUTH).status_code for _ in range(4)]
    assert codes == [404, 404, 404, 429]  # 404: alice never registered
    response = client.get('/metrics/events', headers=AUTH)
    assert int(response.headers['retry-after']) >= 1


# --- metrics ----------------------------------------------------------------

def test_current_app_payload_is_accepted_and_identity_stored(client):
    response = client.post('/metrics/', json=metrics_payload(), headers=AUTH)
    assert response.status_code == 201
    assert set(response.json()) == {'id'}
    [doc] = stored('metrics_entries')
    assert doc['username'] == 'alice'
    assert doc['session_id'] == 4242
    assert doc['hr'] == 96 and doc['hrv_slope'] == -0.25 and doc['distance_m'] == 120


def test_metrics_without_register_creates_the_user(client):
    assert client.post('/metrics/', json=metrics_payload(), headers=AUTH).status_code == 201
    assert len(stored('users')) == 1


def test_resent_line_without_entry_id_is_a_duplicate(client):
    first = client.post('/metrics/', json=metrics_payload(), headers=AUTH)
    second = client.post('/metrics/', json=metrics_payload(), headers=AUTH)
    assert second.status_code == 200
    assert second.json() == {'id': first.json()['id'], 'duplicate': True}
    assert len(stored('metrics_entries')) == 1


def test_entry_id_identifies_duplicates(client):
    payload = metrics_payload(entryId='3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90', hrvSource='beat')
    assert client.post('/metrics/', json=payload, headers=AUTH).status_code == 201
    again = client.post('/metrics/', json={**payload, 'hr': 97}, headers=AUTH)
    assert again.json()['duplicate'] is True
    [doc] = stored('metrics_entries')
    assert doc['entry_id'] == payload['entryId']
    assert doc['hrv_source'] == 'beat'
    assert 'idem_key' in doc


def test_same_record_from_two_users_is_not_a_duplicate(client):
    client.post('/metrics/', json=metrics_payload(), headers=AUTH)
    other = client.post('/metrics/', json=metrics_payload(), headers={'Authorization': 'Bearer user-bob'})
    assert other.status_code == 201
    assert len(stored('metrics_entries')) == 2


def test_invalid_metrics_are_422_without_echoing_values(client):
    response = client.post('/metrics/', json=metrics_payload(hr=987654), headers=AUTH)
    assert response.status_code == 422
    assert '987654' not in response.text
    assert 'body_received' not in response.json()
    assert response.json()['detail'][0]['loc'] == ['body', 'hr']


def test_nan_is_rejected(client):
    body = '{"timestamp": 1760000000000, "hr": 90, "hrv": NaN, "hrvSlope": 0, "distanceM": 0, ' \
           '"durationMs": 0, "calories": 0, "steps": 0}'
    response = client.post('/metrics/', content=body, headers={**AUTH, 'Content-Type': 'application/json'})
    assert response.status_code == 422


def test_test_flag_is_stored(client):
    client.post('/metrics/', json=metrics_payload(test=True), headers=AUTH)
    assert stored('metrics_entries')[0]['test'] is True


def test_list_and_latest_hide_internal_fields(client):
    client.post('/metrics/', json=metrics_payload(timestamp=1_760_000_000_000), headers=AUTH)
    client.post('/metrics/', json=metrics_payload(timestamp=1_760_000_001_000), headers=AUTH)
    listed = client.get('/metrics/', headers=AUTH).json()
    assert [entry['timestamp'] for entry in listed] == [1_760_000_001_000, 1_760_000_000_000]
    assert all('idem_key' not in entry and '_id' not in entry for entry in listed)
    latest = client.get('/metrics/latest', headers=AUTH).json()
    assert latest['timestamp'] == 1_760_000_001_000


def test_list_clamps_paging_instead_of_rejecting(client):
    client.post('/metrics/', json=metrics_payload(), headers=AUTH)
    assert client.get('/metrics/?skip=-5&limit=100000', headers=AUTH).status_code == 200
    assert len(client.get('/metrics/?limit=0', headers=AUTH).json()) == 1


def test_participant_code_is_stored_and_filterable(client):
    client.post('/metrics/', json=metrics_payload(participantCode='EXO-4K7Q-9ZMD', entryId='a1'), headers=AUTH)
    client.post('/metrics/', json=metrics_payload(participantCode='EXO-ZZZZ-2222', entryId='a2'), headers=AUTH)
    assert {d['participant_code'] for d in stored('metrics_entries')} == {'EXO-4K7Q-9ZMD', 'EXO-ZZZZ-2222'}
    only = client.get('/metrics/?participant_code=EXO-4K7Q-9ZMD', headers=AUTH).json()
    assert [d['entry_id'] for d in only] == ['a1']


def test_participant_code_format_is_checked(client):
    response = client.post('/metrics/', json=metrics_payload(participantCode='{"$ne": 1}'), headers=AUTH)
    assert response.status_code == 422


def test_session_filter_from_live_api_is_kept(client):
    client.post('/metrics/', json=metrics_payload(sessionId=1, entryId='s1'), headers=AUTH)
    client.post('/metrics/', json=metrics_payload(sessionId=2, entryId='s2'), headers=AUTH)
    assert [d['entry_id'] for d in client.get('/metrics/?session_id=2', headers=AUTH).json()] == ['s2']
    feedback = {'timestamp': 1_760_000_000_000, 'sessionId': 9, 'text': 'ok'}
    client.post('/metrics/feedback', json=feedback, headers=AUTH)
    assert len(client.get('/metrics/feedback?session_id=9', headers=AUTH).json()) == 1
    assert client.get('/metrics/feedback?session_id=8', headers=AUTH).json() == []
    power = {'timestamp': 1_760_000_000_000, 'sessionId': 3, 'newPowerPercent': 30, 'reason': 'x',
             'hr': 80, 'hrv': 0, 'hrvSlope': 0}
    client.post('/metrics/events/power', json=power, headers=AUTH)
    assert len(client.get('/metrics/events?session_id=3', headers=AUTH).json()) == 1


def test_least_privilege_check_never_blocks_startup(client):
    # Ran during startup on the in-memory database without raising.
    assert client.get('/health').status_code == 200


def test_get_for_unknown_user_is_still_404(client):
    assert client.get('/metrics/', headers=AUTH).status_code == 404
    assert len(stored('users')) == 0


# --- batch ------------------------------------------------------------------

def test_batch_reports_each_entry(client):
    client.post('/metrics/', json=metrics_payload(entryId='already-there'), headers=AUTH)
    entries = [
        metrics_payload(entryId='new-1'),
        metrics_payload(entryId='already-there'),
        metrics_payload(entryId='bad', hr=-1),
        metrics_payload(entryId='new-1'),
        'not an object',
    ]
    response = client.post('/metrics/batch', json={'entries': entries}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert [r['status'] for r in body['results']] == ['created', 'duplicate', 'invalid', 'duplicate', 'invalid']
    assert [r['index'] for r in body['results']] == [0, 1, 2, 3, 4]
    assert body['results'][3]['id'] == body['results'][0]['id']
    assert (body['created'], body['duplicates'], body['invalid']) == (1, 2, 2)
    assert '-1' not in str(body['results'][2]['errors'])
    assert len(stored('metrics_entries')) == 2


def test_batch_size_limit_is_413(make_client):
    client = make_client(max_batch_size=2)
    entries = [metrics_payload(entryId=f'e{i}') for i in range(3)]
    assert client.post('/metrics/batch', json={'entries': entries}, headers=AUTH).status_code == 413


def test_empty_batch_is_422(client):
    assert client.post('/metrics/batch', json={'entries': []}, headers=AUTH).status_code == 422


def test_body_size_limit_is_413(make_client):
    client = make_client(max_body_bytes=200)
    response = client.post('/metrics/', json=metrics_payload(username='x' * 300), headers=AUTH)
    assert response.status_code == 413


def test_chunked_body_over_limit_is_413(make_client):
    client = make_client(max_body_bytes=200)
    chunks = iter([b'{"timestamp": 1, ', b'"x": "' + b'a' * 400 + b'"}'])  # no Content-Length
    response = client.post('/metrics/', content=chunks, headers={**AUTH, 'Content-Type': 'application/json'})
    assert response.status_code == 413


# --- events and feedback ----------------------------------------------------

def test_power_and_mode_events_from_current_app(client):
    power = {
        'timestamp': 1_760_000_000_000, 'username': 'alice', 'sessionId': 4242,
        'type': 'power_change', 'newPowerPercent': 30, 'reason': 'switch_request',
        'hr': 80, 'hrv': 30.0, 'hrvSlope': 0.0,
    }
    mode = {
        'timestamp': 1_760_000_000_500, 'username': 'alice', 'sessionId': 4242,
        'type': 'mode_change', 'newMode': 'FITNESS', 'hr': 80,
    }
    assert client.post('/metrics/events/power', json=power, headers=AUTH).status_code == 201
    assert client.post('/metrics/events/mode', json=mode, headers=AUTH).status_code == 201
    assert client.post('/metrics/events/power', json=power, headers=AUTH).json()['duplicate'] is True

    events = client.get('/metrics/events', headers=AUTH).json()
    assert [e['type'] for e in events] == ['mode_change', 'power_change']
    assert events[1]['old_power_percent'] is None
    only_power = client.get('/metrics/events?type=power_change', headers=AUTH).json()
    assert len(only_power) == 1


def test_power_event_out_of_range_is_422(client):
    event = {'timestamp': 1_760_000_000_000, 'newPowerPercent': 500, 'reason': 'x', 'hr': 80, 'hrv': 0, 'hrvSlope': 0}
    assert client.post('/metrics/events/power', json=event, headers=AUTH).status_code == 422


def test_feedback_endpoint(client):
    feedback = {'timestamp': 1_760_000_000_000, 'username': 'alice', 'sessionId': 4242, 'text': 'Felt good'}
    assert client.post('/metrics/feedback', json=feedback, headers=AUTH).status_code == 201
    assert client.post('/metrics/feedback', json=feedback, headers=AUTH).json()['duplicate'] is True
    listed = client.get('/metrics/feedback', headers=AUTH).json()
    assert [f['text'] for f in listed] == ['Felt good']
    assert client.post('/metrics/feedback', json={**feedback, 'text': ''}, headers=AUTH).status_code == 422


def test_render_deploys_default_to_production(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv('ENVIRONMENT', raising=False)
    monkeypatch.setenv('RENDER', 'true')
    assert Settings(_env_file=None).environment == 'production'
    assert Settings(_env_file=None).docs_enabled is False
    monkeypatch.setenv('ENVIRONMENT', 'development')
    assert Settings(_env_file=None).environment == 'development'
    monkeypatch.delenv('RENDER')
    monkeypatch.delenv('ENVIRONMENT')
    assert Settings(_env_file=None).environment == 'development'


def test_long_usernames_from_old_app_builds_are_accepted(client):
    # App 1.0 had no username length limit; its records must not be stuck.
    assert client.post('/metrics/', json=metrics_payload(username='x' * 256), headers=AUTH).status_code == 201
    assert client.post('/metrics/', json=metrics_payload(username='x' * 257), headers=AUTH).status_code == 422
