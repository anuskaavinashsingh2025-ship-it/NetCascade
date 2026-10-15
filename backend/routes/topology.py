"""Topology listing, loading, creation and reset."""

from flask import Blueprint

from netcascade import get_topology, list_topologies
from netcascade import topologies as topo_module

from ..errors import ApiError, json_body, ok
from ..serializers import topology_stats, topology_to_dict
from ..store import get_store

bp = Blueprint("topology", __name__)


def current_topology():
    store = get_store()
    return topology_to_dict(store.network, store.source, store.is_modified())


@bp.get("/health")
def health():
    return ok({"status": "ok"})


@bp.get("/topologies")
def list_all():
    store = get_store()
    items = []
    for name in list_topologies():
        builder = topo_module.TOPOLOGIES[name]
        stats = topology_stats(get_topology(name))
        items.append({
            "name": name,
            "description": (builder.__doc__ or "").strip().splitlines()[0],
            "device_count": stats["device_count"],
            "link_count": stats["link_count"],
        })
    return ok({"topologies": items, "active": store.source})


@bp.post("/topologies/<name>/load")
def load(name: str):
    get_store().load(name)  # unknown name -> ValidationError -> 404
    return ok(current_topology())


@bp.post("/topology/new")
def new():
    data = json_body()
    name = data.get("name", "custom")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("'name' must be a non-empty string", 422)
    get_store().new(name.strip())
    return ok(current_topology(), 201)


@bp.get("/topology")
def get():
    return ok(current_topology())


@bp.post("/topology/reset")
def reset():
    get_store().reset_topology()
    return ok(current_topology())
