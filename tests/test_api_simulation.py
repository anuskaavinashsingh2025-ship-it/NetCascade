import pytest

from conftest import err, ok
from netcascade import get_topology, rank_devices, simulate_device_failure, single_points_of_failure


def load(client, name):
    ok(client.post(f"/api/topologies/{name}/load"))


# --------------------------------------------------------------- device failure
def test_simulate_router_failure_basic(client):
    r = ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    assert r["kind"] == "device" and r["component"] == "R1"
    assert r["impact_score"] == 100.0 and r["severity"] == "Critical"
    assert r["affected_clients"] == ["PC1", "PC2", "PC3"] and r["affected_client_count"] == 3
    assert r["lost_pairs"][0] == {"client": "PC1", "server": "SRV1"}
    assert r["lost_paths"][0]["original_path"] == ["PC1", "SW1", "R1", "SRV1"]
    assert r["alternate_paths"] == []
    assert r["disconnected_devices"] == ["SRV1"]
    assert r["is_single_point_of_failure"] is True


def test_simulation_matches_phase2_engine(client):
    load(client, "campus")
    r = ok(client.post("/api/simulate/device", json={"device_id": "ACC-A1"}))
    expected = simulate_device_failure(get_topology("campus"), "ACC-A1")
    assert r["impact_score"] == expected.impact_score
    assert r["severity"] == expected.severity.value
    assert r["affected_clients"] == expected.affected_clients


def test_redundant_failure_returns_alternate_paths(client):
    load(client, "redundant")
    r = ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    assert r["impact_score"] == 0.0 and r["severity"] == "Low"
    assert r["is_single_point_of_failure"] is False
    alt = next(p for p in r["alternate_paths"] if p == {**p, "client": "PC1", "server": "SRV1"})
    assert "R1" in alt["original_path"] and "R1" not in alt["alternate_path"]


def test_simulate_device_accepts_id_alias(client):
    assert ok(client.post("/api/simulate/device", json={"id": "SW1"}))["component"] == "SW1"


@pytest.mark.parametrize("body,status", [
    ({}, 400), ({"device_id": None}, 400), ({"device_id": ""}, 422), ({"device_id": 3}, 422),
    ({"device_id": "NOPE"}, 404),
])
def test_simulate_device_invalid(client, body, status):
    err(client.post("/api/simulate/device", json=body), status)


# ----------------------------------------------------------------- link failure
def test_simulate_link_failure(client):
    r = ok(client.post("/api/simulate/link", json={"source": "SW1", "target": "R1"}))
    assert r["kind"] == "link" and r["component"] == {"source": "SW1", "target": "R1"}
    assert r["label"] == "SW1--R1" and r["severity"] == "Critical"
    assert r["disconnected_devices"] == ["R1", "SRV1"]


def test_redundant_link_failure_reroutes(client):
    load(client, "redundant")
    r = ok(client.post("/api/simulate/link", json={"source": "SW1", "target": "R1"}))
    assert r["impact_score"] == 0.0 and len(r["alternate_paths"]) == 4
    for p in r["alternate_paths"]:
        hops = list(zip(p["alternate_path"], p["alternate_path"][1:]))
        assert ("SW1", "R1") not in hops and ("R1", "SW1") not in hops


@pytest.mark.parametrize("body,status", [
    ({"source": "SW1"}, 400), ({"source": "SW1", "target": "NOPE"}, 404),
    ({"source": "PC1", "target": "R1"}, 404), ({"source": 1, "target": "R1"}, 422),
])
def test_simulate_link_invalid(client, body, status):
    err(client.post("/api/simulate/link", json=body), status)


# ------------------------------------------------- requires / disconnected / empty
def test_requires_respected(client):
    load(client, "redundant")
    ok(client.patch("/api/devices/PC1", json={"requires": ["SRV1"]}))
    r = ok(client.post("/api/simulate/device", json={"device_id": "SRV2"}))
    assert "PC1" not in r["affected_clients"]
    assert r["affected_clients"] == ["PC2", "PC3", "PC4"] and r["severity"] == "Critical"


