import pytest

from conftest import err, ok
from netcascade import (
    NetworkGraph,
    Severity,
    ValidationError,
    get_topology,
    simulate_device_failure,
    simulate_devices_failure,
)


# ------------------------------------------------------------------ engine
def test_combination_is_worse_than_each_failure_alone():
    net = get_topology("redundant")
    assert simulate_device_failure(net, "R1").impact_score == 0.0
    assert simulate_device_failure(net, "R2").impact_score == 0.0
    r = simulate_devices_failure(net, ["R1", "R2"])
    assert r.kind == "devices" and r.component == ("R1", "R2") and r.label == "R1+R2"
    assert r.impact_score == 100.0 and r.severity is Severity.CRITICAL
    assert r.affected_clients == ["PC1", "PC2", "PC3", "PC4"] and len(r.lost_pairs) == 8
    assert r.disconnected_devices == ["SRV1", "SRV2"]
    assert r.is_single_point_of_failure is False
    assert "Failure of devices R1+R2" in r.summary() and "Single point" not in r.summary()


def test_one_switch_and_one_uplink_partner():
    net = get_topology("redundant")
    r = simulate_devices_failure(net, ["SW1", "R1"])
    assert r.affected_clients == ["PC1", "PC2"]           # SW1 clients lost; SW2 clients reroute via R2
    assert r.rerouted_pairs and all("R1" not in p and "SW1" not in p for p in r.rerouted_pairs.values())


def test_failed_pcs_count_as_affected():
    r = simulate_devices_failure(get_topology("basic"), ["PC1", "PC2"])
    assert r.affected_clients == ["PC1", "PC2"] and r.impact_score == 66.67


def test_original_untouched():
    net = get_topology("campus")
    before = net.to_dict()
    simulate_devices_failure(net, ["CORE1", "CORE2", "DC-SW"])
    assert net.to_dict() == before


@pytest.mark.parametrize("ids,msg", [
    (["R1"], "at least two"),
    (["R1", "R1"], "duplicates"),
    (["R1", "NOPE"], "Unknown device"),
    ([], "at least two"),
    ("R1", "must be a list"),
    ([1, 2], "Unknown device"),
])
def test_engine_validation(ids, msg):
    with pytest.raises(ValidationError, match=msg):
        simulate_devices_failure(get_topology("basic"), ids)


def test_all_devices_fail():
    net = get_topology("basic")
    r = simulate_devices_failure(net, net.device_ids())
    assert r.impact_score == 100.0 and r.disconnected_devices == []


def test_empty_network_has_no_devices():
    with pytest.raises(ValidationError):
        simulate_devices_failure(NetworkGraph(), ["A", "B"])


# --------------------------------------------------------------------- API
def test_simulate_devices_endpoint(client, store):
    ok(client.post("/api/topologies/redundant/load"))
    before = store.network.to_dict()
    r = ok(client.post("/api/simulate/devices", json={"device_ids": ["R1", "R2"]}))
    assert r["kind"] == "devices" and r["component"] == ["R1", "R2"] and r["label"] == "R1+R2"
    assert r["impact_score"] == 100.0 and r["execution_ms"] > 0
    assert r["lost_paths"][0]["original_path"][0] == "PC1"
    assert ok(client.get("/api/simulation"))["result"]["label"] == "R1+R2"
    assert store.network.to_dict() == before


@pytest.mark.parametrize("body,status", [
    ({}, 400),
    ({"device_ids": "R1"}, 422),
    ({"device_ids": ["R1"]}, 422),
    ({"device_ids": ["R1", "R1"]}, 422),
    ({"device_ids": ["R1", ""]}, 422),
    ({"device_ids": ["R1", "NOPE"]}, 404),
])
def test_simulate_devices_validation(client, body, status):
    err(client.post("/api/simulate/devices", json=body), status)


def test_compare_accepts_multi_device(client):
    ok(client.post("/api/topologies/redundant/load"))
    data = ok(client.post("/api/simulate/compare", json={"scenarios": [
        {"kind": "device", "device_id": "R1"}, {"kind": "devices", "device_ids": ["R1", "R2"]}]}))
    assert data["comparison"]["higher_impact"] == "B"
    assert data["scenarios"]["B"]["component"] == ["R1", "R2"]
