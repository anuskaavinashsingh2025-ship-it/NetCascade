"""Saved failure scenarios (Phase 6).

A scenario is a named single-device or single-link failure tied to one topology
(``basic``, ``redundant`` or a custom one). Running it uses the Phase 2
simulation functions; the result, the run time and a fingerprint of the
topology it ran on are stored with it. Nothing is stored until a real run.

Scenarios live in memory, and are also written to a JSON file when a path is
given (``python -m backend`` uses ``data/scenarios.json``).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from flask import current_app

from netcascade import NetworkGraph

SEED_SCENARIOS: dict[str, list[dict[str, Any]]] = {
    "basic": [
        {"name": "Router Failure", "target": {"kind": "device", "device_id": "R1"},
         "description": "Simulate failure of the main router to analyse impact on client connectivity to the server."},
        {"name": "Switch Failure", "target": {"kind": "device", "device_id": "SW1"},
         "description": "Simulate failure of the access switch that connects every PC."},
        {"name": "PC1 Link Failure", "target": {"kind": "link", "source": "PC1", "target": "SW1"},
         "description": "Simulate a cable fault between PC1 and its switch."},
    ],
    "redundant": [
        {"name": "Router R1 Failure", "target": {"kind": "device", "device_id": "R1"},
         "description": "Check whether traffic reroutes through R2 when R1 fails."},
        {"name": "Switch SW1 Failure", "target": {"kind": "device", "device_id": "SW1"},
         "description": "Fail the access switch serving PC1 and PC2."},
        {"name": "Uplink SW1–R1 Failure", "target": {"kind": "link", "source": "SW1", "target": "R1"},
         "description": "Cut one switch-to-router uplink and confirm the alternate uplink keeps clients connected."},
    ],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def topology_fingerprint(net: NetworkGraph) -> str:
    """Hash of the full topology; a stored result is only current while this matches."""
    raw = json.dumps(net.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class ScenarioStore:
    def __init__(self, path: str | Path | None = None, seed: bool = True) -> None:
        self.lock = RLock()
        self.path = Path(path) if path else None
        self.items: dict[str, dict[str, Any]] = {}
        if self.path and self.path.exists():
            self._load()
        if seed and not self.items:
            for topology, seeds in SEED_SCENARIOS.items():
                for s in seeds:
                    self.add(topology, s["name"], s["target"], s["description"], save=False)
            self._save()

    # ---------------------------------------------------------------- storage
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
            items = data.get("scenarios", []) if isinstance(data, dict) else []
            self.items = {s["id"]: s for s in items if isinstance(s, dict) and "id" in s}
        except (OSError, ValueError, KeyError):
            self.items = {}  # unreadable file: start clean rather than crash

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".scenarios-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"version": 1, "scenarios": list(self.items.values())}, f, indent=2)
        os.replace(tmp, self.path)

    # -------------------------------------------------------------------- CRUD
    def for_topology(self, topology: str) -> list[dict[str, Any]]:
        with self.lock:
            return sorted((s for s in self.items.values() if s["topology"] == topology),
                          key=lambda s: (s.get("seq", 0), s["created_at"]))

    def get(self, scenario_id: str) -> dict[str, Any] | None:
        return self.items.get(scenario_id)

    def add(self, topology: str, name: str, target: dict[str, Any], description: str = "",
            save: bool = True) -> dict[str, Any]:
        with self.lock:
            rec = {
                "id": uuid.uuid4().hex[:10],
                "seq": max((s.get("seq", 0) for s in self.items.values()), default=0) + 1,   # creation order
                "topology": topology,
                "name": name,
                "target": dict(target),
                "description": description,
                "created_at": now_iso(),
                "last_run_at": None,
                "fingerprint": None,
                "result": None,
            }
            self.items[rec["id"]] = rec
            if save:
                self._save()
            return rec

    def update(self, scenario_id: str, **fields: Any) -> dict[str, Any]:
        with self.lock:
            rec = self.items[scenario_id]
            rec.update(fields)
            self._save()
            return rec

    def delete(self, scenario_id: str) -> None:
        with self.lock:
            del self.items[scenario_id]
            self._save()

    def name_taken(self, topology: str, name: str, exclude: str | None = None) -> bool:
        key = name.strip().casefold()
        return any(s["name"].casefold() == key and s["id"] != exclude for s in self.for_topology(topology))


def get_scenarios() -> ScenarioStore:
    return current_app.extensions["netcascade_scenarios"]
