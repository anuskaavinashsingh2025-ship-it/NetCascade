import pytest

from conftest import err, ok


# ---------------------------------------------------------------- read devices
def test_list_devices_and_filter(client):
    assert len(ok(client.get("/api/devices"))["devices"]) == 6
    pcs = ok(client.get("/api/devices?type=pc"))["devices"]
    assert [d["id"] for d in pcs] == ["PC1", "PC2", "PC3"]


def test_list_devices_bad_type(client):
    err(client.get("/api/devices?type=laptop"), 422)


def test_device_details(client):
    data = ok(client.get("/api/devices/SW1"))
    assert data["type"] == "switch" and data["degree"] == 4
    assert data["neighbors"] == ["PC1", "PC2", "PC3", "R1"]
    assert len(data["links"]) == 4
    assert ok(client.get("/api/devices/SRV1"))["required_by"] == ["PC1", "PC2", "PC3"]


def test_device_not_found(client):
    assert err(client.get("/api/devices/NOPE"), 404)["code"] == "not_found"


# -------------------------------------------------------------- create devices
def test_create_device(client):
    data = ok(client.post("/api/devices", json={
        "id": "PC4", "type": "pc", "name": "Lab PC", "ip_address": "192.168.1.50",
        "attributes": {"room": "B12"}}), 201)
    assert data["id"] == "PC4" and data["name"] == "Lab PC"
    assert data["attributes"] == {"room": "B12"} and data["degree"] == 0
    assert ok(client.get("/api/topology"))["stats"]["device_count"] == 7


def test_create_pc_with_requires(client):
    data = ok(client.post("/api/devices", json={"id": "PC4", "type": "pc", "requires": "SRV1"}), 201)
    assert data["requires"] == ["SRV1"]


@pytest.mark.parametrize("body,status", [
    ({"type": "pc"}, 400),                                   # missing id
    ({"id": "PC9"}, 400),                                    # missing type
    ({"id": "PC9", "type": "laptop"}, 422),
    ({"id": "bad id", "type": "pc"}, 422),
    ({"id": 7, "type": "pc"}, 422),
    ({"id": "PC9", "type": "pc", "ip_address": "300.1.1.1"}, 422),
    ({"id": "PC9", "type": "pc", "attributes": []}, 422),
    ({"id": "PC9", "type": "pc", "attributes": {"name": "x"}}, 422),   # reserved key
    ({"id": "PC9", "type": "pc", "colour": "red"}, 400),               # unknown field
    ({"id": "PC9", "type": "pc", "requires": ["NOPE"]}, 422),
    ({"id": "PC9", "type": "pc", "requires": ["SW1"]}, 422),           # not a server
    ({"id": "PC9", "type": "pc", "requires": [3]}, 422),
    ({"id": "SW9", "type": "switch", "requires": ["SRV1"]}, 422),      # only PCs
])
def test_create_device_validation(client, body, status):
    err(client.post("/api/devices", json=body), status)
    assert ok(client.get("/api/topology"))["stats"]["device_count"] == 6  # nothing saved


def test_create_duplicate_device(client):
    assert err(client.post("/api/devices", json={"id": "PC1", "type": "pc"}), 409)["code"] == "conflict"


def test_create_duplicate_ip(client):
    err(client.post("/api/devices", json={"id": "PC9", "type": "pc", "ip_address": "192.168.1.11"}), 409)


def test_create_with_empty_body(client):
    err(client.post("/api/devices"), 400)


# -------------------------------------------------------------- update devices
def test_update_device(client):
    data = ok(client.patch("/api/devices/PC1", json={
        "name": "Reception", "ip_address": "192.168.1.99", "attributes": {"floor": 1}}))
    assert data["name"] == "Reception" and data["ip_address"] == "192.168.1.99"
    assert data["attributes"] == {"floor": 1}
    assert data["neighbors"] == ["SW1"]  # links preserved
    data = ok(client.patch("/api/devices/PC1", json={"attributes": {"floor": None}}))
    assert data["attributes"] == {}


def test_update_requires_and_clear(client):
    assert ok(client.patch("/api/devices/PC1", json={"requires": ["SRV1"]}))["requires"] == ["SRV1"]
    assert ok(client.patch("/api/devices/PC1", json={"requires": None}))["requires"] is None


def test_update_type_validated_against_links(client):
    # PC1 is linked to SW1; a server may also connect to a switch, so this is allowed...
    ok(client.patch("/api/devices/PC1", json={"type": "server"}))
    # ...but SW1 -> pc would make PC<->server links, which is invalid.
    err(client.patch("/api/devices/SW1", json={"type": "pc"}), 422)
    assert ok(client.get("/api/devices/SW1"))["type"] == "switch"


def test_update_pc_with_requires_to_switch_rejected(client):
    ok(client.patch("/api/devices/PC1", json={"requires": "SRV1"}))
    err(client.patch("/api/devices/PC1", json={"type": "switch"}), 422)


