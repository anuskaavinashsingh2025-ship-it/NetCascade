"""Saved scenario API: list, create, rename/edit, copy, delete, run."""

from __future__ import annotations

from typing import Any

import networkx as nx
from flask import Blueprint

from netcascade import NetworkGraph
from netcascade.models import DeviceType

from ..errors import ApiError, json_body, ok, require_fields
from ..scenarios import get_scenarios, now_iso, topology_fingerprint
from ..serializers import failure_to_dict
from ..store import get_store
from .simulation import device_id_list, timed_run

bp = Blueprint("scenarios", __name__)

MAX_NAME, MAX_DESC = 80, 500
CREATE_FIELDS = {"name", "kind", "device_id", "device_ids", "source", "target", "description"}
UPDATE_FIELDS = {"name", "description"}


# --------------------------------------------------------------- helpers
def topology_key() -> str:
    store = get_store()
    return store.source or f"custom:{store.network.name}"


def _target_exists(net: NetworkGraph, target: dict[str, Any]) -> bool:
    if target["kind"] == "device":
        return net.has_device(target["device_id"])
    if target["kind"] == "devices":
        return all(net.has_device(d) for d in target["device_ids"])
    return net.has_device(target["source"]) and net.has_device(target["target"]) and net.has_link(target["source"], target["target"])


def _status(rec: dict[str, Any], net: NetworkGraph, fingerprint: str) -> str:
    if not _target_exists(net, rec["target"]):
        return "invalid"          # the target was deleted from the topology
    if not rec["result"]:
        return "not_run"
    if rec["fingerprint"] != fingerprint:
        return "outdated"         # topology edited since the last run
    return "completed"


def _target_label(net: NetworkGraph, target: dict[str, Any]) -> str:
    if target["kind"] == "link":
        return f"{target['source']} – {target['target']}"
    if target["kind"] == "devices":
        return ", ".join(target["device_ids"])
    did = target["device_id"]
    if not net.has_device(did):
        return did
    kind = net.get_device(did).type
    return f"{did} ({'PC' if kind is DeviceType.PC else kind.value.title()})"


def serialize(rec: dict[str, Any], net: NetworkGraph, fingerprint: str) -> dict[str, Any]:
    return {
        "id": rec["id"],
        "name": rec["name"],
        "kind": rec["target"]["kind"],
        "target": rec["target"],
        "target_label": _target_label(net, rec["target"]),
        "description": rec["description"],
        "topology": rec["topology"],
        "created_at": rec["created_at"],
        "last_run_at": rec["last_run_at"],
        "status": _status(rec, net, fingerprint),
        "result": rec["result"],
    }


def _require(scenario_id: str) -> dict[str, Any]:
    rec = get_scenarios().get(scenario_id)
    if rec is None:
        raise ApiError(f"Unknown scenario {scenario_id!r}", 404)
    return rec


def _require_current_topology(rec: dict[str, Any]) -> None:
    if rec["topology"] != topology_key():
        raise ApiError(f"Scenario {rec['name']!r} belongs to the {rec['topology']!r} topology; load it first", 409)


def _clean_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError("'name' must be a non-empty string", 422)
    name = " ".join(value.split())
    if len(name) > MAX_NAME:
        raise ApiError(f"'name' must be at most {MAX_NAME} characters", 422)
    return name


