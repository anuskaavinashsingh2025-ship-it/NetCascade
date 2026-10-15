"""Start the API: python -m backend [--port 5001] [--debug]"""

import argparse
from pathlib import Path

from . import create_app

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"

parser = argparse.ArgumentParser(prog="python -m backend")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=5001)  # 5000 is taken by AirPlay Receiver on macOS
parser.add_argument("--debug", action="store_true")
parser.add_argument("--scenarios", default=str(DATA_FILE), help="JSON file for saved scenarios")
args = parser.parse_args()
create_app(config={"SCENARIOS_PATH": args.scenarios}).run(host=args.host, port=args.port, debug=args.debug)
