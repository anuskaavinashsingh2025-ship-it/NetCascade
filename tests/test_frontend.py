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


def test_scenarios_page_has_evaluation_section(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="ev"' in html and "Evaluation &amp; Resilience" in html
    for part in ("ev-current", "ev-compare", "ev-timing", "ev-common", "ev-refresh"):
        assert f'id="{part}"' in html
    assert "campus" not in html.lower().split('id="page-scenarios"')[1].split("</main>")[0].replace("campus benchmark", "")


def test_evaluation_endpoints_used_by_ui_respond(client):
    js = client.get("/assets/js/api.js").get_data(as_text=True)
    assert "/analysis/evaluation?repeat=" in js and "/analysis/evaluation/compare?topologies=" in js
    cur = client.get("/api/analysis/evaluation?repeat=1&records=false").get_json()["data"]
    assert "records" not in cur and cur["timing"]["median_ms"] > 0
    cmp = client.get("/api/analysis/evaluation/compare?topologies=basic,redundant,campus&repeat=1").get_json()["data"]
    assert [t["name"] for t in cmp["topologies"]] == ["basic", "redundant", "campus"]
