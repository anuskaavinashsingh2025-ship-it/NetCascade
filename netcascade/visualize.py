"""Static PNG visualizations of topologies, simulated failures and criticality rankings.

Run ``python -m netcascade.visualize`` to regenerate everything in ``images/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no GUI needed; works headless on macOS
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from .graph import NetworkGraph  # noqa: E402
from .models import DeviceType  # noqa: E402
from .simulation import (  # noqa: E402
    FailureResult,
    Severity,
    rank_devices,
    rank_links,
    simulate_device_failure,
    simulate_link_failure,
)
from .topologies import get_topology  # noqa: E402

# Colors: reference palette (status colors for state, blue for servers, neutral ink for chrome).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
EDGE = "#c3c2b7"
SERVER = "#2a78d6"
INFRA = "#898781"
OK = "#0ca30c"
AFFECTED = "#ec835a"
FAILED = "#d03b3b"
SEVERITY_COLORS = {
    Severity.LOW: "#0ca30c",
    Severity.MEDIUM: "#fab219",
    Severity.HIGH: "#ec835a",
    Severity.CRITICAL: "#d03b3b",
}
SHAPES = {DeviceType.PC: "o", DeviceType.SWITCH: "s", DeviceType.ROUTER: "D", DeviceType.SERVER: "h"}

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "images"


# -------------------------------------------------------------------- layout
def layered_layout(net: NetworkGraph) -> dict[str, tuple[float, float]]:
    """Servers on top, then each layer by hop distance from the nearest server, PCs at the bottom."""
    g = net.graph
    servers = net.device_ids(DeviceType.SERVER)
    dist = nx.multi_source_dijkstra_path_length(g, servers) if servers else {}
    max_d = max(dist.values(), default=0)
    pcs = set(net.device_ids(DeviceType.PC))
    layer = {}
    for n in g.nodes:
        layer[n] = max_d if n in pcs else dist.get(n, max_d + 1)

    pos: dict[str, tuple[float, float]] = {}
    for depth in sorted(set(layer.values())):
        nodes = [n for n in g.nodes if layer[n] == depth]
        def order(n):
            parents = [pos[p][0] for p in g.neighbors(n) if p in pos]
            return (sum(parents) / len(parents) if parents else 0.0, n)
        nodes.sort(key=order)
        width = len(nodes)
        for i, n in enumerate(nodes):
            x = (i - (width - 1) / 2) / max(width - 1, 1) * min(width / 3, 1.0) * 2
            pos[n] = (x, -depth)
    return pos


# ------------------------------------------------------------------- drawing
def _draw(ax, net: NetworkGraph, pos, result: FailureResult | None, title: str) -> None:
    g = net.graph
    ax.set_facecolor(SURFACE)
    failed_node = result.component if result and result.kind == "device" else None
    failed_edge = frozenset(result.component) if result and result.kind == "link" else None
    affected = set(result.affected_clients) if result else set()
    lost_servers = {s for _, s in result.lost_pairs} if result else set()

    # Edges: normal, failed (dashed red), alternate path (blue).
    alt_edges: set[frozenset] = set()
    if result and result.rerouted_pairs:
        first_path = next(iter(result.rerouted_pairs.values()))
        alt_edges = {frozenset(e) for e in zip(first_path, first_path[1:])}
    for u, v in g.edges:
        e = frozenset((u, v))
        (x1, y1), (x2, y2) = pos[u], pos[v]
        if result and (failed_node in (u, v) or e == failed_edge):
            ax.plot([x1, x2], [y1, y2], color=FAILED, lw=2, ls=(0, (4, 3)), zorder=1)
        elif e in alt_edges:
            ax.plot([x1, x2], [y1, y2], color=SERVER, lw=3, zorder=1)
        else:
            ax.plot([x1, x2], [y1, y2], color=EDGE, lw=1.5, zorder=0)

    for n, data in g.nodes(data=True):
        t = data["type"]
        if n == failed_node:
            color = FAILED
        elif t is DeviceType.PC:
            color = AFFECTED if n in affected else OK
        elif t is DeviceType.SERVER:
            color = SERVER
        else:
            color = INFRA
        x, y = pos[n]
        ax.scatter([x], [y], s=520, marker=SHAPES[t], c=color, edgecolors=SURFACE, linewidths=2, zorder=3)
        if n == failed_node:
            ax.scatter([x], [y], s=90, marker="x", c=SURFACE, linewidths=2, zorder=4)
        weight = "bold" if n == failed_node or n in affected else "normal"
        ax.annotate(n, (x, y), xytext=(0, -20), textcoords="offset points", ha="center", va="top",
                    fontsize=8, color=INK if weight == "bold" else INK_2, fontweight=weight, zorder=5)

    ax.set_title(title, fontsize=11, color=INK, loc="left", pad=10)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 0.35, max(xs) + 0.35)
    ax.set_ylim(min(ys) - 0.6, max(ys) + 0.35)
    ax.axis("off")


def draw_failure(net: NetworkGraph, result: FailureResult, path: str | Path) -> Path:
    """Side-by-side 'before' and 'after failure' diagram with the impact summary."""
    pos = layered_layout(net)
    n = net.device_count
    fig, axes = plt.subplots(1, 2, figsize=(max(12, n * 0.75), 6.2 + n * 0.06), facecolor=SURFACE)
    _draw(axes[0], net, pos, None, f"Before: {net.name} topology")
    _draw(axes[1], net, pos, result, f"After: {result.kind} {result.label} fails")

    sev_color = SEVERITY_COLORS[result.severity]
    headline = (f"Impact {result.impact_score:.2f}%  ·  {result.severity.value}  ·  "
                f"{len(result.affected_clients)} of {result.total_clients} clients affected  ·  "
                f"{len(result.lost_pairs)} PC→server pairs lost")
    if result.rerouted_pairs:
        headline += f"  ·  {len(result.rerouted_pairs)} rerouted"
    fig.text(0.03, 0.955, headline, ha="left", fontsize=12, color=INK, fontweight="bold")
    fig.patches.append(plt.Rectangle((0.018, 0.952), 0.007, 0.028, transform=fig.transFigure,
                                     color=sev_color, figure=fig))

    legend = [
        Line2D([], [], marker="o", ls="", color=OK, markersize=9, label="PC: still reaches server"),
        Line2D([], [], marker="o", ls="", color=AFFECTED, markersize=9, label="PC: affected"),
        Line2D([], [], marker="X", ls="", color=FAILED, markersize=10, label="Failed component"),
        Line2D([], [], marker="h", ls="", color=SERVER, markersize=10, label="Server"),
        Line2D([], [], marker="s", ls="", color=INFRA, markersize=9, label="Switch"),
        Line2D([], [], marker="D", ls="", color=INFRA, markersize=8, label="Router"),
        Line2D([], [], color=FAILED, lw=2, ls=(0, (4, 3)), label="Link down"),
        Line2D([], [], color=SERVER, lw=3, label="Alternate path"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=8, frameon=False, fontsize=8.5,
               labelcolor=INK_2, handletextpad=0.4, columnspacing=1.2)
    fig.tight_layout(rect=(0, 0.06, 1, 0.93))
    return _save(fig, path)


def draw_ranking(net: NetworkGraph, path: str | Path, top: int = 10) -> Path:
    """Horizontal bars: top devices and links by impact score, each labelled with severity."""
    results = (rank_devices(net) + rank_links(net))
    results.sort(key=lambda r: (-r.impact_score, -len(r.lost_pairs), r.label))
    results = results[:top][::-1]

    fig, ax = plt.subplots(figsize=(9, 0.42 * len(results) + 1.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    labels = [f"{'device' if r.kind == 'device' else 'link'}  {r.label}" for r in results]
    scores = [r.impact_score for r in results]
    colors = [SEVERITY_COLORS[r.severity] for r in results]
    ax.barh(labels, scores, color=colors, height=0.6, edgecolor=SURFACE, linewidth=2)
    for i, r in enumerate(results):
        ax.text(r.impact_score + 1.2, i, f"{r.impact_score:.1f}%  {r.severity.value}"
                + ("  · SPOF" if r.is_single_point_of_failure else ""),
                va="center", fontsize=8.5, color=INK_2)
    ax.set_xlim(0, 125)
    ax.set_xticks([0, 25, 50, 75, 100])
    for x in (25, 50, 75):
        ax.axvline(x, color="#e1e0d9", lw=0.8, zorder=0)
    ax.set_xlabel("Impact score (% of clients affected)", color=MUTED, fontsize=9)
    ax.tick_params(colors=INK_2, labelsize=8.5, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(EDGE)
    ax.set_title(f"{net.name}: most critical components (top {len(results)})",
                 loc="left", fontsize=11, color=INK)
    fig.tight_layout()
    return _save(fig, path)


def _save(fig, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path


# Example scenarios used for the report images.
SCENARIOS = [
    ("basic", "device", "R1"),
    ("basic", "link", ("SW1", "R1")),
    ("redundant", "device", "R1"),
    ("redundant", "device", "SW1"),
    ("campus", "device", "ACC-A1"),
    ("campus", "device", "CORE1"),
]


def generate_all(out_dir: str | Path = DEFAULT_OUT) -> list[Path]:
    out_dir = Path(out_dir)
    written = []
    for topo, kind, comp in SCENARIOS:
        net = get_topology(topo)
        if kind == "device":
            result = simulate_device_failure(net, comp)
            name = f"{topo}_device_{comp}_failure.png"
        else:
            result = simulate_link_failure(net, *comp)
            name = f"{topo}_link_{comp[0]}-{comp[1]}_failure.png"
        written.append(draw_failure(net, result, out_dir / name))
    for topo in ("basic", "redundant", "campus"):
        written.append(draw_ranking(get_topology(topo), out_dir / f"{topo}_criticality_ranking.png"))
    return written


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    for p in generate_all(out):
        print(f"wrote {p}")
