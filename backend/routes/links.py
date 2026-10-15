"""Link (edge) CRUD. Links are undirected: /links/A/B and /links/B/A are the same link."""

from __future__ import annotations

from typing import Any

from flask import Blueprint

from netcascade import NetworkGraph

from ..errors import ApiError, json_body, ok, require_fields
from ..serializers import canonical_link, link_to_dict
from ..store import get_store

bp = Blueprint("links", __name__)

RESERVED_ATTRS = {"self", "id", "source", "target", "bandwidth_mbps", "latency_ms", "attributes"}
CREATE_FIELDS = {"source", "target", "bandwidth_mbps", "latency_ms", "attributes"}
UPDATE_FIELDS = {"bandwidth_mbps", "latency_ms", "attributes"}


def _reject_unknown(data: dict, allowed: set[str]) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ApiError(f"Unknown field(s): {', '.join(unknown)}", 400)


def _attributes(data: dict) -> dict[str, Any]:
    attrs = data.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise ApiError("'attributes' must be a JSON object", 422)
    bad = sorted(k for k in attrs if k in RESERVED_ATTRS)
    if bad:
        raise ApiError(f"Reserved attribute name(s): {', '.join(bad)}", 422)
    return dict(attrs)


def _require_link(net: NetworkGraph, a: str, b: str) -> None:
    for d in (a, b):
        if not net.has_device(d):
            raise ApiError(f"Unknown device {d!r}", 404)
    if not net.has_link(a, b):
        raise ApiError(f"Link {a!r} <-> {b!r} does not exist", 404)


@bp.get("/links")
def list_links():
    return ok({"links": [link_to_dict(link) for link in get_store().network.links()]})


@bp.get("/links/<source>/<target>")
def get_link(source: str, target: str):
    net = get_store().network
    _require_link(net, source, target)
    return ok(link_to_dict(canonical_link(net, source, target)))


@bp.post("/links")
def create_link():
    data = json_body()
    _reject_unknown(data, CREATE_FIELDS)
    require_fields(data, "source", "target")
    for f in ("source", "target"):
        if not isinstance(data[f], str):
            raise ApiError(f"'{f}' must be a device id string", 422)
    attrs = _attributes(data)
    kwargs = {k: data[k] for k in ("bandwidth_mbps", "latency_ms") if k in data}
    store = get_store()
    link = store.mutate(lambda net: net.add_link(data["source"], data["target"], **kwargs, **attrs))
    return ok(link_to_dict(link), 201)


@bp.patch("/links/<source>/<target>")
def update_link(source: str, target: str):
    data = json_body()
    _reject_unknown(data, UPDATE_FIELDS)
    if not data:
        raise ApiError("No fields to update", 400)
    store = get_store()
    _require_link(store.network, source, target)
    new_attrs = _attributes(data)

    def change(net: NetworkGraph):
        old = canonical_link(net, source, target)
        attrs = dict(old.attributes)
        for key, value in new_attrs.items():
            if value is None:
                attrs.pop(key, None)
            else:
                attrs[key] = value
        net.remove_link(source, target)
        return net.add_link(
            old.source, old.target,
            bandwidth_mbps=data.get("bandwidth_mbps", old.bandwidth_mbps),
            latency_ms=data.get("latency_ms", old.latency_ms),
            **attrs,
        )

    link = store.mutate(change)
    return ok(link_to_dict(link))


@bp.delete("/links/<source>/<target>")
def delete_link(source: str, target: str):
    store = get_store()
    _require_link(store.network, source, target)
    link = canonical_link(store.network, source, target)
    store.mutate(lambda net: net.remove_link(source, target))
    return ok({"deleted": f"{link.source}--{link.target}"})