@pytest.mark.parametrize("body,status", [
    ({}, 400),
    ({"id": "PCX"}, 422),
    ({"name": 5}, 422),
    ({"ip_address": "nope"}, 422),
    ({"ip_address": "192.168.1.12"}, 409),   # belongs to PC2
    ({"type": "laptop"}, 422),
    ({"speed": 1}, 400),
])
def test_update_device_validation(client, body, status):
    before = ok(client.get("/api/topology"))
    err(client.patch("/api/devices/PC1", json=body), status)
    assert ok(client.get("/api/topology")) == before


def test_update_unknown_device(client):
    err(client.patch("/api/devices/NOPE", json={"name": "x"}), 404)


# -------------------------------------------------------------- delete devices
def test_delete_device_removes_links(client):
    data = ok(client.delete("/api/devices/SW1"))
    assert data["deleted"] == "SW1" and len(data["removed_links"]) == 4
    topo = ok(client.get("/api/topology"))
    assert topo["stats"]["link_count"] == 1 and topo["stats"]["connected"] is False


def test_delete_unknown_device(client):
    err(client.delete("/api/devices/NOPE"), 404)


def test_delete_server_required_explicitly_is_blocked(client):
    ok(client.patch("/api/devices/PC1", json={"requires": ["SRV1"]}))
    e = err(client.delete("/api/devices/SRV1"), 409)
    assert e["details"] == {"required_by": ["PC1"]}
    ok(client.patch("/api/devices/PC1", json={"requires": None}))
    ok(client.delete("/api/devices/SRV1"))


# ------------------------------------------------------------------------ links
def test_list_and_get_link(client):
    assert len(ok(client.get("/api/links"))["links"]) == 5
    link = ok(client.get("/api/links/R1/SW1"))  # reverse order works
    assert link["latency_ms"] == 2.0 and link["id"] == "SW1--R1"


@pytest.mark.parametrize("url", ["/api/links/PC1/R1", "/api/links/PC1/NOPE"])
def test_get_missing_link(client, url):
    err(client.get(url), 404)


def test_create_link(client):
    ok(client.post("/api/devices", json={"id": "SW2", "type": "switch"}), 201)
    link = ok(client.post("/api/links", json={
        "source": "SW2", "target": "R1", "bandwidth_mbps": 100, "latency_ms": 3,
        "attributes": {"cable": "cat6"}}), 201)
    assert link["bandwidth_mbps"] == 100.0 and link["attributes"] == {"cable": "cat6"}
    assert ok(client.get("/api/devices/R1"))["degree"] == 3


@pytest.mark.parametrize("body,status", [
    ({"source": "PC1"}, 400),
    ({"source": "PC1", "target": "NOPE"}, 404),
    ({"source": "PC1", "target": "PC1"}, 422),
    ({"source": "PC1", "target": "PC2"}, 422),                       # pc<->pc not allowed
    ({"source": "PC1", "target": "SRV1"}, 422),
    ({"source": "PC1", "target": "R1", "latency_ms": 0}, 422),
    ({"source": "PC1", "target": "R1", "bandwidth_mbps": "fast"}, 422),
    ({"source": "PC1", "target": "R1", "attributes": {"source": "x"}}, 422),
    ({"source": ["PC1"], "target": "R1"}, 422),
    ({"source": "PC1", "target": "R1", "colour": "blue"}, 400),
])
def test_create_link_validation(client, body, status):
    err(client.post("/api/links", json=body), status)
    assert ok(client.get("/api/topology"))["stats"]["link_count"] == 5


def test_create_duplicate_link(client):
    err(client.post("/api/links", json={"source": "SW1", "target": "PC1"}), 409)


def test_update_link(client):
    link = ok(client.patch("/api/links/SW1/R1", json={"latency_ms": 9, "attributes": {"vlan": 10}}))
    assert link["latency_ms"] == 9.0 and link["bandwidth_mbps"] == 1000.0
    assert link["attributes"] == {"vlan": 10}
    assert ok(client.get("/api/links/SW1/R1"))["latency_ms"] == 9.0


@pytest.mark.parametrize("body,status", [({}, 400), ({"latency_ms": -1}, 422), ({"source": "X"}, 400)])
def test_update_link_validation(client, body, status):
    err(client.patch("/api/links/SW1/R1", json=body), status)
    assert ok(client.get("/api/links/SW1/R1"))["latency_ms"] == 2.0


def test_update_missing_link(client):
    err(client.patch("/api/links/PC1/R1", json={"latency_ms": 1}), 404)


def test_delete_link(client):
    assert ok(client.delete("/api/links/R1/SW1"))["deleted"] == "SW1--R1"
    err(client.delete("/api/links/R1/SW1"), 404)
    assert ok(client.get("/api/topology"))["stats"]["connected"] is False
