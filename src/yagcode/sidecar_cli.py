"""Internal sidecar executable entry used by desktop packaging."""

from __future__ import annotations

import argparse
import json
import sys

from yagcode import __version__
from yagcode.api.server import main as server_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yagcode-sidecar")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="print a sidecar runtime health JSON line")
    subparsers.add_parser("version", help="print the sidecar version")
    serve = subparsers.add_parser("serve", help="start the local sidecar API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--origin", required=True)
    serve.add_argument("--token", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "health":
        print(json.dumps({"state": "ready", "product": "yagcode-sidecar", "version": __version__}, sort_keys=True))
        return 0
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "serve":
        return server_main(
            [
                "--host",
                args.host,
                "--port",
                str(args.port),
                "--origin",
                args.origin,
                "--token",
                args.token,
            ]
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["build_parser", "main"]
