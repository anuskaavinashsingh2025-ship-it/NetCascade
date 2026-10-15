"""Quick demo: python -m netcascade [basic|redundant|campus]"""

import sys

from . import analysis as an
from .topologies import get_topology, list_topologies


def main(argv: list[str]) -> int:
    names = argv or list_topologies()
    for name in names:
        net = get_topology(name)
        print(f"=== {net.name}: {net.device_count} devices, {net.link_count} links ===")
        print(f"  connected:          {an.is_connected(net)}")
        print(f"  single points (devices): {an.articulation_points(net) or 'none'}")
        print(f"  single points (links):   {an.bridges(net) or 'none'}")
        pcs, servers = net.device_ids("pc"), net.device_ids("server")
        if pcs and servers:
            p = an.shortest_path(net, pcs[0], servers[0])
            q = an.shortest_path(net, pcs[0], servers[0], metric="latency")
            print(f"  {pcs[0]} -> {servers[0]} (hops):    {' -> '.join(p.path)} [{p.hops} hops]")
            print(f"  {pcs[0]} -> {servers[0]} (latency): {' -> '.join(q.path)} [{q.latency_ms} ms]")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
