import pytest

from netcascade import (
    NetworkGraph,
    Severity,
    ValidationError,
    classify_severity,
    get_topology,
    impact_score,
    rank_devices,
    rank_links,
    required_pairs,
    simulate_device_failure,
    simulate_link_failure,
    single_points_of_failure,
)


@pytest.fixture
def basic():
    return get_topology("basic")


@pytest.fixture
def redundant():
    return get_topology("redundant")


@pytest.fixture
def campus():
    return get_topology("campus")


# ------------------------------------------------------- severity & scoring
@pytest.mark.parametrize("score,expected", [
    (0, Severity.LOW), (24.99, Severity.LOW),
    (25, Severity.MEDIUM), (49.99, Severity.MEDIUM),
    (50, Severity.HIGH), (74.99, Severity.HIGH),
    (75, Severity.CRITICAL), (100, Severity.CRITICAL),
])
def test_severity_thresholds(score, expected):
    assert classify_severity(score) is expected


@pytest.mark.parametrize("bad", [-0.01, 100.01, float("nan"), "50", None, True])
def test_severity_rejects_invalid_scores(bad):
    with pytest.raises(ValidationError):
        classify_severity(bad)


@pytest.mark.parametrize("affected,total,expected", [
    (0, 4, 0.0), (1, 4, 25.0), (2, 4, 50.0), (3, 4, 75.0), (4, 4, 100.0),
    (1, 3, 33.33), (2, 3, 66.67), (0, 0, 0.0),
])
def test_impact_score_formula(affected, total, expected):
    assert impact_score(affected, total) == expected


@pytest.mark.parametrize("affected,total", [(5, 4), (-1, 4), (0, -1)])
def test_impact_score_rejects_bad_counts(affected, total):
    with pytest.raises(ValidationError):
        impact_score(affected, total)


# ---------------------------------------------------------- required pairs
def test_default_requirement_is_every_server(redundant):
    pairs = required_pairs(redundant)
    assert len(pairs) == 4 * 2
    assert ("PC1", "SRV2") in pairs


def test_custom_requirements():
    net = get_topology("redundant")
    custom = NetworkGraph.from_dict(net.to_dict())
    custom.remove_device("PC1")
    custom.add_device("PC1", "pc", requires=["SRV1"])
    custom.add_link("PC1", "SW1")
    assert [p for p in required_pairs(custom) if p[0] == "PC1"] == [("PC1", "SRV1")]
    # SRV2 failing doesn't hurt PC1 any more.
    assert "PC1" not in simulate_device_failure(custom, "SRV2").affected_clients


def test_requirement_must_be_a_server(basic):
    basic.add_device("PC9", "pc", requires="SW1")
    with pytest.raises(ValidationError, match="not a server"):
        required_pairs(basic)


# --------------------------------------------------------- device failures
def test_router_failure_in_basic_is_critical(basic):
    r = simulate_device_failure(basic, "R1")
    assert r.kind == "device" and r.component == "R1"
    assert r.affected_clients == ["PC1", "PC2", "PC3"]
    assert r.lost_pairs == [("PC1", "SRV1"), ("PC2", "SRV1"), ("PC3", "SRV1")]
    assert r.impact_score == 100.0 and r.severity is Severity.CRITICAL
    assert r.disconnected_devices == ["SRV1"]
    assert r.is_single_point_of_failure


def test_single_pc_failure_affects_only_itself(basic):
    r = simulate_device_failure(basic, "PC2")
    assert r.affected_clients == ["PC2"]
    assert r.impact_score == 33.33 and r.severity is Severity.MEDIUM
    assert not r.is_single_point_of_failure  # only the failed PC itself is hit


def test_redundant_router_failure_reroutes(redundant):
    r = simulate_device_failure(redundant, "R1")
    assert r.affected_clients == [] and r.lost_pairs == []
    assert r.impact_score == 0.0 and r.severity is Severity.LOW
    assert not r.is_single_point_of_failure
    # PC1's old shortest path to SRV1 went through R1; an alternate exists that avoids it.
    alt = r.rerouted_pairs[("PC1", "SRV1")]
    assert alt[0] == "PC1" and alt[-1] == "SRV1" and "R1" not in alt
    assert r.unaffected_clients == ["PC1", "PC2", "PC3", "PC4"]


def test_redundant_switch_failure_is_high(redundant):
    r = simulate_device_failure(redundant, "SW1")
    assert r.affected_clients == ["PC1", "PC2"]
    assert r.impact_score == 50.0 and r.severity is Severity.HIGH
    assert r.is_single_point_of_failure


def test_campus_access_switch_failure_is_medium(campus):
    r = simulate_device_failure(campus, "ACC-A1")
    assert r.affected_clients == ["PC-A1-1", "PC-A1-2"]
    assert len(r.lost_pairs) == 2 * 3
    assert r.severity is Severity.MEDIUM


def test_campus_core_failure_has_no_impact(campus):
    r = simulate_device_failure(campus, "CORE1")
    assert r.affected_clients == []
    assert r.rerouted_pairs  # paths that used CORE1 now go via CORE2
    assert all("CORE1" not in p for p in r.rerouted_pairs.values())


def test_server_failure_counts_lost_service(redundant):
    r = simulate_device_failure(redundant, "SRV1")
    assert len(r.affected_clients) == 4
    assert {s for _, s in r.lost_pairs} == {"SRV1"}


