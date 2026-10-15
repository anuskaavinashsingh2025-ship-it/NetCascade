"""Failure simulation, impact scoring and criticality ranking (Phase 2).

Every simulation works on ``net.copy()``; the original topology is never changed.

Clients are PCs. By default each PC needs to reach every server. To give a PC
specific destinations, set a ``requires`` attribute when adding it, e.g.
``net.add_device("PC1", "pc", requires=["SRV1"])``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

import networkx as nx

from .graph import NetworkGraph
from .models import DeviceType
from .validation import ValidationError

ComponentKind = Literal["device", "link"]
Pair = tuple[str, str]


class Severity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


def classify_severity(score: float) -> Severity:
    """Low 0-24.99, Medium 25-49.99, High 50-74.99, Critical 75-100."""
    if isinstance(score, bool) or not isinstance(score, (int, float)) or math.isnan(score):
        raise ValidationError(f"Impact score must be a number, got {score!r}")
    if score < 0 or score > 100:
        raise ValidationError(f"Impact score must be between 0 and 100, got {score}")
    if score < 25:
        return Severity.LOW
    if score < 50:
        return Severity.MEDIUM
    if score < 75:
        return Severity.HIGH
    return Severity.CRITICAL


def impact_score(affected_clients: int, total_clients: int) -> float:
    """Affected clients / total clients x 100, rounded to 2 decimals (0 if no clients)."""
    if total_clients < 0 or affected_clients < 0 or affected_clients > total_clients:
        raise ValidationError(
            f"Invalid client counts: affected={affected_clients}, total={total_clients}"
        )
    if total_clients == 0:
        return 0.0
    return round(affected_clients / total_clients * 100, 2)


@dataclass(frozen=True)
class FailureResult:
    """Outcome of one simulated failure."""

    kind: ComponentKind
    component: str | Pair            # device id, or (source, target) for a link
    total_clients: int
    affected_clients: list[str]      # PCs that lost at least one required server
    lost_pairs: list[Pair]           # (pc, server) pairs that lost connectivity
    rerouted_pairs: dict[Pair, list[str]] = field(default_factory=dict)  # pair -> alternate path
    unaffected_clients: list[str] = field(default_factory=list)
    disconnected_devices: list[str] = field(default_factory=list)  # cut off from the largest part
    impact_score: float = 0.0
    severity: Severity = Severity.LOW

    @property
    def label(self) -> str:
        return self.component if self.kind == "device" else f"{self.component[0]}--{self.component[1]}"

    @property
    def is_single_point_of_failure(self) -> bool:
        """True when the failure cuts off a client that is itself still working.

        A failed PC losing its own connectivity doesn't count; a switch, router,
        server or link that cuts off other clients does.
        """
        survivors = [c for c in self.affected_clients if not (self.kind == "device" and c == self.component)]
        return bool(survivors)

    def summary(self) -> str:
        lines = [
            f"Failure of {self.kind} {self.label}",
            f"  Impact score: {self.impact_score:.2f}%  ({len(self.affected_clients)}/{self.total_clients} clients)",
            f"  Severity:     {self.severity.value}",
            f"  Affected clients: {', '.join(self.affected_clients) or 'none'}",
            f"  Lost pairs:       {', '.join(f'{a}->{b}' for a, b in self.lost_pairs) or 'none'}",
        ]
        if self.rerouted_pairs:
            lines.append("  Rerouted via alternate path:")
            for (a, b), path in self.rerouted_pairs.items():
                lines.append(f"    {a}->{b}: {' -> '.join(path)}")
        if self.disconnected_devices:
            lines.append(f"  Cut off from main network: {', '.join(self.disconnected_devices)}")
        lines.append(f"  Single point of failure: {'YES' if self.is_single_point_of_failure else 'no'}")
        return "\n".join(lines)


# --------------------------------------------------------------- requirements
def required_pairs(net: NetworkGraph) -> list[Pair]:
    """(pc, server) pairs that must stay connected, from each PC's ``requires`` attribute."""
    servers = net.device_ids(DeviceType.SERVER)
    pairs: list[Pair] = []
    for pc in net.devices(DeviceType.PC):
        requires = pc.attributes.get("requires")
        if requires is None:
            targets = servers
        else:
            if isinstance(requires, str):
                requires = [requires]
            targets = list(requires)
            for t in targets:
                if t not in net or net.get_device(t).type is not DeviceType.SERVER:
                    raise ValidationError(f"{pc.id} requires {t!r}, which is not a server in the network")
        pairs.extend((pc.id, s) for s in targets)
    return pairs


