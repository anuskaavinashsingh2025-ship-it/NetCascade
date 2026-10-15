"""Criticality rankings, single points of failure and connectivity."""

from __future__ import annotations

from flask import Blueprint, request

from netcascade import (
    can_reach,
    connected_components,
    is_connected,
    isolated_devices,
    rank_devices,
    rank_links,
    required_pairs,
    single_points_of_failure,
)
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
