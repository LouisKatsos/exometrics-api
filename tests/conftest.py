import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app import database, dependencies
from app.config import settings


def fake_verifier(token: str) -> dict:
    """'user-<name>' tokens are valid for uid <name>; anything else is rejected."""
    if not token.startswith('user-'):
        raise ValueError('bad token')
    return {'uid': token[len('user-'):]}


@pytest.fixture
def make_client(monkeypatch):
    """Builds a TestClient on an in-memory MongoDB with Firebase stubbed out.

    Settings can be changed before the app is built: make_client(environment='production').
    """
    clients = []

    def factory(**overrides):
        for key, value in overrides.items():
            monkeypatch.setattr(settings, key, value)
        monkeypatch.setattr(dependencies, 'init_firebase', lambda: None)
        monkeypatch.setattr(dependencies, 'token_verifier', fake_verifier)
        dependencies.rate_limiter.reset()
        monkeypatch.setattr(database, 'client', AsyncMongoMockClient())

        from app.main import create_app
        client = TestClient(create_app())
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


AUTH = {'Authorization': 'Bearer user-alice'}


def metrics_payload(**overrides) -> dict:
    """Exactly what the current app build (before entryId) sends."""
    payload = {
        'timestamp': 1_760_000_000_000,
        'username': 'alice',
        'sessionId': 4242,
        'hr': 96,
        'hrv': 41.5,
        'hrvSlope': -0.25,
        'distanceM': 120,
        'durationMs': 60_000,
        'calories': 7,
        'steps': 150,
    }
    payload.update(overrides)
    return payload
