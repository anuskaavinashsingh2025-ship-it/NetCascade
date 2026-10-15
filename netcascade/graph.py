"""Core NetworkX-backed network graph."""

from __future__ import annotations

from typing import Any, Iterable

import networkx as nx

from .models import Device, DeviceType, Link
from .validation import (
    ValidationError,
    validate_connection,
    validate_device_id,
    validate_device_type,
    validate_ip_address,
    validate_positive_number,
)


class NetworkGraph:
    """A validated network topology stored as an undirected NetworkX graph.

    Nodes are device ids with attributes ``type``, ``name``, ``ip_address`` and
    ``attributes``. Edges carry ``bandwidth_mbps``, ``latency_ms`` and
    ``attributes``.
    """

    def __init__(self, name: str = "network") -> None:
        self.name = name
        self._graph = nx.Graph(name=name)

    # ------------------------------------------------------------------ devices
    def add_device(
        self,
        device_id: str,
        device_type: DeviceType | str,
        name: str = "",
        ip_address: str | None = None,
        **attributes: Any,
    ) -> Device:
        device_id = validate_device_id(device_id)
        dtype = validate_device_type(device_type)
        ip = validate_ip_address(ip_address)

        if device_id in self._graph:
            raise ValidationError(f"Device {device_id!r} already exists")
        if ip is not None:
            owner = self._find_ip_owner(ip)
            if owner is not None:
                raise ValidationError(f"IP address {ip} is already assigned to {owner!r}")
        if not isinstance(name, str):
            raise ValidationError("Device name must be a string")

        device = Device(device_id, dtype, name or device_id, ip, dict(attributes))
        self._graph.add_node(
            device_id,
            type=dtype,
            name=device.name,
            ip_address=ip,
            attributes=device.attributes,
        )
        return device

    def remove_device(self, device_id: str) -> None:
        self._require_device(device_id)
        self._graph.remove_node(device_id)

    def get_device(self, device_id: str) -> Device:
        self._require_device(device_id)
        data = self._graph.nodes[device_id]
        return Device(device_id, data["type"], data["name"], data["ip_address"], dict(data["attributes"]))

    def has_device(self, device_id: str) -> bool:
        return device_id in self._graph

    def devices(self, device_type: DeviceType | str | None = None) -> list[Device]:
        wanted = DeviceType.parse(device_type) if device_type is not None else None
        return [
            self.get_device(n)
            for n, t in self._graph.nodes(data="type")
            if wanted is None or t == wanted
        ]

    def device_ids(self, device_type: DeviceType | str | None = None) -> list[str]:
        return [d.id for d in self.devices(device_type)]

    # -------------------------------------------------------------------- links
    def add_link(
        self,
        source: str,
        target: str,
        bandwidth_mbps: float = 1000.0,
        latency_ms: float = 1.0,
        **attributes: Any,
    ) -> Link:
        self._require_device(source)
        self._require_device(target)
        if source == target:
            raise ValidationError(f"Cannot link device {source!r} to itself")
        if self._graph.has_edge(source, target):
            raise ValidationError(f"Link {source!r} <-> {target!r} already exists")
        validate_connection(self._graph.nodes[source]["type"], self._graph.nodes[target]["type"])
        bandwidth = validate_positive_number(bandwidth_mbps, "bandwidth_mbps")
        latency = validate_positive_number(latency_ms, "latency_ms")

        link = Link(source, target, bandwidth, latency, dict(attributes))
        self._graph.add_edge(
            source,
            target,
            bandwidth_mbps=bandwidth,
            latency_ms=latency,
            attributes=link.attributes,
        )
        return link

    def remove_link(self, source: str, target: str) -> None:
        if not self._graph.has_edge(source, target):
            raise ValidationError(f"Link {source!r} <-> {target!r} does not exist")
        self._graph.remove_edge(source, target)

    def has_link(self, source: str, target: str) -> bool:
        return self._graph.has_edge(source, target)

    def get_link(self, source: str, target: str) -> Link:
        if not self._graph.has_edge(source, target):
            raise ValidationError(f"Link {source!r} <-> {target!r} does not exist")
        data = self._graph.edges[source, target]
        return Link(source, target, data["bandwidth_mbps"], data["latency_ms"], dict(data["attributes"]))

    def links(self) -> list[Link]:
        return [self.get_link(u, v) for u, v in self._graph.edges]

    def neighbors(self, device_id: str) -> list[str]:
        self._require_device(device_id)
        return list(self._graph.neighbors(device_id))

    # ------------------------------------------------------------------ helpers
    @property
    def graph(self) -> nx.Graph:
        """The underlying NetworkX graph (treat as read-only)."""
        return self._graph

    def copy(self) -> "NetworkGraph":
        """Deep-enough copy for later failure simulation; the original is untouched."""
        clone = NetworkGraph(self.name)
        clone._graph = self._graph.copy()
        for _, data in clone._graph.nodes(data=True):
            data["attributes"] = dict(data["attributes"])
        for _, _, data in clone._graph.edges(data=True):
            data["attributes"] = dict(data["attributes"])
        return clone

    def __len__(self) -> int:
        return self._graph.number_of_nodes()

    def __contains__(self, device_id: object) -> bool:
        return device_id in self._graph

    @property
    def device_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def link_count(self) -> int:
        return self._graph.number_of_edges()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "devices": [d.to_dict() for d in self.devices()],
            "links": [link.to_dict() for link in self.links()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NetworkGraph":
        """Build a graph from a dict, validating every device and link."""
        if not isinstance(data, dict):
            raise ValidationError("Topology definition must be a dict")
        devices = data.get("devices", [])
        links = data.get("links", [])
        if not isinstance(devices, list) or not isinstance(links, list):
            raise ValidationError("'devices' and 'links' must be lists")

        net = cls(str(data.get("name", "network")))
        for i, dev in enumerate(devices):
            if not isinstance(dev, dict) or "id" not in dev or "type" not in dev:
                raise ValidationError(f"Device #{i} must be a dict with 'id' and 'type'")
            net.add_device(
                dev["id"],
                dev["type"],
                name=dev.get("name", ""),
                ip_address=dev.get("ip_address"),
                **dev.get("attributes", {}),
            )
        for i, link in enumerate(links):
            if not isinstance(link, dict) or "source" not in link or "target" not in link:
                raise ValidationError(f"Link #{i} must be a dict with 'source' and 'target'")
            net.add_link(
                link["source"],
                link["target"],
                bandwidth_mbps=link.get("bandwidth_mbps", 1000.0),
                latency_ms=link.get("latency_ms", 1.0),
                **link.get("attributes", {}),
            )
        return net

    def add_links(self, pairs: Iterable[tuple[str, str]], **kwargs: Any) -> None:
        for source, target in pairs:
            self.add_link(source, target, **kwargs)

    def _require_device(self, device_id: str) -> None:
        if device_id not in self._graph:
            raise ValidationError(f"Unknown device {device_id!r}")

    def _find_ip_owner(self, ip: str) -> str | None:
        for node, node_ip in self._graph.nodes(data="ip_address"):
            if node_ip == ip:
                return node
        return None

    def __repr__(self) -> str:
        return f"NetworkGraph(name={self.name!r}, devices={self.device_count}, links={self.link_count})"
