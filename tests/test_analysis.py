import math

import pytest

from netcascade import (
    NetworkGraph,
    ValidationError,
    all_shortest_paths,
    bridges,
    can_reach,
    connected_components,
    count_simple_paths,
    get_topology,
    is_connected,
    isolated_devices,
    reachability_matrix,
    reachable_from,
    shortest_path,
    shortest_path_length,
    unreachable_pairs,
)


@pytest.fixture
def basic():
    return get_topology("basic")


@pytest.fixture
def redundant():
    return get_topology("redundant")


# ------------------------------------------------------------ connectivity
def test_empty_graph_is_connected():
    assert is_connected(NetworkGraph())


def test_disconnected_after_removing_router(basic):
    basic.remove_device("R1")
    assert not is_connected(basic)
    comps = connected_components(basic)
    assert comps[0] == {"PC1", "PC2", "PC3", "SW1"}
    assert comps[1] == {"SRV1"}
    assert isolated_devices(basic) == ["SRV1"]


def test_reachable_from(basic):
    assert reachable_from(basic, "PC1") == {"PC2", "PC3", "SW1", "R1", "SRV1"}


def test_can_reach(basic):
    assert can_reach(basic, "PC1", "SRV1")
    basic.remove_link("SW1", "R1")
    assert not can_reach(basic, "PC1", "SRV1")
    assert can_reach(basic, "PC1", "PC2")


def test_unknown_device_in_analysis(basic):
    with pytest.raises(ValidationError):
        can_reach(basic, "PC1", "NOPE")
    with pytest.raises(ValidationError):
        reachable_from(basic, "NOPE")
    with pytest.raises(ValidationError):
        shortest_path(basic, "NOPE", "PC1")


def test_reachability_matrix_pc_to_server(basic):
    matrix = reachability_matrix(basic)
    assert matrix == {f"PC{i}": {"SRV1": True} for i in range(1, 4)}
    assert unreachable_pairs(basic) == []

    basic.remove_device("SW1")
    assert unreachable_pairs(basic) == [("PC1", "SRV1"), ("PC2", "SRV1"), ("PC3", "SRV1")]


def test_redundant_survives_any_single_infrastructure_link_loss(redundant):
    infra = {"SW1", "SW2", "R1", "R2", "SRV1", "SRV2"}
    for link in redundant.links():
        if {link.source, link.target} <= infra:
            copy = redundant.copy()
            copy.remove_link(link.source, link.target)
            assert unreachable_pairs(copy) == [], f"losing {link.source}-{link.target} broke it"


def test_redundant_survives_any_router_loss(redundant):
    for router in ("R1", "R2"):
        copy = redundant.copy()
        copy.remove_device(router)
        assert unreachable_pairs(copy) == []


def test_bridges(basic, redundant):
    assert ("R1", "SW1") in bridges(basic)
    assert all(link[0].startswith("PC") for link in bridges(redundant))


# ----------------------------------------------------------- shortest path
def test_shortest_path_hops(basic):
    result = shortest_path(basic, "PC1", "SRV1")
    assert result.path == ["PC1", "SW1", "R1", "SRV1"]
    assert result.hops == 3
    assert result.latency_ms == 8.0
    assert result.reachable


def test_shortest_path_to_self(basic):
    result = shortest_path(basic, "PC1", "PC1")
    assert result.path == ["PC1"] and result.hops == 0 and result.latency_ms == 0


def test_shortest_path_unreachable(basic):
    basic.remove_device("R1")
    result = shortest_path(basic, "PC1", "SRV1")
    assert not result.reachable
    assert result.path == []
    assert math.isinf(result.latency_ms)
    assert math.isinf(shortest_path_length(basic, "PC1", "SRV1"))


def test_latency_metric_prefers_faster_longer_path():
    n = NetworkGraph()
    for d in ("R1", "R2", "R3"):
        n.add_device(d, "router")
    n.add_link("R1", "R3", latency_ms=50)        # 1 hop, slow
    n.add_link("R1", "R2", latency_ms=5)
    n.add_link("R2", "R3", latency_ms=5)         # 2 hops, fast
    assert shortest_path(n, "R1", "R3").path == ["R1", "R3"]
    fast = shortest_path(n, "R1", "R3", metric="latency")
    assert fast.path == ["R1", "R2", "R3"]
    assert fast.latency_ms == 10.0
    assert shortest_path_length(n, "R1", "R3", metric="latency") == 10.0
    assert shortest_path_length(n, "R1", "R3") == 1


def test_unknown_metric(basic):
    with pytest.raises(ValidationError, match="Unknown metric"):
        shortest_path(basic, "PC1", "SRV1", metric="cost")


def test_all_shortest_paths_shows_redundancy(redundant):
    paths = all_shortest_paths(redundant, "PC1", "SRV2")
    assert ["PC1", "SW1", "R1", "SRV2"] in paths
    assert ["PC1", "SW1", "R2", "SRV2"] in paths
    assert all(len(p) == 4 for p in paths)


def test_all_shortest_paths_unreachable(basic):
    basic.remove_device("SW1")
    assert all_shortest_paths(basic, "PC1", "SRV1") == []


def test_count_simple_paths(basic, redundant):
    assert count_simple_paths(basic, "PC1", "SRV1") == 1
    assert count_simple_paths(redundant, "PC1", "SRV1") > 1
    assert count_simple_paths(basic, "PC1", "PC1") == 1


def test_campus_shortest_path_crosses_core():
    net = get_topology("campus")
    result = shortest_path(net, "PC-A1-1", "SRV-WEB")
    assert result.hops == 5
    assert result.path[0] == "PC-A1-1" and result.path[-1] == "SRV-WEB"
    assert any(n.startswith("CORE") for n in result.path)
