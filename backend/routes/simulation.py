"""Failure simulation, scenario comparison and simulation reset (Phase 2 functions, on copies)."""

from __future__ import annotations

import time
from typing import Any

from flask import Blueprint

from netcascade import FailureResult, NetworkGraph, simulate_device_failure, simulate_link_failure

from ..errors import ApiError, json_body, ok, require_fields
from ..serializers import failure_to_dict
from ..store import get_store

bp = Blueprint("simulation", __name__)


def _string(data: dict, field: str) -> str:
    value = data[field]
    if not isinstance(value, str) or not value:
        raise ApiError(f"'{field}' must be a non-empty string", 422)
    return value


def _run(net: NetworkGraph, scenario: dict[str, Any]) -> FailureResult:
    """Run one scenario: {"kind": "device", "device_id": ...} or {"kind": "link", "source": ..., "target": ...}."""
    if not isinstance(scenario, dict):
        raise ApiError("Each scenario must be a JSON object", 400)
    kind = scenario.get("kind")
    if kind == "device":
        if "device_id" not in scenario and "id" in scenario:
            scenario = {**scenario, "device_id": scenario["id"]}
        require_fields(scenario, "device_id")
        return simulate_device_failure(net, _string(scenario, "device_id"))
    if kind == "link":
        require_fields(scenario, "source", "target")
        return simulate_link_failure(net, _string(scenario, "source"), _string(scenario, "target"))
    raise ApiError("'kind' must be 'device' or 'link'", 422)


def timed_run(net: NetworkGraph, scenario: dict[str, Any]) -> tuple[FailureResult, float]:
    """Run a scenario and measure how long the analysis took, in milliseconds."""
    start = time.perf_counter()
    result = _run(net, scenario)
    return result, round((time.perf_counter() - start) * 1000, 4)


def _record(result: FailureResult, ms: float) -> dict[str, Any]:
    store = get_store()
    with store.lock:
        payload = {**failure_to_dict(store.network, result), "execution_ms": ms}
        store.simulation = payload
    return payload


@bp.post("/simulate/device")
def simulate_device():
    data = json_body()
    return ok(_record(*timed_run(get_store().network, {**data, "kind": "device"})))


@bp.post("/simulate/link")
def simulate_link():
    data = json_body()
    return ok(_record(*timed_run(get_store().network, {**data, "kind": "link"})))


@bp.get("/simulation")
def current_simulation():
    sim = get_store().simulation
    return ok({"active": sim is not None, "result": sim})


@bp.post("/simulation/reset")
def reset_simulation():
    store = get_store()
    store.reset_simulation()
    return ok({"active": False, "result": None, "device_count": store.network.device_count,
               "link_count": store.network.link_count})


@bp.post("/simulate/compare")
def compare():
    data = json_body()
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 2:
        raise ApiError("'scenarios' must be a list of exactly two scenarios", 400)
    net = get_store().network
    (a, ms_a), (b, ms_b) = (timed_run(net, s) for s in scenarios)
    ra = {**failure_to_dict(net, a), "execution_ms": ms_a}
    rb = {**failure_to_dict(net, b), "execution_ms": ms_b}

    key_a, key_b = (a.impact_score, len(a.lost_pairs)), (b.impact_score, len(b.lost_pairs))
    worse = "A" if key_a > key_b else "B" if key_b > key_a else "equal"
    affected_a, affected_b = set(a.affected_clients), set(b.affected_clients)
    lost_a, lost_b = set(a.lost_pairs), set(b.lost_pairs)
    return ok({
        "scenarios": {"A": ra, "B": rb},
        "comparison": {
            "higher_impact": worse,
            "impact_score_difference": round(b.impact_score - a.impact_score, 2),
            "severity": {"A": a.severity.value, "B": b.severity.value},
            "affected_client_count": {"A": len(affected_a), "B": len(affected_b)},
            "lost_pair_count": {"A": len(lost_a), "B": len(lost_b)},
            "rerouted_pair_count": {"A": len(a.rerouted_pairs), "B": len(b.rerouted_pairs)},
            "single_point_of_failure": {"A": a.is_single_point_of_failure, "B": b.is_single_point_of_failure},
            "shared_affected_clients": sorted(affected_a & affected_b),
            "only_affected_by_A": sorted(affected_a - affected_b),
            "only_affected_by_B": sorted(affected_b - affected_a),
        },
    })
