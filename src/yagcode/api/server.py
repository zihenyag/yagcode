"""Command line entry point for the local development sidecar API."""

from __future__ import annotations

import argparse

import uvicorn

from yagcode.api.app import Runtime, create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m yagcode.api.server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--token", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    runtime = Runtime(startup_token=args.token, desktop_origin=args.origin)
    uvicorn.run(
        create_app(runtime),
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