# ----------------------------------------------------------------- simulation
def simulate_device_failure(net: NetworkGraph, device_id: str) -> FailureResult:
    """Remove a device and all its links from a copy of the graph and measure the impact."""
    if not isinstance(device_id, str) or not net.has_device(device_id):
        raise ValidationError(f"Unknown device {device_id!r}")
    failed = net.copy()
    failed.remove_device(device_id)
    return _evaluate(net, failed, "device", device_id, failed_nodes={device_id})


def simulate_link_failure(net: NetworkGraph, source: str, target: str) -> FailureResult:
    """Remove only the given link from a copy of the graph and measure the impact."""
    for d in (source, target):
        if not isinstance(d, str) or not net.has_device(d):
            raise ValidationError(f"Unknown device {d!r}")
    if not net.has_link(source, target):
        raise ValidationError(f"Link {source!r} <-> {target!r} does not exist")
    failed = net.copy()
    failed.remove_link(source, target)
    return _evaluate(net, failed, "link", (source, target), failed_edge=frozenset((source, target)))


def _evaluate(
    original: NetworkGraph,
    failed: NetworkGraph,
    kind: ComponentKind,
    component: str | Pair,
    failed_nodes: set[str] = frozenset(),
    failed_edge: frozenset[str] | None = None,
) -> FailureResult:
    pairs = required_pairs(original)
    clients = original.device_ids(DeviceType.PC)
    g_before, g_after = original.graph, failed.graph

    lost: list[Pair] = []
    rerouted: dict[Pair, list[str]] = {}
    for pc, srv in pairs:
        if not nx.has_path(g_before, pc, srv):
            continue  # already broken before the failure, not caused by it
        if pc in failed_nodes or srv in failed_nodes or not nx.has_path(g_after, pc, srv):
            lost.append((pc, srv))
            continue
        old_path = nx.shortest_path(g_before, pc, srv)
        if _path_uses(old_path, failed_nodes, failed_edge):
            rerouted[(pc, srv)] = nx.shortest_path(g_after, pc, srv)

    affected = sorted({pc for pc, _ in lost})
    unaffected = sorted(set(clients) - set(affected))
    score = impact_score(len(affected), len(clients))
    return FailureResult(
        kind=kind,
        component=component,
        total_clients=len(clients),
        affected_clients=affected,
        lost_pairs=sorted(lost),
        rerouted_pairs=dict(sorted(rerouted.items())),
        unaffected_clients=unaffected,
        disconnected_devices=_cut_off(g_before, g_after),
        impact_score=score,
        severity=classify_severity(score),
    )


def _path_uses(path: list[str], nodes: set[str], edge: frozenset[str] | None) -> bool:
    if any(n in nodes for n in path):
        return True
    return edge is not None and any(frozenset(e) == edge for e in zip(path, path[1:]))


def _cut_off(g_before: nx.Graph, g_after: nx.Graph) -> list[str]:
    """Surviving devices no longer in the largest connected part (if the failure split the network)."""
    if g_after.number_of_nodes() == 0:
        return []
    before = nx.number_connected_components(g_before)
    comps = sorted(nx.connected_components(g_after), key=len, reverse=True)
    if len(comps) <= before:
        return []
    return sorted(n for comp in comps[1:] for n in comp)


# ------------------------------------------------------------------- ranking
def _rank_key(r: FailureResult):
    return (-r.impact_score, -len(r.lost_pairs), r.label)


def rank_devices(net: NetworkGraph, device_type: DeviceType | str | None = None) -> list[FailureResult]:
    """Simulate failure of every device (optionally one type) and rank by impact, highest first."""
    results = [simulate_device_failure(net, d) for d in net.device_ids(device_type)]
    return sorted(results, key=_rank_key)


def rank_links(net: NetworkGraph) -> list[FailureResult]:
    """Simulate failure of every link and rank by impact, highest first."""
    results = [simulate_link_failure(net, l.source, l.target) for l in net.links()]
    return sorted(results, key=_rank_key)


def single_points_of_failure(net: NetworkGraph) -> dict[str, list[FailureResult]]:
    """Devices and links whose single failure disconnects a still-working client from a required server."""
    return {
        "devices": [r for r in rank_devices(net) if r.is_single_point_of_failure],
        "links": [r for r in rank_links(net) if r.is_single_point_of_failure],
    }
