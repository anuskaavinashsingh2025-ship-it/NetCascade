import pytest

from backend import create_app


@pytest.fixture
def app():
    return create_app(config={"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def store(app):
    return app.extensions["netcascade_store"]


def ok(resp, status=200):
    body = resp.get_json()
    assert resp.status_code == status, body
    assert body["success"] is True
    return body["data"]


def err(resp, status):
    body = resp.get_json()
    assert resp.status_code == status, body
    assert body["success"] is False
    assert body["error"]["status"] == status
    assert body["error"]["message"]
    return body["error"]