def _clean_description(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApiError("'description' must be a string", 422)
    if len(value) > MAX_DESC:
        raise ApiError(f"'description' must be at most {MAX_DESC} characters", 422)
    return value.strip()


def _ident(data: dict, field: str) -> str:
    value = data[field]
    if not isinstance(value, str) or not value:
        raise ApiError(f"'{field}' must be a non-empty string", 422)
    return value


def reachability_after(net: NetworkGraph, kind: str, component: Any) -> dict[str, Any]:
    """PC/server reachability matrix on a copy of the topology with the component removed."""
    failed = net.copy()
    if kind == "device":
        failed.remove_device(component)
    elif kind == "devices":
        for d in component:
            failed.remove_device(d)
    else:
        failed.remove_link(*component)
    nodes = net.device_ids(DeviceType.PC) + net.device_ids(DeviceType.SERVER)
    comp: dict[str, int] = {}
    for i, c in enumerate(nx.connected_components(failed.graph)):
        for n in c:
            comp[n] = i
    rows = [[None if a == b else (a in comp and b in comp and comp[a] == comp[b]) for b in nodes] for a in nodes]
    return {"nodes": nodes, "reachable": rows}


def _list_payload() -> dict[str, Any]:
    net = get_store().network
    fp = topology_fingerprint(net)
    items = [serialize(s, net, fp) for s in get_scenarios().for_topology(topology_key())]
    count = lambda *st: sum(1 for s in items if s["status"] in st)  # noqa: E731
    return {
        "topology": topology_key(),
        "scenarios": items,
        "summary": {
            "total": len(items),
            "completed": count("completed"),
            "pending": count("outdated"),
            "not_run": count("not_run", "invalid"),
            "by_kind": {k: sum(1 for s in items if s["kind"] == k) for k in ("device", "link", "devices")},
        },
    }


# ---------------------------------------------------------------- routes
@bp.get("/scenarios")
def list_scenarios():
    return ok(_list_payload())


@bp.get("/scenarios/<scenario_id>")
def get_scenario(scenario_id: str):
    net = get_store().network
    return ok(serialize(_require(scenario_id), net, topology_fingerprint(net)))


@bp.post("/scenarios")
def create_scenario():
    data = json_body()
    unknown = sorted(set(data) - CREATE_FIELDS)
    if unknown:
        raise ApiError(f"Unknown field(s): {', '.join(unknown)}", 400)
    require_fields(data, "name", "kind")
    name = _clean_name(data["name"])
    description = _clean_description(data.get("description"))
    kind = data["kind"]
    net = get_store().network
    if kind == "device":
        require_fields(data, "device_id")
        target = {"kind": "device", "device_id": _ident(data, "device_id")}
        if not net.has_device(target["device_id"]):
            raise ApiError(f"Unknown device {target['device_id']!r}", 404)
    elif kind == "link":
        require_fields(data, "source", "target")
        a, b = _ident(data, "source"), _ident(data, "target")
        if not (net.has_device(a) and net.has_device(b) and net.has_link(a, b)):
            raise ApiError(f"Link {a!r} <-> {b!r} does not exist", 404)
        link = next(l for l in net.links() if l.key == frozenset((a, b)))   # stored orientation
        target = {"kind": "link", "source": link.source, "target": link.target}
    elif kind == "devices":
        require_fields(data, "device_ids")
        ids = device_id_list(data)
        if len(set(ids)) != len(ids):
            raise ApiError("'device_ids' must not contain duplicates", 422)
        if len(ids) < 2:
            raise ApiError("A multiple-device failure needs at least two devices", 422)
        missing = [d for d in ids if not net.has_device(d)]
        if missing:
            raise ApiError(f"Unknown device {missing[0]!r}", 404)
        target = {"kind": "devices", "device_ids": ids}
    else:
        raise ApiError("'kind' must be 'device', 'devices' or 'link'", 422)

    scenarios = get_scenarios()
    key = topology_key()
    if scenarios.name_taken(key, name):
        raise ApiError(f"A scenario named {name!r} already exists", 409)
    rec = scenarios.add(key, name, target, description)
    return ok(serialize(rec, net, topology_fingerprint(net)), 201)


@bp.patch("/scenarios/<scenario_id>")
def update_scenario(scenario_id: str):
    rec = _require(scenario_id)
    data = json_body()
    unknown = sorted(set(data) - UPDATE_FIELDS)
    if unknown:
        raise ApiError(f"Unknown field(s): {', '.join(unknown)}", 400)
    if not data:
        raise ApiError("No fields to update", 400)
    changes: dict[str, Any] = {}
    if "name" in data:
        changes["name"] = _clean_name(data["name"])
        if get_scenarios().name_taken(rec["topology"], changes["name"], exclude=scenario_id):
            raise ApiError(f"A scenario named {changes['name']!r} already exists", 409)
    if "description" in data:
        changes["description"] = _clean_description(data["description"])
    rec = get_scenarios().update(scenario_id, **changes)
    net = get_store().network
    return ok(serialize(rec, net, topology_fingerprint(net)))


@bp.post("/scenarios/<scenario_id>/copy")
def copy_scenario(scenario_id: str):
    rec = _require(scenario_id)
    scenarios = get_scenarios()
    base = f"{rec['name']} (copy)"
    name, n = base, 2
    while scenarios.name_taken(rec["topology"], name):
        name, n = f"{rec['name']} (copy {n})", n + 1
    name = name[:MAX_NAME]
    new = scenarios.add(rec["topology"], name, rec["target"], rec["description"])   # copies config, not results
    net = get_store().network
    return ok(serialize(new, net, topology_fingerprint(net)), 201)


@bp.delete("/scenarios/<scenario_id>")
def delete_scenario(scenario_id: str):
    rec = _require(scenario_id)
    get_scenarios().delete(scenario_id)
    return ok({"deleted": rec["id"], "name": rec["name"]})


@bp.post("/scenarios/<scenario_id>/run")
def run_scenario(scenario_id: str):
    rec = _require(scenario_id)
    _require_current_topology(rec)
    store = get_store()
    with store.lock:
        net = store.network
        result, ms = timed_run(net, dict(rec["target"]))   # Phase 2 simulation on a copy, timed
        payload = {**failure_to_dict(net, result), "execution_ms": ms}
        store.simulation = payload                      # also the current simulation on the Topology page
        stored = {**payload, "matrix": reachability_after(net, result.kind, result.component)}
        fp = topology_fingerprint(net)
    rec = get_scenarios().update(scenario_id, result=stored, fingerprint=fp, last_run_at=now_iso())
    return ok(serialize(rec, net, fp))
