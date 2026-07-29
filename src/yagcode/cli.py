"""Command-line entry point for YagCode."""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from pathlib import Path
from typing import Callable, TextIO

from yagcode.api.dependencies import Services
from yagcode.cli_demo import run_cli_demo
from yagcode.tui import health_payload, run_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yagcode")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("health", help="print local CLI health as JSON")
    subparsers.add_parser("version", help="print the CLI version")
    tui = subparsers.add_parser("tui", help="start the terminal workbench")
    tui.add_argument("--script", help="read commands from a file instead of stdin")
    demo = subparsers.add_parser("demo", help="run a local end-to-end CLI demo")
    demo.add_argument("--workspace", required=True, help="directory used for generated demo projects")
    demo.add_argument("--provider", default="scripted", help="provider id; scripted is deterministic")
    demo.add_argument("--model", default="scripted-local", help="model id")
    demo.add_argument("--real-provider", action="store_true", help="use the configured real Provider")
    demo.add_argument("--json", action="store_true", help="print the public report as JSON")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    cwd: Path | None = None,
    services: Services | None = None,
    secret_prompt: Callable[[str], str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    if args.command is None:
        return run_tui(
            cwd=cwd or Path.cwd(),
            input_stream=input_stream,
            output_stream=output_stream,
            services=services,
            secret_prompt=secret_prompt,
        )
    if args.command == "health":
        print(json.dumps(health_payload(cwd=cwd or Path.cwd()), sort_keys=True), file=output_stream)
        return 0
    if args.command == "version":
        from yagcode import __version__

        print(__version__, file=output_stream)
        return 0
    if args.command == "tui":
        if args.script:
            with Path(args.script).open("r", encoding="utf-8") as script:
                return run_tui(
                    cwd=cwd or Path.cwd(),
                    input_stream=script,
                    output_stream=output_stream,
                    services=services,
                    secret_prompt=secret_prompt,
                )
        return run_tui(
            cwd=cwd or Path.cwd(),
            input_stream=input_stream,
            output_stream=output_stream,
            services=services,
            secret_prompt=secret_prompt,
        )
    if args.command == "demo":
        api_key = getpass.getpass("Provider API key: ") if args.real_provider else None
        report = run_cli_demo(
            workspace=Path(args.workspace),
            provider=args.provider,
            model=args.model,
            real_provider=args.real_provider,
            api_key=api_key,
        )
        if args.json:
            print(report.to_public_json())
        else:
            _print_human_report(report.to_public_dict())
        return 0
    parser.error("COMMAND_UNSUPPORTED")
    return 2


def _print_human_report(report: dict[str, object]) -> None:
    print("YagCode CLI demo")
    print(f"- agents: {_count(report, 'agents')}")
    print(f"- projects: {_count(report, 'projects')}")
    print(f"- threads: {_count(report, 'threads')}")
    print(f"- provider: {report['provider']} / {report['model']}")
    print("- bug fixes:")
    bug_fixes = report["bug_fixes"]
    if not isinstance(bug_fixes, list):
        bug_fixes = []
    for item in bug_fixes:
        if not isinstance(item, dict):
            continue
        diff = item.get("diff")
        files_changed = diff.get("files_changed") if isinstance(diff, dict) else "?"
        print(f"  - {item.get('project_id')}: {item.get('status')} ({files_changed} files)")
    rollback = report["rollback"]
    if isinstance(rollback, dict):
        print(f"- rollback: {rollback.get('status')}")


def _count(report: dict[str, object], key: str) -> object:
    value = report[key]
    return value.get("count") if isinstance(value, dict) else "?"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


__all__ = ["build_parser", "main"]
