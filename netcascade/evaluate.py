"""Evaluation report: execution time, device vs link failures, redundancy comparison.

    python -m netcascade.evaluate                       # basic, redundant, campus
    python -m netcascade.evaluate basic redundant --repeat 50
    python -m netcascade.evaluate --out results --images images

Writes results/evaluation.json, results/summary.csv, results/components.csv,
results/common_failures.csv and images/evaluation_*.png.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .evaluation import SEVERITIES, compare_topologies
from .topologies import list_topologies

ROOT = Path(__file__).resolve().parent.parent


def write_outputs(report: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    path = out_dir / "evaluation.json"
    path.write_text(json.dumps(report, indent=2))
    written.append(path)

    path = out_dir / "summary.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["topology", "devices", "links", "clients", "failure_type", "scenarios", "mean_impact",
                    "median_impact", "max_impact", *[f"{s.lower()}_count" for s in SEVERITIES],
                    "single_points_of_failure", "spof_share_pct", "mean_lost_pairs", "mean_ms", "max_ms"])
        for t in report["topologies"]:
            for label, key in (("device", "device_failures"), ("link", "link_failures"), ("all", "all_failures")):
                st = t[key]
                w.writerow([t["name"], t["devices"], t["links"], t["clients"], label, st["count"], st["mean_impact"],
                            st["median_impact"], st["max_impact"], *[st["severity_counts"][s] for s in SEVERITIES],
                            st["single_points_of_failure"], st["spof_share"], st["mean_lost_pairs"], st["mean_ms"], st["max_ms"]])
    written.append(path)

    path = out_dir / "components.csv"
    with path.open("w", newline="") as f:
        fields = ["topology", "kind", "label", "component_type", "impact_score", "severity", "affected_clients",
                  "total_clients", "lost_pairs", "rerouted_pairs", "single_point_of_failure", "execution_ms"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in report["topologies"]:
            for r in t["records"]:
                w.writerow({"topology": t["name"], **r})
    written.append(path)

    path = out_dir / "common_failures.csv"
    names = [t["name"] for t in report["topologies"]]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "label", "component_type", *[f"{n}_impact" for n in names], *[f"{n}_spof" for n in names]])
        for c in report["common_failures"]:
            w.writerow([c["kind"], c["label"], c["component_type"],
                        *[c["impact"].get(n, {}).get("impact_score", "") for n in names],
                        *[c["impact"].get(n, {}).get("single_point_of_failure", "") for n in names]])
    written.append(path)
    return written


def print_report(report: dict) -> None:
    print(f"NetCascade evaluation · {report['generated_at']} · repeat={report['repeat']} · {report['environment']}\n")
    head = f"{'Topology':<11}{'Type':<8}{'N':>4}{'Mean %':>9}{'Max %':>8}{'SPOF':>6}{'SPOF %':>8}{'Crit':>6}{'High':>6}{'Med':>5}{'Low':>5}{'Mean ms':>10}{'Max ms':>9}"
    print(head)
    print("-" * len(head))
    for t in report["topologies"]:
        for label, key in (("device", "device_failures"), ("link", "link_failures"), ("all", "all_failures")):
            st = t[key]
            sc = st["severity_counts"]
            print(f"{t['name'] if label == 'device' else '':<11}{label:<8}{st['count']:>4}{st['mean_impact']:>9.2f}{st['max_impact']:>8.2f}"
                  f"{st['single_points_of_failure']:>6}{st['spof_share']:>8.1f}{sc['Critical']:>6}{sc['High']:>6}{sc['Medium']:>5}{sc['Low']:>5}"
                  f"{st['mean_ms']:>10.3f}{st['max_ms']:>9.3f}")
        print(f"{'':<11}full criticality ranking ({t['devices']} devices + {t['links']} links): {t['timing']['full_ranking_ms']:.2f} ms\n")
    names = [t["name"] for t in report["topologies"]]
    if report["common_failures"]:
        print("Same component failing in different topologies (impact %):")
        print(f"{'Component':<16}" + "".join(f"{n:>12}" for n in names))
        for c in report["common_failures"]:
            cells = "".join(f"{(str(c['impact'][n]['impact_score']) + ('*' if c['impact'][n]['single_point_of_failure'] else '')) if n in c['impact'] else '–':>12}" for n in names)
            print(f"{c['label']:<16}{cells}")
        print("* = single point of failure")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m netcascade.evaluate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topologies", nargs="*", choices=list_topologies(), help="default: all")
    parser.add_argument("--repeat", type=int, default=20, help="timed runs per failure (median is kept)")
    parser.add_argument("--out", default=str(ROOT / "results"), help="directory for JSON/CSV results")
    parser.add_argument("--images", default=str(ROOT / "images"), help="directory for charts")
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    report = compare_topologies(args.topologies or list_topologies(), repeat=args.repeat)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repeat": args.repeat,
        "environment": f"Python {platform.python_version()} on {platform.system()} {platform.machine()}",
        **report,
    }
    print_report(report)
    written = write_outputs(report, Path(args.out))
    if not args.no_charts:
        from .visualize import draw_evaluation
        written += draw_evaluation(report, Path(args.images))
    print("\nWrote:")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
