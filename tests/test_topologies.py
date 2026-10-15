import pytest

from netcascade import (
    NetworkGraph,
    ValidationError,
    articulation_points,
    get_topology,
    is_connected,
    list_topologies,
)


def test_list_topologies():
    assert list_topologies() == ["basic", "redundant", "campus"]


@pytest.mark.parametrize("name", ["basic", "redundant", "campus"])
def test_topology_is_valid_and_connected(name):
    net = get_topology(name)
    assert net.name == name
    assert is_connected(net)
    # Every topology must survive a round trip through full validation.
    assert NetworkGraph.from_dict(net.to_dict()).to_dict() == net.to_dict()
    for t in ("pc", "switch", "router", "server"):
        assert net.device_ids(t), f"{name} has no {t}"


def test_get_topology_returns_fresh_instances():
    a, b = get_topology("basic"), get_topology("basic")
    a.remove_device("R1")
    assert "R1" in b


def test_get_topology_is_case_insensitive():
    assert get_topology(" Campus ").name == "campus"


def test_unknown_topology():
    with pytest.raises(ValidationError, match="Unknown topology"):
        get_topology("mesh")


def test_basic_matches_proposal_example():
    net = get_topology("basic")
    assert net.device_count == 6 and net.link_count == 5
    assert set(net.neighbors("SW1")) == {"PC1", "PC2", "PC3", "R1"}
    assert set(net.neighbors("R1")) == {"SW1", "SRV1"}


def test_redundancy_levels_differ():
    # Basic: switch and router are single points of failure.
    assert set(articulation_points(get_topology("basic"))) == {"SW1", "R1"}
    # Redundant: no router is a single point of failure.
    redundant_aps = articulation_points(get_topology("redundant"))
    assert not any(d.startswith("R") for d in redundant_aps)
    # Campus: core and distribution layers are fully redundant.
    campus_aps = articulation_points(get_topology("campus"))
    assert not any(d.startswith(("CORE", "DIST", "EDGE")) for d in campus_aps)


def test_campus_size():
    net = get_topology("campus")
    assert len(net.device_ids("pc")) == 8
    assert len(net.device_ids("server")) == 3
    assert len(net.device_ids("router")) == 3
