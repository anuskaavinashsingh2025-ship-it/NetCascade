"""Connectivity and shortest-path analysis on a NetworkGraph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import networkx as nx

from .graph import NetworkGraph
from .models import DeviceType
from .validation import ValidationError

Metric = Literal["hops", "latency"]


@dataclass(frozen=True)
class PathResult:
    source: str
    target: str
    path: list[str]
    hops: int
    latency_ms: float

    @property
    def reachable(self) -> bool:
        return bool(self.path)


# ------------------------------------------------------------------ connectivity
def is_connected(net: NetworkGraph) -> bool:
    """True if every device can reach every other device. Empty graphs count as connected."""
    if net.device_count == 0:
        return True
    return nx.is_connected(net.graph)


def connected_components(net: NetworkGraph) -> list[set[str]]:
    """Connected groups of devices, largest first."""
    return sorted((set(c) for c in nx.connected_components(net.graph)), key=len, reverse=True)


def reachable_from(net: NetworkGraph, device_id: str) -> set[str]:
    """All devices reachable from ``device_id`` (excluding itself)."""
    _require(net, device_id)
    return nx.node_connected_component(net.graph, device_id) - {device_id}


def can_reach(net: NetworkGraph, source: str, target: str) -> bool:
    _require(net, source)
    _require(net, target)
    return nx.has_path(net.graph, source, target)


def isolated_devices(net: NetworkGraph) -> list[str]:
    """Devices with no links at all."""
    return sorted(nx.isolates(net.graph))


def reachability_matrix(
    net: NetworkGraph,
    sources: DeviceType | str = DeviceType.PC,
    targets: DeviceType | str = DeviceType.SERVER,
) -> dict[str, dict[str, bool]]:
    """For each source-type device, which target-type devices it can reach.

    Defaults to PC -> server, the main "can users reach services" question.
    """
    component_of = {}
    for idx, comp in enumerate(nx.connected_components(net.graph)):
        for node in comp:
            component_of[node] = idx
    src_ids = net.device_ids(sources)
    dst_ids = net.device_ids(targets)
    return {
        s: {t: s != t and component_of[s] == component_of[t] for t in dst_ids} for s in src_ids
    }


def unreachable_pairs(
    net: NetworkGraph,
    sources: DeviceType | str = DeviceType.PC,
    targets: DeviceType | str = DeviceType.SERVER,
) -> list[tuple[str, str]]:
    matrix = reachability_matrix(net, sources, targets)
    return [(s, t) for s, row in matrix.items() for t, ok in row.items() if not ok and s != t]


def articulation_points(net: NetworkGraph) -> list[str]:
    """Devices whose removal disconnects part of the network (single points of failure)."""
    return sorted(nx.articulation_points(net.graph))


def bridges(net: NetworkGraph) -> list[tuple[str, str]]:
    """Links whose removal disconnects part of the network."""
    return sorted(tuple(sorted(e)) for e in nx.bridges(net.graph))


# ------------------------------------------------------------------ shortest path
def shortest_path(
    net: NetworkGraph, source: str, target: str, metric: Metric = "hops"
) -> PathResult:
    """Shortest path between two devices.

    ``metric="hops"`` minimises link count; ``metric="latency"`` minimises total
    ``latency_ms`` (Dijkstra). Returns a PathResult with an empty path if the
    target is unreachable.
    """
    _require(net, source)
    _require(net, target)
    weight = _weight(metric)
    try:
        path = nx.shortest_path(net.graph, source, target, weight=weight)
    except nx.NetworkXNoPath:
        return PathResult(source, target, [], 0, float("inf"))
    return PathResult(source, target, path, len(path) - 1, path_latency(net, path))


def all_shortest_paths(
    net: NetworkGraph, source: str, target: str, metric: Metric = "hops"
) -> list[list[str]]:
    """Every equally-short path (useful to see redundancy)."""
    _require(net, source)
    _require(net, target)
    try:
        return sorted(nx.all_shortest_paths(net.graph, source, target, weight=_weight(metric)))
    except nx.NetworkXNoPath:
        return []


def shortest_path_length(
    net: NetworkGraph, source: str, target: str, metric: Metric = "hops"
) -> float:
    """Path length in hops or ms; ``inf`` if unreachable."""
    result = shortest_path(net, source, target, metric)
    if not result.reachable:
        return float("inf")
    return result.hops if metric == "hops" else result.latency_ms


def count_simple_paths(net: NetworkGraph, source: str, target: str, cutoff: int | None = None) -> int:
    """Number of loop-free paths between two devices (a measure of redundancy)."""
    _require(net, source)
    _require(net, target)
    if source == target:
        return 1
    return sum(1 for _ in nx.all_simple_paths(net.graph, source, target, cutoff=cutoff))


def path_latency(net: NetworkGraph, path: list[str]) -> float:
    return sum(net.graph.edges[u, v]["latency_ms"] for u, v in zip(path, path[1:]))


def _weight(metric: str) -> str | None:
    if metric == "hops":
        return None
    if metric == "latency":
        return "latency_ms"
    raise ValidationError(f"Unknown metric {metric!r}. Use 'hops' or 'latency'")


def _require(net: NetworkGraph, device_id: str) -> None:
    if not net.has_device(device_id):
        raise ValidationError(f"Unknown device {device_id!r}")
