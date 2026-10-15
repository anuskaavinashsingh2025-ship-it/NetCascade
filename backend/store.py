"""In-memory topology workspace.

Holds three things:
- ``pristine``: the topology as first loaded/created; ``reset_topology()`` restores it.
- ``network``: the saved working topology, changed only by explicit edits.
- ``simulation``: the last simulated failure (serialized). Simulations always run
  on copies via the Phase 2 functions, so ``network`` is never touched by them.
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Callable

from flask import current_app

from netcascade import NetworkGraph, ValidationError, get_topology, required_pairs


class TopologyStore:
    def __init__(self, default_topology: str = "basic") -> None:
        self.lock = RLock()
        self.source: str | None = None
        self._pristine = NetworkGraph()
        self.network = NetworkGraph()
        self.simulation: dict[str, Any] | None = None
        self.load(default_topology)

    def load(self, name: str) -> None:
        net = get_topology(name)
        with self.lock:
            self.source = net.name
            self._pristine = net
            self.network = net.copy()
            self.simulation = None

    def new(self, name: str) -> None:
        with self.lock:
            self.source = None
            self._pristine = NetworkGraph(name)
            self.network = self._pristine.copy()
            self.simulation = None

    def reset_topology(self) -> None:
        with self.lock:
            self.network = self._pristine.copy()
            self.simulation = None

    def reset_simulation(self) -> None:
        with self.lock:
            self.simulation = None

    def mutate(self, change: Callable[[NetworkGraph], Any]) -> Any:
        """Apply ``change`` to a copy, validate it, then commit atomically.

        If ``change`` or validation raises, the saved topology is unchanged.
        """
        with self.lock:
            draft = self.network.copy()
            result = change(draft)
            if isinstance(result, NetworkGraph):  # change rebuilt the graph
                draft, result = result, None
            required_pairs(draft)  # every PC's `requires` must still point at real servers
            self.network = draft
            self.simulation = None  # an old result no longer describes the topology
            return result

    def is_modified(self) -> bool:
        return self.network.to_dict() != self._pristine.to_dict()


def get_store() -> TopologyStore:
    return current_app.extensions["netcascade_store"]


__all__ = ["TopologyStore", "get_store", "ValidationError"]
