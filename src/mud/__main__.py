"""Server entry point.

``python -m mud --check-config`` prints the effective configuration and exits
without binding a port or touching the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from mud.config import ConfigError, load_config


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mud", description="Club MUD server")
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="path to mud.toml (default: ./mud.toml when it exists)",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="print the effective configuration and exit",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"mud: error: {exc}", file=sys.stderr)
        return 2

    if args.check_config:
        print(json.dumps(config.model_dump(), indent=2))
        return 0

    print("mud: the server is not implemented yet; use --check-config", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
