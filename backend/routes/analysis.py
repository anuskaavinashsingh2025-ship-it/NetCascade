"""Criticality rankings, single points of failure, connectivity and evaluation metrics."""

from __future__ import annotations

from flask import Blueprint, request

from netcascade import (
    can_reach,
    connected_components,
    evaluation,
    is_connected,
    isolated_devices,
    rank_devices,
    rank_links,
    required_pairs,
    single_points_of_failure,
)
from netcascade.topologies import list_topologies
from netcascade.validation import validate_device_type

from ..errors import ApiError, ok
from ..serializers import ranking_entry
from ..store import get_store

bp = Blueprint("analysis", __name__)


def _top() -> int | None:
    raw = request.args.get("top")
    if raw is None:
        return None
    try:
        top = int(raw)
    except ValueError:
        raise ApiError("'top' must be a positive integer", 400) from None
    if top < 1:
        raise ApiError("'top' must be a positive integer", 400)
    return top


@bp.get("/analysis/rankings")
def rankings():
    kind = request.args.get("kind", "all")
    if kind not in ("all", "devices", "links"):
        raise ApiError("'kind' must be 'all', 'devices' or 'links'", 400)
    device_type = request.args.get("type")
    if device_type is not None:
        device_type = validate_device_type(device_type)
    top = _top()
    net = get_store().network
    data = {}
    if kind in ("all", "devices"):
        data["devices"] = [ranking_entry(r, i) for i, r in enumerate(rank_devices(net, device_type)[:top], 1)]
    if kind in ("all", "links"):
        data["links"] = [ranking_entry(r, i) for i, r in enumerate(rank_links(net)[:top], 1)]
    return ok(data)


@bp.get("/analysis/spof")
def spof():
    found = single_points_of_failure(get_store().network)
    devices = [ranking_entry(r, i) for i, r in enumerate(found["devices"], 1)]
    links = [ranking_entry(r, i) for i, r in enumerate(found["links"], 1)]
    return ok({"devices": devices, "links": links, "count": len(devices) + len(links)})


@bp.get("/analysis/connectivity")
def connectivity():
    net = get_store().network
    pairs = required_pairs(net)
    unreachable = [{"client": a, "server": b} for a, b in pairs if not can_reach(net, a, b)]
    return ok({
        "connected": is_connected(net),
        "components": [sorted(c) for c in connected_components(net)],
        "isolated_devices": isolated_devices(net),
        "required_pair_count": len(pairs),
        "unreachable_required_pairs": unreachable,
    })


def _repeat() -> int:
    raw = request.args.get("repeat", "5")
    try:
        repeat = int(raw)
    except ValueError:
        raise ApiError("'repeat' must be an integer between 1 and 50", 400) from None
    if not 1 <= repeat <= 50:
        raise ApiError("'repeat' must be an integer between 1 and 50", 400)
    return repeat


def _summary(report: dict, records: bool) -> dict:
    return report if records else {k: v for k, v in report.items() if k != "records"}


@bp.get("/analysis/evaluation")
def evaluate_current():
    """Device vs link failure statistics and execution time for the loaded topology."""
    repeat = _repeat()
    records = request.args.get("records", "true").lower() != "false"
    return ok(_summary(evaluation.evaluate_topology(get_store().network, repeat=repeat), records))


@bp.get("/analysis/evaluation/compare")
def evaluate_compare():
    """Compare predefined topologies (with vs without redundancy). Uses fresh copies, not the workspace."""
    raw = request.args.get("topologies", "basic,redundant,campus")
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    unknown = [n for n in names if n not in list_topologies()]
    if not names or unknown:
        raise ApiError(f"Unknown topology {', '.join(unknown) or '(none)'}. Available: {', '.join(list_topologies())}", 404)
    repeat = _repeat()
    records = request.args.get("records", "false").lower() == "true"
    report = evaluation.compare_topologies(dict.fromkeys(names), repeat=repeat)
    report["topologies"] = [_summary(t, records) for t in report["topologies"]]
    return ok(report)
