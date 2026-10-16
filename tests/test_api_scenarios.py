import json

import pytest

from backend import create_app
from conftest import err, ok
from netcascade import get_topology, simulate_device_failure, simulate_link_failure


def names(client):
    return [s["name"] for s in ok(client.get("/api/scenarios"))["scenarios"]]


def by_name(client, name):
    return next(s for s in ok(client.get("/api/scenarios"))["scenarios"] if s["name"] == name)


# ------------------------------------------------------------------ listing
def test_seeded_scenarios_are_per_topology_and_not_run(client):
    data = ok(client.get("/api/scenarios"))
    assert data["topology"] == "basic"
    assert [s["name"] for s in data["scenarios"]] == ["Router Failure", "Switch Failure", "PC1 Link Failure"]
    assert all(s["status"] == "not_run" and s["result"] is None and s["last_run_at"] is None for s in data["scenarios"])
    assert data["summary"] == {"total": 3, "completed": 0, "pending": 0, "not_run": 3, "by_kind": {"device": 2, "link": 1, "devices": 0}}
    ok(client.post("/api/topologies/redundant/load"))
    assert names(client) == ["Router R1 Failure", "Switch SW1 Failure", "Uplink SW1–R1 Failure"]


def test_no_seed(tmp_path):
    c = create_app(config={"SEED_SCENARIOS": False}).test_client()
    assert ok(c.get("/api/scenarios"))["scenarios"] == []


def test_target_labels(client):
    data = ok(client.get("/api/scenarios"))["scenarios"]
    assert [s["target_label"] for s in data] == ["R1 (Router)", "SW1 (Switch)", "PC1 – SW1"]


# ------------------------------------------------------------------- create
def test_create_device_and_link_scenarios(client):
    s = ok(client.post("/api/scenarios", json={"name": "  Server   down ", "kind": "device", "device_id": "SRV1",
                                                "description": "Lose the only server"}), 201)
    assert s["name"] == "Server down" and s["status"] == "not_run" and s["target"] == {"kind": "device", "device_id": "SRV1"}
    link = ok(client.post("/api/scenarios", json={"name": "Uplink", "kind": "link", "source": "R1", "target": "SW1"}), 201)
    assert link["target"] == {"kind": "link", "source": "SW1", "target": "R1"}   # stored link orientation
    assert ok(client.get(f"/api/scenarios/{s['id']}"))["description"] == "Lose the only server"


@pytest.mark.parametrize("body,status", [
    ({"kind": "device", "device_id": "R1"}, 400),
    ({"name": "x"}, 400),
    ({"name": "", "kind": "device", "device_id": "R1"}, 422),
    ({"name": "x" * 81, "kind": "device", "device_id": "R1"}, 422),
    ({"name": "x", "kind": "device"}, 400),
    ({"name": "x", "kind": "device", "device_id": "NOPE"}, 404),
    ({"name": "x", "kind": "link", "source": "PC1", "target": "R1"}, 404),
    ({"name": "x", "kind": "link", "source": "PC1"}, 400),
    ({"name": "x", "kind": "node", "device_id": "R1"}, 422),
    ({"name": "x", "kind": "multi_device", "device_id": "R1"}, 422),
    ({"name": "x", "kind": "devices", "device_ids": ["R1"]}, 422),
    ({"name": "x", "kind": "devices", "device_ids": ["R1", "R1"]}, 422),
    ({"name": "x", "kind": "devices", "device_ids": "R1,SW1"}, 422),
    ({"name": "x", "kind": "devices", "device_ids": ["R1", "NOPE"]}, 404),
    ({"name": "x", "kind": "devices"}, 400),
    ({"name": "x", "kind": "device", "device_id": "R1", "description": 5}, 422),
    ({"name": "x", "kind": "device", "device_id": "R1", "extra": 1}, 400),
    ({"name": "router failure", "kind": "device", "device_id": "R1"}, 409),   # case-insensitive duplicate
])
def test_create_validation(client, body, status):
    err(client.post("/api/scenarios", json=body), status)
    assert len(names(client)) == 3


