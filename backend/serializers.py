"""Convert engine objects to JSON-safe dicts."""

from __future__ import annotations

from typing import Any

import networkx as nx

from netcascade import (
    FailureResult,
    NetworkGraph,
    connected_components,
    is_connected,
    required_pairs,
)


def device_to_dict(net: NetworkGraph, device_id: str, detail: bool = False) -> dict[str, Any]:
    data = net.get_device(device_id).to_dict()
    data["requires"] = data["attributes"].get("requires")
    data["degree"] = len(net.neighbors(device_id))
    if detail:
        data["neighbors"] = sorted(net.neighbors(device_id))
        data["links"] = [link_to_dict(canonical_link(net, device_id, n)) for n in data["neighbors"]]
        data["required_by"] = sorted(pc for pc, srv in required_pairs(net) if srv == device_id)
    return data


def canonical_link(net: NetworkGraph, a: str, b: str):
    """The link between a and b in its stored orientation (same as in net.links())."""
    key = frozenset((a, b))
    return next(link for link in net.links() if link.key == key)


def link_to_dict(link) -> dict[str, Any]:
    data = link.to_dict()
    data["id"] = f"{link.source}--{link.target}"
    return data


def topology_to_dict(net: NetworkGraph, source: str | None, modified: bool) -> dict[str, Any]:
    return {
        "name": net.name,
        "source": source,
        "modified": modified,
        "stats": topology_stats(net),
        "devices": [device_to_dict(net, d) for d in net.device_ids()],
        "links": [link_to_dict(link) for link in net.links()],
    }


def topology_stats(net: NetworkGraph) -> dict[str, Any]:
    counts = {t: len(net.device_ids(t)) for t in ("pc", "switch", "router", "server")}
    return {
        "device_count": net.device_count,
        "link_count": net.link_count,
        "by_type": counts,
        "connected": is_connected(net),
        "component_count": len(connected_components(net)),
    }


def _pair(pc: str, srv: str) -> dict[str, str]:
    return {"client": pc, "server": srv}


def failure_to_dict(net: NetworkGraph, r: FailureResult) -> dict[str, Any]:
    """Serialize a Phase 2 FailureResult. ``net`` is the unfailed topology, used for original paths."""
    g = net.graph

    def original_path(a: str, b: str) -> list[str]:
        try:
            return nx.shortest_path(g, a, b)
        except nx.NetworkXNoPath:
            return []

    component = r.component if r.kind == "device" else {"source": r.component[0], "target": r.component[1]}
    return {
        "kind": r.kind,
        "component": component,
        "label": r.label,
        "impact_score": r.impact_score,
        "severity": r.severity.value,
        "is_single_point_of_failure": r.is_single_point_of_failure,
        "total_clients": r.total_clients,
        "affected_client_count": len(r.affected_clients),
        "affected_clients": r.affected_clients,
        "unaffected_clients": r.unaffected_clients,
        "lost_pairs": [_pair(a, b) for a, b in r.lost_pairs],
        "lost_paths": [
            {**_pair(a, b), "original_path": original_path(a, b)} for a, b in r.lost_pairs
        ],
        "alternate_paths": [
            {**_pair(a, b), "original_path": original_path(a, b), "alternate_path": path}
            for (a, b), path in r.rerouted_pairs.items()
        ],
        "disconnected_devices": r.disconnected_devices,
    }


def ranking_entry(r: FailureResult, rank: int) -> dict[str, Any]:
    component = r.component if r.kind == "device" else {"source": r.component[0], "target": r.component[1]}
    return {
        "rank": rank,
        "kind": r.kind,
        "component": component,
        "label": r.label,
        "impact_score": r.impact_score,
        "severity": r.severity.value,
        "affected_client_count": len(r.affected_clients),
        "lost_pair_count": len(r.lost_pairs),
        "is_single_point_of_failure": r.is_single_point_of_failure,
    }
