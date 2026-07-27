"""Fail CI/local validation when source candidates contain likely credentials.

The scanner intentionally reports only file, line, and detector name. It never
prints the matched value, because the tool itself must not become a leakage
channel. Scope includes Git-tracked files plus unignored untracked files so
pre-commit validation covers new source. Ignored local files such as `.env`
remain out of scope.
"""

from __future__ import annotations

import re
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Final


_SKIP_SUFFIXES: Final = {
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".webp",
    ".zip",
}
_SKIP_PARTS: Final = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
    "__pycache__",
}


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line_number: int
    detector: str


_DETECTORS: Final = (
    ("openai_or_compatible_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b")),
    ("github_fine_grained_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{80,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
)


def main() -> int:
    root = Path.cwd()
    findings: list[Finding] = []
    for relative_path in _candidate_files(root):
        path = root / relative_path
        if _should_skip(relative_path, path):
            continue
        findings.extend(_scan_file(relative_path, path))
    if findings:
        print("SECRET_SCAN_FAILED", file=sys.stderr)
        for finding in findings:
            print(
                f"{finding.path}:{finding.line_number}: {finding.detector}",
                file=sys.stderr,
            )
        return 1
    print("SECRET_SCAN_PASSED")
    return 0


def _candidate_files(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError("SECRET_SCAN_GIT_LS_FILES_FAILED")
    return tuple(sorted(set(line for line in result.stdout.splitlines() if line)))


def _should_skip(relative_path: str, path: Path) -> bool:
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return True
    return any(part in _SKIP_PARTS for part in Path(relative_path).parts)


def _scan_file(relative_path: str, path: Path) -> tuple[Finding, ...]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    findings: list[Finding] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for detector, pattern in _DETECTORS:
            if pattern.search(line):
                findings.append(Finding(relative_path, line_number, detector))
    return tuple(findings)


if __name__ == "__main__":
    raise SystemExit(main())