# -------------------------------------------------------------- rename/copy
def test_rename_and_edit_description(client):
    sid = by_name(client, "Router Failure")["id"]
    s = ok(client.patch(f"/api/scenarios/{sid}", json={"name": "Core router down", "description": "New text"}))
    assert s["name"] == "Core router down" and s["description"] == "New text"
    err(client.patch(f"/api/scenarios/{sid}", json={"name": "Switch Failure"}), 409)
    err(client.patch(f"/api/scenarios/{sid}", json={}), 400)
    err(client.patch(f"/api/scenarios/{sid}", json={"target": "SW1"}), 400)
    err(client.patch("/api/scenarios/nope", json={"name": "x"}), 404)


def test_copy_copies_config_not_results(client):
    sid = by_name(client, "Router Failure")["id"]
    ok(client.post(f"/api/scenarios/{sid}/run"))
    c1 = ok(client.post(f"/api/scenarios/{sid}/copy"), 201)
    c2 = ok(client.post(f"/api/scenarios/{sid}/copy"), 201)
    assert c1["name"] == "Router Failure (copy)" and c2["name"] == "Router Failure (copy 2)"
    assert c1["target"] == {"kind": "device", "device_id": "R1"}
    assert c1["status"] == "not_run" and c1["result"] is None and c1["last_run_at"] is None
    err(client.post("/api/scenarios/nope/copy"), 404)


def test_delete(client):
    sid = by_name(client, "Switch Failure")["id"]
    assert ok(client.delete(f"/api/scenarios/{sid}"))["name"] == "Switch Failure"
    err(client.get(f"/api/scenarios/{sid}"), 404)
    err(client.delete(f"/api/scenarios/{sid}"), 404)


# ---------------------------------------------------------------------- run
def test_run_device_scenario_matches_engine(client, store):
    sid = by_name(client, "Router Failure")["id"]
    before = store.network.to_dict()
    s = ok(client.post(f"/api/scenarios/{sid}/run"))
    expected = simulate_device_failure(get_topology("basic"), "R1")
    r = s["result"]
    assert s["status"] == "completed" and s["last_run_at"]
    assert r["impact_score"] == expected.impact_score == 100.0 and r["severity"] == "Critical"
    assert r["affected_clients"] == expected.affected_clients
    assert len(r["lost_pairs"]) == 3 and r["is_single_point_of_failure"] is True
    assert r["matrix"]["nodes"] == ["PC1", "PC2", "PC3", "SRV1"]
    assert r["matrix"]["reachable"][0] == [None, True, True, False]       # PCs still see each other via SW1
    assert r["matrix"]["reachable"][3] == [False, False, False, None]
    assert store.network.to_dict() == before                              # topology untouched
    sim = ok(client.get("/api/simulation"))                               # also the current simulation
    assert sim["active"] and sim["result"]["label"] == "R1"
    summary = ok(client.get("/api/scenarios"))["summary"]
    assert summary["completed"] == 1 and summary["not_run"] == 2


def test_run_link_scenario_with_alternate_paths(client):
    ok(client.post("/api/topologies/redundant/load"))
    sid = by_name(client, "Uplink SW1–R1 Failure")["id"]
    r = ok(client.post(f"/api/scenarios/{sid}/run"))["result"]
    expected = simulate_link_failure(get_topology("redundant"), "SW1", "R1")
    assert r["impact_score"] == expected.impact_score == 0.0
    assert len(r["alternate_paths"]) == len(expected.rerouted_pairs) == 4
    assert all(all(row[j] in (True, None) for j in range(len(row))) for row in r["matrix"]["reachable"])


def test_topology_edit_makes_result_outdated_and_rerun_completes(client):
    sid = by_name(client, "Router Failure")["id"]
    ok(client.post(f"/api/scenarios/{sid}/run"))
    ok(client.patch("/api/links/SW1/R1", json={"latency_ms": 9}))
    s = ok(client.get(f"/api/scenarios/{sid}"))
    assert s["status"] == "outdated" and s["result"] is not None
    assert ok(client.get("/api/scenarios"))["summary"]["pending"] == 1
    assert ok(client.post(f"/api/scenarios/{sid}/run"))["status"] == "completed"


