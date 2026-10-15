import pytest

from conftest import err, ok


def test_simulation_responses_include_execution_time(client):
    r = ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    assert r["execution_ms"] > 0
    assert ok(client.get("/api/simulation"))["result"]["execution_ms"] == r["execution_ms"]
    assert ok(client.post("/api/simulate/link", json={"source": "SW1", "target": "R1"}))["execution_ms"] > 0
    cmp = ok(client.post("/api/simulate/compare", json={"scenarios": [
        {"kind": "device", "device_id": "R1"}, {"kind": "link", "source": "PC1", "target": "SW1"}]}))
    assert cmp["scenarios"]["A"]["execution_ms"] > 0 and cmp["scenarios"]["B"]["execution_ms"] > 0


def test_scenario_run_records_execution_time(client):
    sid = ok(client.get("/api/scenarios"))["scenarios"][0]["id"]
    assert ok(client.post(f"/api/scenarios/{sid}/run"))["result"]["execution_ms"] > 0


def test_evaluate_current_topology(client, store):
    before = store.network.to_dict()
    data = ok(client.get("/api/analysis/evaluation?repeat=2"))
    assert data["name"] == "basic" and data["device_failures"]["count"] == 6
    assert len(data["records"]) == 11 and data["timing"]["repeat"] == 2
    assert "records" not in ok(client.get("/api/analysis/evaluation?records=false"))
    assert store.network.to_dict() == before


def test_evaluate_reflects_edits(client):
    ok(client.delete("/api/devices/PC3"))
    assert ok(client.get("/api/analysis/evaluation?repeat=1"))["clients"] == 2


def test_evaluate_compare(client, store):
    ok(client.delete("/api/devices/PC1"))   # workspace edits must not leak into the predefined comparison
    data = ok(client.get("/api/analysis/evaluation/compare?topologies=basic,redundant&repeat=1"))
    names = [t["name"] for t in data["topologies"]]
    assert names == ["basic", "redundant"]
    assert data["topologies"][0]["clients"] == 3
    assert "records" not in data["topologies"][0]
    assert any(c["label"] == "R1" for c in data["common_failures"])
    with_records = ok(client.get("/api/analysis/evaluation/compare?topologies=basic&repeat=1&records=true"))
    assert len(with_records["topologies"][0]["records"]) == 11


@pytest.mark.parametrize("query,status", [
    ("repeat=0", 400), ("repeat=51", 400), ("repeat=abc", 400),
])
def test_evaluate_bad_repeat(client, query, status):
    err(client.get(f"/api/analysis/evaluation?{query}"), status)
    err(client.get(f"/api/analysis/evaluation/compare?{query}"), status)


@pytest.mark.parametrize("topologies", ["mesh", "basic,mesh", ","])
def test_evaluate_compare_unknown(client, topologies):
    err(client.get(f"/api/analysis/evaluation/compare?topologies={topologies}&repeat=1"), 404)


def test_evaluate_empty_topology(client):
    ok(client.post("/api/topology/new", json={"name": "empty"}), 201)
    data = ok(client.get("/api/analysis/evaluation?repeat=1"))
    assert data["all_failures"]["count"] == 0 and data["records"] == []
