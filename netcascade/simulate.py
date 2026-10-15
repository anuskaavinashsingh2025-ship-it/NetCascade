"""Command-line failure simulator.

Examples:
    python -m netcascade.simulate basic --device R1
    python -m netcascade.simulate redundant --link SW1 R1
    python -m netcascade.simulate campus --rank
    python -m netcascade.simulate campus --spof
    python -m netcascade.simulate basic --device R1 --image images/my_failure.png
"""

from __future__ import annotations

import argparse
import sys

from .simulation import (
    rank_devices,
    rank_links,
    simulate_device_failure,
    simulate_link_failure,
    single_points_of_failure,
)
from .topologies import get_topology, list_topologies
from .validation import ValidationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m netcascade.simulate", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topology", choices=list_topologies())
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--device", metavar="ID", help="simulate failure of a device")
    group.add_argument("--link", nargs=2, metavar=("A", "B"), help="simulate failure of a link")
    group.add_argument("--rank", action="store_true", help="rank all devices and links by impact")
    group.add_argument("--spof", action="store_true", help="list genuine single points of failure")
    parser.add_argument("--top", type=int, default=10, help="rows to show with --rank (default 10)")
    parser.add_argument("--image", metavar="PATH", help="also save a PNG of the failure (with --device/--link)")
    args = parser.parse_args(argv)

    net = get_topology(args.topology)
    try:
        if args.device or args.link:
            result = (simulate_device_failure(net, args.device) if args.device
                      else simulate_link_failure(net, *args.link))
            print(result.summary())
            if args.image:
                from .visualize import draw_failure
                print(f"\nSaved {draw_failure(net, result, args.image)}")
        elif args.rank:
            for title, results in (("Devices", rank_devices(net)), ("Links", rank_links(net))):
                print(f"{title} ranked by impact ({args.topology}):")
                for i, r in enumerate(results[: args.top], 1):
                    spof = "  SPOF" if r.is_single_point_of_failure else ""
                    print(f"  {i:>2}. {r.label:<22} {r.impact_score:6.2f}%  {r.severity.value:<8}"
                          f" lost pairs: {len(r.lost_pairs)}{spof}")
                print()
        else:
            spof = single_points_of_failure(net)
            print(f"Single points of failure in {args.topology}:")
            for kind in ("devices", "links"):
                items = ", ".join(f"{r.label} ({r.impact_score:.1f}%)" for r in spof[kind]) or "none"
                print(f"  {kind}: {items}")
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
