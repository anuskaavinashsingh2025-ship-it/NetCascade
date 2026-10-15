"""Device (node) CRUD."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, request

from netcascade import NetworkGraph, required_pairs
from netcascade.validation import validate_device_type

from ..errors import ApiError, json_body, ok, require_fields
from ..serializers import device_to_dict
from ..store import get_store

bp = Blueprint("devices", __name__)

# Attribute names that would collide with NetworkGraph.add_device parameters.
RESERVED_ATTRS = {"self", "id", "device_id", "type", "device_type", "name", "ip_address", "attributes"}
CREATE_FIELDS = {"id", "type", "name", "ip_address", "attributes", "requires"}
UPDATE_FIELDS = {"id", "name", "ip_address", "type", "attributes", "requires"}


def _reject_unknown(data: dict, allowed: set[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ApiError(f"Unknown field(s): {', '.join(unknown)}", 400)


def _attributes(data: dict) -> dict[str, Any]:
    attrs = data.get("attributes", {})
    if attrs is None:
        attrs = {}
    if not isinstance(attrs, dict):
        raise ApiError("'attributes' must be a JSON object", 422)
    bad = sorted(k for k in attrs if k in RESERVED_ATTRS)
    if bad:
        raise ApiError(f"Reserved attribute name(s): {', '.join(bad)}", 422)
    return dict(attrs)


def _normalize_requires(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ApiError("'requires' must be a server id or a list of server ids", 422)
    return list(dict.fromkeys(value))


def _check_requires_type(device_type: str, attrs: dict) -> None:
    if attrs.get("requires") is not None and device_type != "pc":
        raise ApiError("Only PCs can have 'requires'", 422)


def _require_device(net: NetworkGraph, device_id: str) -> None:
    if not net.has_device(device_id):
        raise ApiError(f"Unknown device {device_id!r}", 404)


@bp.get("/devices")
def list_devices():
    net = get_store().network
    device_type = request.args.get("type")
    if device_type is not None:
        device_type = validate_device_type(device_type)
    return ok({"devices": [device_to_dict(net, d) for d in net.device_ids(device_type)]})


@bp.get("/devices/<device_id>")
def get_device(device_id: str):
    net = get_store().network
    _require_device(net, device_id)
    return ok(device_to_dict(net, device_id, detail=True))


@bp.post("/devices")
def create_device():
    data = json_body()
    _reject_unknown(data, CREATE_FIELDS)
    require_fields(data, "id", "type")
    attrs = _attributes(data)
    if "requires" in data:
        attrs["requires"] = _normalize_requires(data["requires"])
        if attrs["requires"] is None:
            del attrs["requires"]
    dtype = validate_device_type(data["type"])
    _check_requires_type(dtype.value, attrs)

    store = get_store()
    device = store.mutate(lambda net: net.add_device(
        data["id"], dtype, name=data.get("name") or "", ip_address=data.get("ip_address"), **attrs
    ))
    return ok(device_to_dict(store.network, device.id, detail=True), 201)


@bp.patch("/devices/<device_id>")
def update_device(device_id: str):
    data = json_body()
    _reject_unknown(data, UPDATE_FIELDS)
    if not data:
        raise ApiError("No fields to update", 400)
    if "id" in data and data["id"] != device_id:
        raise ApiError("Device id cannot be changed", 422)
    store = get_store()
    _require_device(store.network, device_id)
    new_attrs = _attributes(data)
    if "requires" in data:
        new_attrs["requires"] = _normalize_requires(data["requires"])
    if "name" in data and not isinstance(data["name"], str):
        raise ApiError("'name' must be a string", 422)
    if "type" in data:
        validate_device_type(data["type"])

    def change(net: NetworkGraph) -> NetworkGraph:
        topo = net.to_dict()
        dev = next(d for d in topo["devices"] if d["id"] == device_id)
        for field in ("name", "ip_address", "type"):
            if field in data:
                dev[field] = data[field]
        for key, value in new_attrs.items():
            if value is None:
                dev["attributes"].pop(key, None)
            else:
                dev["attributes"][key] = value
        _check_requires_type(validate_device_type(dev["type"]).value, dev["attributes"])
        return NetworkGraph.from_dict(topo)  # full re-validation: type vs links, duplicate IPs, ...

    store.mutate(change)
    return ok(device_to_dict(store.network, device_id, detail=True))


@bp.delete("/devices/<device_id>")
def delete_device(device_id: str):
    store = get_store()
    net = store.network
    _require_device(net, device_id)
    dependents = sorted(pc for pc, srv in required_pairs(net) if srv == device_id
                        and "requires" in net.get_device(pc).attributes)
    if dependents:
        raise ApiError(
            f"Cannot delete {device_id!r}: required by {', '.join(dependents)}. Update their 'requires' first.",
            409, details={"required_by": dependents},
        )
    removed_links = [f"{device_id}--{n}" for n in sorted(net.neighbors(device_id))]
    store.mutate(lambda draft: draft.remove_device(device_id))
    return ok({"deleted": device_id, "removed_links": removed_links})