def test_disconnected_network(client):
    ok(client.delete("/api/links/SW1/R1"))
    r = ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    assert r["affected_clients"] == [] and r["lost_pairs"] == []  # already broken beforehand
    conn = ok(client.get("/api/analysis/connectivity"))
    assert conn["connected"] is False and len(conn["components"]) == 2
    assert len(conn["unreachable_required_pairs"]) == 3


def test_empty_topology_is_safe(client):
    ok(client.post("/api/topology/new", json={"name": "empty"}), 201)
    err(client.post("/api/simulate/device", json={"device_id": "R1"}), 404)
    assert ok(client.get("/api/analysis/rankings")) == {"devices": [], "links": []}
    assert ok(client.get("/api/analysis/spof")) == {"devices": [], "links": [], "count": 0}
    conn = ok(client.get("/api/analysis/connectivity"))
    assert conn["connected"] is True and conn["components"] == []


def test_topology_without_clients(client):
    ok(client.post("/api/topology/new", json={"name": "core"}), 201)
    ok(client.post("/api/devices", json={"id": "R1", "type": "router"}), 201)
    ok(client.post("/api/devices", json={"id": "S1", "type": "server"}), 201)
    ok(client.post("/api/links", json={"source": "R1", "target": "S1"}), 201)
    r = ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    assert r["total_clients"] == 0 and r["impact_score"] == 0.0 and r["severity"] == "Low"


# --------------------------------------------- original topology never modified
@pytest.mark.parametrize("name", ["basic", "redundant", "campus"])
def test_simulations_never_modify_saved_topology(client, store, name):
    load(client, name)
    before = ok(client.get("/api/topology"))
    saved = store.network.to_dict()
    net = get_topology(name)
    for dev in net.device_ids():
        ok(client.post("/api/simulate/device", json={"device_id": dev}))
    for link in net.links():
        ok(client.post("/api/simulate/link", json={"source": link.source, "target": link.target}))
    ok(client.get("/api/analysis/rankings"))
    ok(client.get("/api/analysis/spof"))
    assert store.network.to_dict() == saved
    after = ok(client.get("/api/topology"))
    assert after == before and after["modified"] is False


# ---------------------------------------------------------------- simulation reset
def test_simulation_state_and_reset(client):
    assert ok(client.get("/api/simulation")) == {"active": False, "result": None}
    ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    current = ok(client.get("/api/simulation"))
    assert current["active"] is True and current["result"]["component"] == "R1"
    reset = ok(client.post("/api/simulation/reset"))
    assert reset["active"] is False and reset["device_count"] == 6 and reset["link_count"] == 5
    assert ok(client.get("/api/simulation"))["active"] is False
    assert ok(client.get("/api/topology"))["modified"] is False


def test_failed_simulation_keeps_previous_result(client):
    ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    err(client.post("/api/simulate/device", json={"device_id": "NOPE"}), 404)
    assert ok(client.get("/api/simulation"))["result"]["component"] == "R1"


def test_editing_clears_stale_simulation(client):
    ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    ok(client.post("/api/devices", json={"id": "PC9", "type": "pc"}), 201)
    assert ok(client.get("/api/simulation"))["active"] is False


def test_topology_reset_clears_simulation(client):
    ok(client.post("/api/simulate/device", json={"device_id": "R1"}))
    ok(client.post("/api/topology/reset"))
    assert ok(client.get("/api/simulation"))["active"] is False


# ------------------------------------------------------------------- comparison
def test_compare_two_scenarios(client):
    load(client, "redundant")
    data = ok(client.post("/api/simulate/compare", json={"scenarios": [
        {"kind": "device", "device_id": "R1"},
        {"kind": "device", "device_id": "SW1"},
    ]}))
    assert data["scenarios"]["A"]["severity"] == "Low"
    assert data["scenarios"]["B"]["severity"] == "High"
    c = data["comparison"]
    assert c["higher_impact"] == "B" and c["impact_score_difference"] == 50.0
    assert c["only_affected_by_B"] == ["PC1", "PC2"] and c["shared_affected_clients"] == []
    assert c["single_point_of_failure"] == {"A": False, "B": True}


