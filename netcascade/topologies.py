"""Predefined sample topologies."""

from __future__ import annotations

from typing import Callable

from .graph import NetworkGraph
from .validation import ValidationError


def basic_topology() -> NetworkGraph:
    """The example from the proposal: 3 PCs -> switch -> router -> server.

    No redundancy, so the switch and router are single points of failure.
    """
    net = NetworkGraph("basic")
    for i in range(1, 4):
        net.add_device(f"PC{i}", "pc", ip_address=f"192.168.1.{10 + i}")
    net.add_device("SW1", "switch")
    net.add_device("R1", "router", ip_address="192.168.1.1")
    net.add_device("SRV1", "server", ip_address="10.0.0.10")

    net.add_links([("PC1", "SW1"), ("PC2", "SW1"), ("PC3", "SW1")], bandwidth_mbps=100, latency_ms=1)
    net.add_link("SW1", "R1", bandwidth_mbps=1000, latency_ms=2)
    net.add_link("R1", "SRV1", bandwidth_mbps=1000, latency_ms=5)
    return net


def redundant_topology() -> NetworkGraph:
    """Two access switches and two routers in a mesh, with dual-homed servers.

    PCs are still single-homed to an access switch, but every
    switch/router has a backup path, so no infrastructure device or
    infrastructure link is a single point of failure for the servers.
    """
    net = NetworkGraph("redundant")
    for i in range(1, 5):
        net.add_device(f"PC{i}", "pc", ip_address=f"192.168.1.{10 + i}")
    net.add_device("SW1", "switch")
    net.add_device("SW2", "switch")
    net.add_device("R1", "router", ip_address="192.168.1.1")
    net.add_device("R2", "router", ip_address="192.168.1.2")
    net.add_device("SRV1", "server", ip_address="10.0.0.10")
    net.add_device("SRV2", "server", ip_address="10.0.0.11")

    net.add_links([("PC1", "SW1"), ("PC2", "SW1"), ("PC3", "SW2"), ("PC4", "SW2")],
                  bandwidth_mbps=100, latency_ms=1)
    # Switch interconnect + each switch dual-homed to both routers.
    net.add_link("SW1", "SW2", bandwidth_mbps=1000, latency_ms=1)
    net.add_link("SW1", "R1", bandwidth_mbps=1000, latency_ms=2)
    net.add_link("SW1", "R2", bandwidth_mbps=1000, latency_ms=4)
    net.add_link("SW2", "R1", bandwidth_mbps=1000, latency_ms=4)
    net.add_link("SW2", "R2", bandwidth_mbps=1000, latency_ms=2)
    net.add_link("R1", "R2", bandwidth_mbps=10000, latency_ms=1)
    # Servers dual-homed to both routers.
    net.add_link("R1", "SRV1", bandwidth_mbps=10000, latency_ms=3)
    net.add_link("R2", "SRV1", bandwidth_mbps=10000, latency_ms=6)
    net.add_link("R1", "SRV2", bandwidth_mbps=10000, latency_ms=6)
    net.add_link("R2", "SRV2", bandwidth_mbps=10000, latency_ms=3)
    return net


def campus_topology() -> NetworkGraph:
    """Three-tier campus network: core / distribution / access + data-centre.

    - Core: two routers (CORE1, CORE2) linked together.
    - Distribution: two switches per building, each uplinked to both cores.
    - Access: one switch per floor, uplinked to both distribution switches of
      its building.
    - Data centre: a switch dual-homed to both cores, with web/DB/file servers.
    - Edge: a gateway router to the internet, attached to both cores.
    """
    net = NetworkGraph("campus")
    net.add_device("CORE1", "router", ip_address="10.255.0.1")
    net.add_device("CORE2", "router", ip_address="10.255.0.2")
    net.add_device("EDGE", "router", ip_address="203.0.113.1")
    net.add_link("CORE1", "CORE2", bandwidth_mbps=40000, latency_ms=0.5)
    net.add_link("EDGE", "CORE1", bandwidth_mbps=10000, latency_ms=1)
    net.add_link("EDGE", "CORE2", bandwidth_mbps=10000, latency_ms=1)

    buildings = {"A": 2, "B": 2}  # building -> number of floors
    for b_idx, (bldg, floors) in enumerate(buildings.items(), start=1):
        dist = [f"DIST-{bldg}1", f"DIST-{bldg}2"]
        for d in dist:
            net.add_device(d, "switch")
            net.add_link(d, "CORE1", bandwidth_mbps=10000, latency_ms=1)
            net.add_link(d, "CORE2", bandwidth_mbps=10000, latency_ms=1)
        net.add_link(dist[0], dist[1], bandwidth_mbps=10000, latency_ms=0.5)

        for floor in range(1, floors + 1):
            acc = f"ACC-{bldg}{floor}"
            net.add_device(acc, "switch")
            net.add_link(acc, dist[0], bandwidth_mbps=1000, latency_ms=1)
            net.add_link(acc, dist[1], bandwidth_mbps=1000, latency_ms=1)
            for pc in range(1, 3):
                pc_id = f"PC-{bldg}{floor}-{pc}"
                net.add_device(pc_id, "pc", ip_address=f"10.{b_idx}.{floor}.{10 + pc}")
                net.add_link(pc_id, acc, bandwidth_mbps=100, latency_ms=1)

    net.add_device("DC-SW", "switch")
    net.add_link("DC-SW", "CORE1", bandwidth_mbps=40000, latency_ms=0.5)
    net.add_link("DC-SW", "CORE2", bandwidth_mbps=40000, latency_ms=0.5)
    for i, role in enumerate(("WEB", "DB", "FILE"), start=10):
        srv = f"SRV-{role}"
        net.add_device(srv, "server", ip_address=f"10.100.0.{i}", role=role.lower())
        net.add_link(srv, "DC-SW", bandwidth_mbps=10000, latency_ms=0.5)
    return net


TOPOLOGIES: dict[str, Callable[[], NetworkGraph]] = {
    "basic": basic_topology,
    "redundant": redundant_topology,
    "campus": campus_topology,
}


def get_topology(name: str) -> NetworkGraph:
    """Build a fresh copy of a predefined topology by name."""
    key = name.strip().lower() if isinstance(name, str) else name
    if key not in TOPOLOGIES:
        raise ValidationError(f"Unknown topology {name!r}. Available: {', '.join(TOPOLOGIES)}")
    return TOPOLOGIES[key]()


def list_topologies() -> list[str]:
    return list(TOPOLOGIES)