def test_deleted_target_makes_scenario_invalid_and_unrunnable(client):
    sid = by_name(client, "PC1 Link Failure")["id"]
    ok(client.delete("/api/links/PC1/SW1"))
    assert ok(client.get(f"/api/scenarios/{sid}"))["status"] == "invalid"
    err(client.post(f"/api/scenarios/{sid}/run"), 404)


def test_run_requires_its_topology_to_be_loaded(client):
    sid = by_name(client, "Router Failure")["id"]
    ok(client.post("/api/topologies/redundant/load"))
    e = err(client.post(f"/api/scenarios/{sid}/run"), 409)
    assert "basic" in e["message"]


def test_run_unknown(client):
    err(client.post("/api/scenarios/nope/run"), 404)


# --------------------------------------------------------------- persistence
def test_persists_to_json(tmp_path):
    path = tmp_path / "s.json"
    c = create_app(config={"SCENARIOS_PATH": str(path)}).test_client()
    sid = next(s["id"] for s in ok(c.get("/api/scenarios"))["scenarios"] if s["name"] == "Router Failure")
    ok(c.post(f"/api/scenarios/{sid}/run"))
    ok(c.post("/api/scenarios", json={"name": "Mine", "kind": "device", "device_id": "SW1"}), 201)
    saved = json.loads(path.read_text())["scenarios"]
    assert len(saved) == 7
    c2 = create_app(config={"SCENARIOS_PATH": str(path)}).test_client()     # restart
    items = ok(c2.get("/api/scenarios"))["scenarios"]
    assert "Mine" in [s["name"] for s in items]
    assert next(s for s in items if s["id"] == sid)["status"] == "completed"


def test_corrupt_file_starts_clean(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    c = create_app(config={"SCENARIOS_PATH": str(path)}).test_client()
    assert len(ok(c.get("/api/scenarios"))["scenarios"]) == 3   # reseeded


# --------------------------------------------------------- multiple devices
def test_multi_device_scenario_create_run_and_invalidate(client, store):
    s = ok(client.post("/api/scenarios", json={"name": "Router and switch", "kind": "devices", "device_ids": ["R1", "SW1"]}), 201)
    assert s["kind"] == "devices" and s["target"] == {"kind": "devices", "device_ids": ["R1", "SW1"]}
    assert s["target_label"] == "R1, SW1" and s["status"] == "not_run"
    assert ok(client.get("/api/scenarios"))["summary"]["by_kind"]["devices"] == 1
    before = store.network.to_dict()
    r = ok(client.post(f"/api/scenarios/{s['id']}/run"))["result"]
    assert r["kind"] == "devices" and r["component"] == ["R1", "SW1"] and r["label"] == "R1+SW1"
    assert r["impact_score"] == 100.0 and r["is_single_point_of_failure"] is False
    assert r["matrix"]["reachable"][0] == [None, False, False, False]      # SW1 gone: PCs isolated
    assert store.network.to_dict() == before
    copy = ok(client.post(f"/api/scenarios/{s['id']}/copy"), 201)
    assert copy["target"] == s["target"] and copy["result"] is None
    ok(client.delete("/api/devices/SW1"))
    assert ok(client.get(f"/api/scenarios/{s['id']}"))["status"] == "invalid"


def test_multi_device_redundant_routers_fail_together(client):
    ok(client.post("/api/topologies/redundant/load"))
    s = ok(client.post("/api/scenarios", json={"name": "Both routers", "kind": "devices", "device_ids": ["R1", "R2"]}), 201)
    r = ok(client.post(f"/api/scenarios/{s['id']}/run"))["result"]
    assert r["impact_score"] == 100.0 and r["severity"] == "Critical"
    assert r["disconnected_devices"] == ["SRV1", "SRV2"]
