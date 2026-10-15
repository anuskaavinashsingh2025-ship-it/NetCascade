# NetCascade — Phase 1: Core Graph Engine

Network Dependency Graph for Predictive Failure Impact and Resilience Analysis (BACSE203 CN Lab).

Phase 1 covers the NetworkX graph model, input validation, the predefined topologies, and
connectivity and shortest-path analysis. The Flask backend and dashboard are not part of this phase.

## Layout
```
netcascade/
  models.py      DeviceType (pc/switch/router/server), Device, Link
  validation.py  ValidationError + rules (ids, types, IPs, link metrics, allowed connections)
  graph.py       NetworkGraph: add/remove/get devices & links, copy(), to_dict/from_dict
  topologies.py  basic, redundant, campus + get_topology()/list_topologies()
  analysis.py    connectivity, reachability, articulation points/bridges, shortest paths
  __main__.py    demo: python -m netcascade [basic|redundant|campus]
tests/           pytest suite
```

## Setup (macOS)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -v
python -m netcascade
```

## Validation rules
- Device ids: 1–64 chars, letters/digits/`_`/`-`/`.`, unique.
- Device type must be one of pc, switch, router, server (case-insensitive).
- IP addresses are optional, must be valid IPv4/IPv6 and unique.
- Links: both endpoints must exist; no self-loops or duplicates; bandwidth and latency must be positive finite numbers.
- PCs and servers must connect to a switch or router. End device ↔ end device links are rejected.

---

# Phase 2: Failure Simulation & Impact Analysis

New modules (Phase 1 code unchanged apart from added exports):
```
netcascade/simulation.py  device/link failure on a graph copy, impact score, severity, ranking, SPOFs
netcascade/simulate.py    command-line simulator
netcascade/visualize.py   PNG diagrams (before/after failure) and criticality ranking charts -> images/
```

- **Clients** are PCs. By default each PC needs every server; set `requires=["SRV1"]` on a PC to narrow it.
- **Affected client**: a PC that loses a path to at least one required server because of the failure.
- **Impact score** = affected clients / total clients × 100.
  Severity: Low 0–24.99, Medium 25–49.99, High 50–74.99, Critical 75–100.
- **Rerouted pairs**: PC→server pairs that are still connected but whose shortest path used the failed component. The new alternate path is reported.
- **Genuine single point of failure**: a device or link whose failure cuts off a PC that is still working. A PC failing by itself doesn't count.

## Commands
```bash
python -m netcascade.simulate basic --device R1
python -m netcascade.simulate redundant --link SW1 R1
python -m netcascade.simulate campus --rank
python -m netcascade.simulate campus --spof
python -m netcascade.visualize          # regenerate images/
open images/                            # view in Finder
```

---

# Phase 3: Flask Backend API

```
backend/
  __init__.py      create_app() factory
  __main__.py      python -m backend [--port 5001] [--debug]
  store.py         in-memory workspace: pristine copy, saved topology, last simulation
  errors.py        JSON envelope + error -> HTTP status mapping
  serializers.py   engine objects -> JSON
  routes/          topology.py, devices.py, links.py, simulation.py, analysis.py
