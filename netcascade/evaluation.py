"""Evaluation metrics from the proposal's "Planned Results and Evaluation" section.

- Execution time for analysing a failure scenario.
- Single-device vs single-link failures.
- Topologies with and without redundant paths.

Everything is computed with the Phase 2 simulation functions on copies of the
graph; nothing here changes a topology.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass
from typing import Iterable

from .graph import NetworkGraph
from .models import DeviceType
from .simulation import FailureResult, Severity, simulate_device_failure, simulate_link_failure
from .topologies import get_topology
from .validation import ValidationError

SEVERITIES = [s.value for s in Severity]


@dataclass(frozen=True)
class ComponentRecord:
    kind: str                 # "device" or "link"
    label: str                # device id, or "A--B" for a link
    component_type: str       # pc / switch / router / server / link
    impact_score: float
    severity: str
    affected_clients: int
    total_clients: int
    lost_pairs: int
    rerouted_pairs: int
    single_point_of_failure: bool
    execution_ms: float       # median wall-clock time of one simulation


def timed(fn, *args, repeat: int = 5) -> tuple[FailureResult, float]:
    """Run ``fn(*args)`` ``repeat`` times; return the result and the median time in milliseconds."""
    if not isinstance(repeat, int) or repeat < 1:
        raise ValidationError("repeat must be a positive integer")
    times = []
    result = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn(*args)
        times.append((time.perf_counter() - start) * 1000)
    return result, statistics.median(times)


def _record(result: FailureResult, component_type: str, ms: float) -> ComponentRecord:
    return ComponentRecord(
        kind=result.kind,
        label=result.label,
        component_type=component_type,
        impact_score=result.impact_score,
        severity=result.severity.value,
        affected_clients=len(result.affected_clients),
        total_clients=result.total_clients,
        lost_pairs=len(result.lost_pairs),
        rerouted_pairs=len(result.rerouted_pairs),
        single_point_of_failure=result.is_single_point_of_failure,
        execution_ms=round(ms, 4),
    )


def component_records(net: NetworkGraph, repeat: int = 5) -> list[ComponentRecord]:
    """Simulate (and time) the failure of every device and every link."""
    records = []
    for dev in net.devices():
        result, ms = timed(simulate_device_failure, net, dev.id, repeat=repeat)
        records.append(_record(result, dev.type.value, ms))
    for link in net.links():
        result, ms = timed(simulate_link_failure, net, link.source, link.target, repeat=repeat)
        records.append(_record(result, "link", ms))
    return records


def failure_stats(records: Iterable[ComponentRecord]) -> dict:
    recs = list(records)
    if not recs:
        return {"count": 0, "mean_impact": 0.0, "median_impact": 0.0, "max_impact": 0.0,
                "severity_counts": {s: 0 for s in SEVERITIES}, "single_points_of_failure": 0,
                "spof_share": 0.0, "mean_lost_pairs": 0.0, "mean_ms": 0.0, "max_ms": 0.0}
    impacts = [r.impact_score for r in recs]
    spof = sum(r.single_point_of_failure for r in recs)
    return {
        "count": len(recs),
        "mean_impact": round(statistics.fmean(impacts), 2),
        "median_impact": round(statistics.median(impacts), 2),
        "max_impact": round(max(impacts), 2),
        "severity_counts": {s: sum(r.severity == s for r in recs) for s in SEVERITIES},
        "single_points_of_failure": spof,
        "spof_share": round(spof / len(recs) * 100, 2),
        "mean_lost_pairs": round(statistics.fmean(r.lost_pairs for r in recs), 2),
        "mean_ms": round(statistics.fmean(r.execution_ms for r in recs), 4),
        "max_ms": round(max(r.execution_ms for r in recs), 4),
    }


def evaluate_topology(net: NetworkGraph, repeat: int = 5) -> dict:
    """Resilience and timing summary for one topology."""
    records = component_records(net, repeat=repeat)
    devices = [r for r in records if r.kind == "device"]
    links = [r for r in records if r.kind == "link"]
    start = time.perf_counter()
    for dev in net.devices():                      # one full criticality pass, timed once
        simulate_device_failure(net, dev.id)
    for link in net.links():
        simulate_link_failure(net, link.source, link.target)
    full_pass_ms = (time.perf_counter() - start) * 1000
    overall = failure_stats(records)
    return {
        "name": net.name,
        "devices": net.device_count,
        "links": net.link_count,
        "clients": len(net.device_ids(DeviceType.PC)),
        "servers": len(net.device_ids(DeviceType.SERVER)),
        "device_failures": failure_stats(devices),
        "link_failures": failure_stats(links),
        "all_failures": overall,
        "single_points_of_failure": {
            "devices": [r.label for r in devices if r.single_point_of_failure],
            "links": [r.label for r in links if r.single_point_of_failure],
        },
        "timing": {
            "repeat": repeat,
            "mean_ms": overall["mean_ms"],
            "median_ms": round(statistics.median(r.execution_ms for r in records), 4) if records else 0.0,
            "max_ms": overall["max_ms"],
            "full_ranking_ms": round(full_pass_ms, 3),
        },
        "records": [asdict(r) for r in records],
    }


def _key(record: dict) -> tuple[str, frozenset | str]:
    if record["kind"] == "link":
        return ("link", frozenset(record["label"].split("--")))
    return ("device", record["label"])


def compare_topologies(names: Iterable[str] = ("basic", "redundant", "campus"), repeat: int = 5) -> dict:
    """Evaluate several predefined topologies and line up failures of components they share."""
    names = list(names)
    if not names:
        raise ValidationError("At least one topology is required")
    summaries = [evaluate_topology(get_topology(n), repeat=repeat) for n in names]

    shared: dict[tuple, dict] = {}
    for s in summaries:
        for rec in s["records"]:
            entry = shared.setdefault(_key(rec), {"kind": rec["kind"], "label": rec["label"],
                                                   "component_type": rec["component_type"], "impact": {}})
            entry["impact"][s["name"]] = {"impact_score": rec["impact_score"], "severity": rec["severity"],
                                          "single_point_of_failure": rec["single_point_of_failure"]}
    common = [e for e in shared.values() if len(e["impact"]) >= 2]
    common.sort(key=lambda e: (e["kind"] != "device", e["label"]))
    return {"topologies": summaries, "common_failures": common}
