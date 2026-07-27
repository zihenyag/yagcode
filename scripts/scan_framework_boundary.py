"""Reject high-level agent-runner frameworks from the submitted harness boundary."""

from __future__ import annotations

import json
import re
import sys

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BANNED = (
    "langchain",
    "langgraph",
    "autogen",
    "crewai",
    "llamaindex",
    "llama_index",
    "openhands",
)
SOURCE_ROOTS = (ROOT / "src" / "yagcode",)
MANIFESTS = (ROOT / "package.json", ROOT / "pyproject.toml")


def main() -> int:
    findings: list[str] = []
    for manifest in MANIFESTS:
        if manifest.is_file():
            findings.extend(_scan_text(manifest.relative_to(ROOT).as_posix(), manifest.read_text(encoding="utf-8")))
    for root in SOURCE_ROOTS:
        findings.extend(_scan_source_tree(root))
    if findings:
        print("FRAMEWORK_BOUNDARY_FAILED", file=sys.stderr)
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    print("FRAMEWORK_BOUNDARY_PASSED")
    return 0


def _scan_source_tree(root: Path) -> list[str]:
    findings: list[str] = []
    if not root.is_dir():
        return findings
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        findings.extend(_scan_python_imports(relative, path.read_text(encoding="utf-8")))
    return findings


def _scan_python_imports(relative: str, text: str) -> list[str]:
    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        lowered = stripped.lower()
        for banned in BANNED:
            if re.search(rf"\b{re.escape(banned)}\b", lowered):
                findings.append(f"{relative}:{line_number}: banned import {banned}")
    return findings


def _scan_text(relative: str, text: str) -> list[str]:
    findings: list[str] = []
    lowered = text.lower()
    for banned in BANNED:
        if banned in lowered:
            findings.append(f"{relative}: banned dependency text {banned}")
    if relative == "package.json":
        data = json.loads(text)
        for block in ("dependencies", "devDependencies", "optionalDependencies"):
            dependencies = data.get(block, {})
            if isinstance(dependencies, dict):
                for name in dependencies:
                    normalized = name.lower().replace("-", "")
                    if any(banned.replace("_", "") in normalized for banned in BANNED):
                        findings.append(f"{relative}: banned npm dependency {name}")
    return findings


if __name__ == "__main__":
    raise SystemExit(main())