```

Responses: `{"success": true, "data": ...}` or `{"success": false, "error": {"code", "message", "status"}}`.
Status codes: 200/201 ok, 400 malformed request, 404 unknown id/topology/link, 405 wrong method,
409 duplicate device/link/IP or deleting a server a PC explicitly `requires`, 415 non-JSON body, 422 invalid values.

Edits are validated on a copy and committed only if valid. Simulations run on copies and never change the saved topology.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | health check |
| GET | `/api/topologies` | list predefined topologies |
| POST | `/api/topologies/<name>/load` | load basic / redundant / campus |
| POST | `/api/topology/new` | start an empty topology `{"name"}` |
| GET | `/api/topology` | full topology: devices, links, stats |
| POST | `/api/topology/reset` | restore the topology as originally loaded |
| GET | `/api/devices[?type=pc]` | list devices |
| GET | `/api/devices/<id>` | device details, neighbours, links, `required_by` |
| POST | `/api/devices` | add `{"id","type","name?","ip_address?","attributes?","requires?"}` |
| PATCH | `/api/devices/<id>` | edit name / ip_address / type / attributes / requires |
| DELETE | `/api/devices/<id>` | delete device and its links |
| GET | `/api/links` | list links |
| GET | `/api/links/<a>/<b>` | link details |
| POST | `/api/links` | add `{"source","target","bandwidth_mbps?","latency_ms?","attributes?"}` |
| PATCH | `/api/links/<a>/<b>` | edit bandwidth / latency / attributes |
| DELETE | `/api/links/<a>/<b>` | delete link |
| POST | `/api/simulate/device` | `{"device_id"}` -> impact result |
| POST | `/api/simulate/link` | `{"source","target"}` -> impact result |
| GET | `/api/simulation` | last simulation result |
| POST | `/api/simulation/reset` | clear the simulation |
| POST | `/api/simulate/compare` | `{"scenarios":[A,B]}`, each `{"kind":"device","device_id"}` or `{"kind":"link","source","target"}` |
| GET | `/api/analysis/rankings[?kind=all\|devices\|links&type=&top=]` | criticality ranking |
| GET | `/api/analysis/spof` | genuine single points of failure |
| GET | `/api/analysis/connectivity` | components, isolated devices, unreachable required pairs |

## Run
```bash
python -m backend                     # http://127.0.0.1:5001 (5000 is used by AirPlay on macOS)
curl -s http://127.0.0.1:5001/api/topologies
curl -s -X POST http://127.0.0.1:5001/api/simulate/device -H 'Content-Type: application/json' -d '{"device_id":"R1"}'
```

---

# Phase 4: Frontend (Overview page)

Plain HTML/CSS/ES modules served by the same Flask app. No Node or build step.
```
frontend/index.html
frontend/assets/css/app.css
frontend/assets/js/api.js     fetch wrapper for /api
frontend/assets/js/graph.js   SVG canvas: pan, zoom, fit, drag, link mode, auto layout
frontend/assets/js/icons.js   3D-style device art + UI icons
frontend/assets/js/app.js     state, cards, info panel, modals, undo/redo, search
backend/frontend.py           serves / and /assets/*
```
```bash
python -m backend        # then open http://127.0.0.1:5001
```
Shortcuts: V select · L add link · Del delete · ⌘Z / ⇧⌘Z undo/redo · ⌘K search · +/−/0 zoom/fit · Esc cancel.
Device positions are a UI concern and are kept in the browser's localStorage per topology.

---

# Topology & Scenarios pages

**Topology** (`#topology`): select or link devices, simulate device or link failures, view failure impact analysis,
and filter the criticality ranking (all components or single points of failure only).
Reset Simulation clears only the simulation. Restore original discards topology edits.

**Scenarios** (`#scenarios`): saved single-device or single-link failure scenarios for each topology.
Results and "last run" times come only from real runs. A scenario becomes **Outdated** when the topology changes after
its last run, and **Target missing** when its device or link is deleted.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/scenarios` | scenarios for the loaded topology + summary counts |
| POST | `/api/scenarios` | create `{"name","kind":"device","device_id"}` or `{"name","kind":"link","source","target"}`, optional `description` |
| GET / PATCH / DELETE | `/api/scenarios/<id>` | read · rename / edit description · delete |
| POST | `/api/scenarios/<id>/copy` | copy the configuration (not the results) |
| POST | `/api/scenarios/<id>/run` | run with the Phase 2 engine; stores result, reachability matrix, run time |

Comparison uses `POST /api/simulate/compare`. Scenarios are saved to `data/scenarios.json`
(`python -m backend --scenarios <file>` to change it). Multiple-device failures are not supported by the engine yet.

---

# Evaluation (proposal §9: Planned Results and Evaluation)

```bash
python -m netcascade.evaluate                    # basic, redundant, campus · median of 20 runs per failure
python -m netcascade.evaluate basic redundant --repeat 50
```
Prints the tables and writes:
- `results/evaluation.json`: everything, including per-component records
- `results/summary.csv`: per topology × failure type (device / link / all): mean, median and max impact, severity counts, SPOF count and share, mean lost pairs, mean/max ms
- `results/components.csv`: every device and link failure with impact, severity, SPOF flag and execution time
- `results/common_failures.csv`: the same component failing in different topologies (with vs without redundancy)
- `images/evaluation_summary.png` and `images/evaluation_common_failures.png`

What it covers:
- **Execution time per failure scenario.** Median wall-clock time of `simulate_device_failure` / `simulate_link_failure`, plus the time for one full criticality ranking. Live API responses also include `execution_ms`; a single cold call is slower than the benchmark median.
- **Single-device vs single-link failures.** Separate statistics for each.
- **With vs without redundant paths.** Basic vs Redundant (vs Campus), including the same components side by side.

API: `GET /api/analysis/evaluation?repeat=5[&records=false]` evaluates the loaded workspace topology.
`GET /api/analysis/evaluation/compare?topologies=basic,redundant,campus&repeat=5[&records=true]` evaluates fresh predefined topologies.

Note: each PC requires every server by default, so a server failure is always Critical. Set `requires` on PCs to model per-service dependencies.