# ----------------------------------------------------------- link failures
def test_link_failure_removes_only_that_edge(basic):
    r = simulate_link_failure(basic, "SW1", "R1")
    assert r.kind == "link" and r.component == ("SW1", "R1")
    assert r.severity is Severity.CRITICAL
    assert r.disconnected_devices == ["R1", "SRV1"]  # both devices survive, just cut off


def test_access_link_failure(basic):
    r = simulate_link_failure(basic, "PC1", "SW1")
    assert r.affected_clients == ["PC1"]
    assert r.is_single_point_of_failure  # PC1 is still up but lost its only uplink


def test_redundant_link_failure_uses_alternate_path(redundant):
    r = simulate_link_failure(redundant, "SW1", "R1")
    assert r.impact_score == 0.0
    for path in r.rerouted_pairs.values():
        edges = {frozenset(e) for e in zip(path, path[1:])}
        assert frozenset(("SW1", "R1")) not in edges


def test_link_given_in_reverse_order(basic):
    assert simulate_link_failure(basic, "R1", "SW1").impact_score == 100.0


# -------------------------------------------------- disconnected networks
def test_pairs_broken_before_failure_are_not_blamed():
    net = get_topology("basic")
    net.add_device("PC9", "pc")  # isolated from the start
    r = simulate_device_failure(net, "PC1")
    assert r.affected_clients == ["PC1"]  # PC9 was already disconnected
    assert r.total_clients == 4


def test_failure_in_already_split_network():
    net = get_topology("basic")
    net.remove_link("SW1", "R1")
    r = simulate_device_failure(net, "R1")
    assert r.affected_clients == []  # nothing left to lose
    assert r.lost_pairs == []


def test_network_with_no_clients():
    net = NetworkGraph()
    net.add_device("R1", "router")
    net.add_device("SRV1", "server")
    net.add_link("R1", "SRV1")
    r = simulate_device_failure(net, "R1")
    assert r.total_clients == 0 and r.impact_score == 0.0 and r.severity is Severity.LOW


def test_failing_the_only_device():
    net = NetworkGraph()
    net.add_device("PC1", "pc")
    r = simulate_device_failure(net, "PC1")
    assert r.disconnected_devices == []
    assert r.impact_score == 0.0  # no server required, so nothing was lost


# -------------------------------------------------------------- invalid ids
@pytest.mark.parametrize("bad", ["NOPE", "", None, 7])
def test_unknown_device_rejected(basic, bad):
    with pytest.raises(ValidationError, match="Unknown device"):
        simulate_device_failure(basic, bad)


@pytest.mark.parametrize("a,b,msg", [
    ("PC1", "NOPE", "Unknown device"),
    ("NOPE", "SW1", "Unknown device"),
    ("PC1", "R1", "does not exist"),
    ("PC1", "PC2", "does not exist"),
])
def test_invalid_link_rejected(basic, a, b, msg):
    with pytest.raises(ValidationError, match=msg):
        simulate_link_failure(basic, a, b)


# ------------------------------------------------ original graph untouched
@pytest.mark.parametrize("name", ["basic", "redundant", "campus"])
def test_original_graph_is_preserved(name):
    net = get_topology(name)
    before = net.to_dict()
    rank_devices(net)
    rank_links(net)
    single_points_of_failure(net)
    assert net.to_dict() == before


def test_device_failure_does_not_mutate(basic):
    simulate_device_failure(basic, "SW1")
    assert "SW1" in basic and basic.link_count == 5


def test_link_failure_does_not_mutate(basic):
    simulate_link_failure(basic, "SW1", "R1")
    assert basic.has_link("SW1", "R1")


# --------------------------------------------------------- ranking & SPOF
def test_rank_devices_order(basic):
    ranked = rank_devices(basic)
    assert [r.component for r in ranked[:3]] == ["R1", "SRV1", "SW1"]  # 100%, ties by name
    assert ranked[-1].impact_score == 33.33
    scores = [r.impact_score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert len(ranked) == basic.device_count


def test_rank_devices_by_type(redundant):
    ranked = rank_devices(redundant, "router")
    assert {r.component for r in ranked} == {"R1", "R2"}
    assert all(r.impact_score == 0 for r in ranked)


def test_rank_links_covers_every_link(redundant):
    ranked = rank_links(redundant)
    assert len(ranked) == redundant.link_count
    assert ranked[0].impact_score == 25.0
    assert ranked[-1].impact_score == 0.0


def test_spof_basic(basic):
    spof = single_points_of_failure(basic)
    assert {r.component for r in spof["devices"]} == {"R1", "SW1", "SRV1"}
    assert len(spof["links"]) == basic.link_count  # a tree: every link matters


def test_spof_redundant_excludes_routers(redundant):
    spof = single_points_of_failure(redundant)
    devices = {r.component for r in spof["devices"]}
    assert devices == {"SW1", "SW2", "SRV1", "SRV2"}
    assert not any(r.component in {"R1", "R2"} for r in spof["devices"])
    assert {frozenset(r.component) for r in spof["links"]} == {
        frozenset(("PC1", "SW1")), frozenset(("PC2", "SW1")),
        frozenset(("PC3", "SW2")), frozenset(("PC4", "SW2")),
    }


def test_spof_campus_core_is_redundant(campus):
    devices = {r.component for r in single_points_of_failure(campus)["devices"]}
    assert "DC-SW" in devices
    assert not devices & {"CORE1", "CORE2", "EDGE", "DIST-A1", "DIST-A2", "DIST-B1", "DIST-B2"}


def test_summary_text(basic):
    text = simulate_device_failure(basic, "R1").summary()
    assert "100.00%" in text and "Critical" in text and "PC1->SRV1" in text
