import pytest

from netcascade import DeviceType, NetworkGraph, ValidationError


@pytest.fixture
def net():
    n = NetworkGraph("t")
    n.add_device("PC1", "pc", ip_address="192.168.0.10")
    n.add_device("SW1", DeviceType.SWITCH)
    n.add_device("R1", "Router")
    n.add_device("SRV1", "server", ip_address="10.0.0.1")
    return n


# ----------------------------------------------------------------- devices
def test_add_device_stores_attributes(net):
    dev = net.get_device("PC1")
    assert dev.type is DeviceType.PC
    assert dev.ip_address == "192.168.0.10"
    assert dev.name == "PC1"
    assert net.device_count == 4


def test_device_type_parsing_is_case_insensitive(net):
    assert net.get_device("R1").type is DeviceType.ROUTER


def test_custom_attributes_kept():
    n = NetworkGraph()
    n.add_device("S", "server", role="db", rack=4)
    assert n.get_device("S").attributes == {"role": "db", "rack": 4}


def test_filter_devices_by_type(net):
    assert net.device_ids("pc") == ["PC1"]
    assert net.device_ids(DeviceType.SERVER) == ["SRV1"]


@pytest.mark.parametrize("bad_id", ["", "   ", None, 42, "has space", "-leading", "x" * 65])
def test_invalid_device_id_rejected(bad_id):
    with pytest.raises(ValidationError):
        NetworkGraph().add_device(bad_id, "pc")


@pytest.mark.parametrize("bad_type", ["laptop", "", None, 3])
def test_invalid_device_type_rejected(bad_type):
    with pytest.raises(ValidationError, match="Unknown device type"):
        NetworkGraph().add_device("X", bad_type)


@pytest.mark.parametrize("bad_ip", ["999.1.1.1", "abc", "10.0.0", 1234])
def test_invalid_ip_rejected(bad_ip):
    with pytest.raises(ValidationError):
        NetworkGraph().add_device("X", "pc", ip_address=bad_ip)


def test_ipv6_accepted_and_normalised():
    n = NetworkGraph()
    n.add_device("X", "pc", ip_address="2001:DB8::0001")
    assert n.get_device("X").ip_address == "2001:db8::1"


def test_duplicate_device_rejected(net):
    with pytest.raises(ValidationError, match="already exists"):
        net.add_device("PC1", "pc")


def test_duplicate_ip_rejected(net):
    with pytest.raises(ValidationError, match="already assigned"):
        net.add_device("PC2", "pc", ip_address="192.168.0.10")


def test_remove_device_removes_its_links(net):
    net.add_link("PC1", "SW1")
    net.remove_device("SW1")
    assert "SW1" not in net
    assert net.link_count == 0


def test_unknown_device_lookup(net):
    with pytest.raises(ValidationError, match="Unknown device"):
        net.get_device("nope")
    with pytest.raises(ValidationError):
        net.remove_device("nope")


# ------------------------------------------------------------------- links
def test_add_link(net):
    link = net.add_link("PC1", "SW1", bandwidth_mbps=100, latency_ms=2)
    assert net.has_link("SW1", "PC1")  # undirected
    assert link.bandwidth_mbps == 100.0
    assert net.get_link("SW1", "PC1").latency_ms == 2.0
    assert net.neighbors("SW1") == ["PC1"]


def test_link_to_unknown_device(net):
    with pytest.raises(ValidationError, match="Unknown device"):
        net.add_link("PC1", "GHOST")


def test_self_loop_rejected(net):
    with pytest.raises(ValidationError, match="itself"):
        net.add_link("R1", "R1")


def test_duplicate_link_rejected_in_either_direction(net):
    net.add_link("PC1", "SW1")
    with pytest.raises(ValidationError, match="already exists"):
        net.add_link("SW1", "PC1")


@pytest.mark.parametrize("a,b", [("PC1", "PC2"), ("PC1", "SRV1"), ("SRV1", "SRV2")])
def test_end_devices_cannot_link_directly(a, b):
    n = NetworkGraph()
    for d, t in [("PC1", "pc"), ("PC2", "pc"), ("SRV1", "server"), ("SRV2", "server")]:
        n.add_device(d, t)
    with pytest.raises(ValidationError, match="cannot be connected directly"):
        n.add_link(a, b)


@pytest.mark.parametrize("a,b", [("PC1", "SW1"), ("PC1", "R1"), ("SRV1", "SW1"),
                                 ("SRV1", "R1"), ("SW1", "R1")])
def test_allowed_connections(net, a, b):
    net.add_link(a, b)
    assert net.has_link(a, b)


def test_switch_switch_and_router_router_allowed():
    n = NetworkGraph()
    for d, t in [("S1", "switch"), ("S2", "switch"), ("R1", "router"), ("R2", "router")]:
        n.add_device(d, t)
    n.add_link("S1", "S2")
    n.add_link("R1", "R2")
    assert n.link_count == 2


@pytest.mark.parametrize("field", ["bandwidth_mbps", "latency_ms"])
@pytest.mark.parametrize("value", [0, -5, "fast", None, True, float("nan"), float("inf")])
def test_invalid_link_metrics_rejected(net, field, value):
    with pytest.raises(ValidationError, match=field):
        net.add_link("PC1", "SW1", **{field: value})
    assert net.link_count == 0


def test_remove_link(net):
    net.add_link("PC1", "SW1")
    net.remove_link("SW1", "PC1")
    assert net.link_count == 0
    with pytest.raises(ValidationError, match="does not exist"):
        net.remove_link("PC1", "SW1")


# ---------------------------------------------------- copy / serialisation
def test_copy_is_independent(net):
    net.add_link("PC1", "SW1")
    clone = net.copy()
    clone.remove_device("SW1")
    clone.get_device("PC1").attributes["x"] = 1
    assert "SW1" in net and net.link_count == 1
    assert net.get_device("PC1").attributes == {}


def test_dict_round_trip(net):
    net.add_link("PC1", "SW1", latency_ms=3)
    net.add_link("SW1", "R1")
    rebuilt = NetworkGraph.from_dict(net.to_dict())
    assert rebuilt.to_dict() == net.to_dict()


@pytest.mark.parametrize("data,msg", [
    ("not a dict", "must be a dict"),
    ({"devices": "x"}, "must be lists"),
    ({"devices": [{"id": "A"}]}, "'id' and 'type'"),
    ({"devices": [{"id": "A", "type": "pc"}], "links": [{"source": "A"}]}, "'source' and 'target'"),
    ({"devices": [{"id": "A", "type": "pc"}, {"id": "B", "type": "pc"}],
      "links": [{"source": "A", "target": "B"}]}, "cannot be connected"),
])
def test_from_dict_validates(data, msg):
    with pytest.raises(ValidationError, match=msg):
        NetworkGraph.from_dict(data)


def test_returned_models_do_not_mutate_graph():
    n = NetworkGraph()
    n.add_device("S", "server", role="db")
    n.get_device("S").attributes["role"] = "hacked"
    assert n.get_device("S").attributes["role"] == "db"