def test_compare_device_vs_link(client):
    data = ok(client.post("/api/simulate/compare", json={"scenarios": [
        {"kind": "link", "source": "PC1", "target": "SW1"},
        {"kind": "device", "device_id": "R1"},
    ]}))
    c = data["comparison"]
    assert c["higher_impact"] == "B" and c["shared_affected_clients"] == ["PC1"]
    assert c["only_affected_by_B"] == ["PC2", "PC3"]


def test_compare_equal(client):
    data = ok(client.post("/api/simulate/compare", json={"scenarios": [
        {"kind": "device", "id": "R1"}, {"kind": "device", "id": "SW1"}]}))
    assert data["comparison"]["higher_impact"] == "equal"


def test_compare_does_not_change_state(client, store):
    saved = store.network.to_dict()
    ok(client.post("/api/simulate/compare", json={"scenarios": [
        {"kind": "device", "device_id": "R1"}, {"kind": "device", "device_id": "SW1"}]}))
    assert store.network.to_dict() == saved
    assert ok(client.get("/api/simulation"))["active"] is False


@pytest.mark.parametrize("body,status", [
    ({}, 400),
    ({"scenarios": "R1"}, 400),
    ({"scenarios": [{"kind": "device", "device_id": "R1"}]}, 400),
    ({"scenarios": [{"kind": "device", "device_id": "R1"}] * 3}, 400),
    ({"scenarios": [{"kind": "device", "device_id": "R1"}, "SW1"]}, 400),
    ({"scenarios": [{"kind": "node", "device_id": "R1"}, {"kind": "device", "device_id": "SW1"}]}, 422),
    ({"scenarios": [{"kind": "device", "device_id": "R1"}, {"kind": "device", "device_id": "NOPE"}]}, 404),
    ({"scenarios": [{"kind": "device", "device_id": "R1"}, {"kind": "link", "source": "PC1"}]}, 400),
])
def test_compare_invalid(client, body, status):
    err(client.post("/api/simulate/compare", json=body), status)


# -------------------------------------------------------------- rankings & SPOF
def test_rankings_match_engine(client):
    load(client, "redundant")
    data = ok(client.get("/api/analysis/rankings"))
    engine = rank_devices(get_topology("redundant"))
    assert [d["label"] for d in data["devices"]] == [r.label for r in engine]
    assert [d["rank"] for d in data["devices"]] == list(range(1, 11))
    assert len(data["links"]) == 14
    scores = [d["impact_score"] for d in data["devices"]]
    assert scores == sorted(scores, reverse=True)


def test_rankings_filters(client):
    load(client, "redundant")
    data = ok(client.get("/api/analysis/rankings?kind=devices&type=router&top=1"))
    assert list(data) == ["devices"] and len(data["devices"]) == 1
    assert data["devices"][0]["label"] in {"R1", "R2"}
    assert list(ok(client.get("/api/analysis/rankings?kind=links&top=2"))) == ["links"]


@pytest.mark.parametrize("query,status", [
    ("kind=nodes", 400), ("top=0", 400), ("top=abc", 400), ("type=laptop", 422),
])
def test_rankings_invalid_params(client, query, status):
    err(client.get(f"/api/analysis/rankings?{query}"), status)


@pytest.mark.parametrize("name", ["basic", "redundant", "campus"])
def test_spof_matches_engine(client, name):
    load(client, name)
    data = ok(client.get("/api/analysis/spof"))
    engine = single_points_of_failure(get_topology(name))
    assert [d["label"] for d in data["devices"]] == [r.label for r in engine["devices"]]
    assert [d["label"] for d in data["links"]] == [r.label for r in engine["links"]]
    assert data["count"] == len(engine["devices"]) + len(engine["links"])
    assert all(d["is_single_point_of_failure"] for d in data["devices"] + data["links"])


def test_spof_redundant_excludes_routers(client):
    load(client, "redundant")
    labels = {d["label"] for d in ok(client.get("/api/analysis/spof"))["devices"]}
    assert labels == {"SW1", "SW2", "SRV1", "SRV2"}


def test_spof_reflects_edits(client):
    load(client, "redundant")
    ok(client.delete("/api/links/R2/SRV1"))  # SRV1 now only reachable via R1
    labels = {d["label"] for d in ok(client.get("/api/analysis/spof"))["devices"]}
    assert "R1" in labels
