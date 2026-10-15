import pytest


def test_index_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "<title>NetCascade</title>" in html
    assert "/assets/js/app.js" in html and "/assets/css/app.css" in html


@pytest.mark.parametrize("path,mime", [
    ("/assets/js/app.js", "javascript"),
    ("/assets/js/api.js", "javascript"),
    ("/assets/js/graph.js", "javascript"),
    ("/assets/js/icons.js", "javascript"),
    ("/assets/css/app.css", "text/css"),
])
def test_assets_served(client, path, mime):
    resp = client.get(path)
    assert resp.status_code == 200
    assert mime in resp.content_type


def test_missing_asset_404(client):
    assert client.get("/assets/js/nope.js").status_code == 404


def test_asset_path_traversal_blocked(client):
    assert client.get("/assets/../../backend/store.py").status_code == 404


def test_api_still_json(client):
    assert client.get("/api/health").get_json()["success"] is True
