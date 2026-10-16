"""NetCascade: network dependency graph for failure impact analysis (Phase 1 core engine)."""

from .analysis import (
    PathResult,
    all_shortest_paths,
    articulation_points,
    bridges,
    can_reach,
    connected_components,
    count_simple_paths,
    is_connected,
    isolated_devices,
    reachability_matrix,
    reachable_from,
    shortest_path,
    shortest_path_length,
    unreachable_pairs,
)
from .graph import NetworkGraph
from .models import Device, DeviceType, Link
from .topologies import (
    basic_topology,
    campus_topology,
    get_topology,
    list_topologies,
    redundant_topology,
)
from .validation import ValidationError
from . import evaluation  # noqa: E402  (Phase 7: evaluation metrics)

__all__ = [
    "Device", "DeviceType", "Link", "NetworkGraph", "ValidationError", "PathResult",
    "basic_topology", "redundant_topology", "campus_topology", "get_topology", "list_topologies",
    "is_connected", "connected_components", "reachable_from", "can_reach", "isolated_devices",
    "reachability_matrix", "unreachable_pairs", "articulation_points", "bridges",
    "shortest_path", "all_shortest_paths", "shortest_path_length", "count_simple_paths",
]

__version__ = "0.1.0"

# Phase 2: failure simulation and impact analysis
from .simulation import (  # noqa: E402
    FailureResult,
    Severity,
    classify_severity,
    impact_score,
    rank_devices,
    rank_links,
    required_pairs,
    simulate_device_failure,
    simulate_devices_failure,
    simulate_link_failure,
    single_points_of_failure,
)

__all__ += [
    "FailureResult", "Severity", "classify_severity", "impact_score", "rank_devices", "rank_links",
    "required_pairs", "simulate_device_failure", "simulate_devices_failure", "simulate_link_failure", "single_points_of_failure",
]
