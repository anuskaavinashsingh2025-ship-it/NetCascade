import pytest

from conftest import err, ok


def test_health(client):
    assert ok(client.get("/api/health")) == {"status": "ok"}


def test_list_topologies(client):
    data = ok(client.get("/api/topologies"))
    assert [t["name"] for t in data["topologies"]] == ["basic", "redundant", "campus"]
    assert data["active"] == "basic"
    campus = data["topologies"][2]
    assert campus["device_count"] == 23 and campus["link_count"] == 34
    assert campus["description"]


@pytest.mark.parametrize("name,devices,links", [("basic", 6, 5), ("redundant", 10, 14), ("campus", 23, 34)])
def test_load_topology(client, name, devices, links):
    data = ok(client.post(f"/api/topologies/{name}/load"))
    assert data["name"] == name and data["source"] == name and data["modified"] is False
    assert data["stats"]["device_count"] == devices and data["stats"]["link_count"] == links
    assert len(data["devices"]) == devices and len(data["links"]) == links
    assert ok(client.get("/api/topology"))["name"] == name


def test_load_is_case_insensitive(client):
    assert ok(client.post("/api/topologies/Campus/load"))["name"] == "campus"


def test_load_unknown_topology(client):
    e = err(client.post("/api/topologies/mesh/load"), 404)
    assert e["code"] == "not_found"


def test_get_topology_shape(client):
    data = ok(client.get("/api/topology"))
    assert data["stats"] == {
        "device_count": 6, "link_count": 5,
        "by_type": {"pc": 3, "switch": 1, "router": 1, "server": 1},
        "connected": True, "component_count": 1,
    }
    dev = next(d for d in data["devices"] if d["id"] == "PC1")
    assert dev["type"] == "pc" and dev["ip_address"] == "192.168.1.11" and dev["degree"] == 1
    link = data["links"][0]
    assert {"id", "source", "target", "bandwidth_mbps", "latency_ms", "attributes"} <= set(link)


def test_new_empty_topology(client):
    data = ok(client.post("/api/topology/new", json={"name": "lab"}), 201)
    assert data["name"] == "lab" and data["source"] is None
    assert data["devices"] == [] and data["links"] == []
    assert data["stats"]["connected"] is True and data["stats"]["component_count"] == 0


def test_new_topology_default_name(client):
    assert ok(client.post("/api/topology/new"), 201)["name"] == "custom"


@pytest.mark.parametrize("name", ["", "   ", 5, None])
def test_new_topology_bad_name(client, name):
    err(client.post("/api/topology/new", json={"name": name}), 422)


def test_reset_topology_discards_edits(client):
    ok(client.delete("/api/devices/PC1"))
    ok(client.post("/api/devices", json={"id": "PC9", "type": "pc"}), 201)
    assert ok(client.get("/api/topology"))["modified"] is True
    data = ok(client.post("/api/topology/reset"))
    assert data["modified"] is False
    ids = {d["id"] for d in data["devices"]}
    assert "PC1" in ids and "PC9" not in ids


def test_reset_empty_topology(client):
    ok(client.post("/api/topology/new", json={"name": "x"}), 201)
    ok(client.post("/api/devices", json={"id": "R1", "type": "router"}), 201)
    assert ok(client.post("/api/topology/reset"))["devices"] == []


def test_loading_discards_previous_edits(client):
    ok(client.delete("/api/devices/PC1"))
    ok(client.post("/api/topologies/redundant/load"))
    data = ok(client.post("/api/topologies/basic/load"))
    assert any(d["id"] == "PC1" for d in data["devices"])


# --------------------------------------------------------------- generic errors
def test_unknown_route_is_json_404(client):
    err(client.get("/api/nope"), 404)


def test_wrong_method_is_json_405(client):
    err(client.delete("/api/topologies"), 405)


def test_malformed_json(client):
    e = err(client.post("/api/devices", data="{bad json", content_type="application/json"), 400)
    assert "Malformed JSON" in e["message"]


def test_non_object_json(client):
    err(client.post("/api/devices", json=["PC1", "pc"]), 400)


def test_wrong_content_type(client):
    err(client.post("/api/devices", data="id=PC9", content_type="application/x-www-form-urlencoded"), 415)
