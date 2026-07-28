"""Fail CI/local validation when source candidates contain likely credentials.

The scanner intentionally reports only file, line, and detector name. It never
prints the matched value, because the tool itself must not become a leakage
channel. Scope includes Git-tracked files plus unignored untracked files so
pre-commit validation covers new source. Ignored local files such as `.env`
remain out of scope.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal


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
    scope: str = "worktree"


_DETECTORS: Final = (
    ("openai_or_compatible_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b")),
    ("github_fine_grained_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{80,}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
)
_ALLOWED_HISTORY_SECRET_BLOBS: Final = frozenset(
    {
        # Synthetic key-shaped fixture blobs from earlier local tests. These hashes
        # are reviewed as non-secret fixtures so the history scanner can still
        # fail closed for any new unreviewed credential-shaped object.
        "87d9fd2c4faaf3c6ac1eafc750da104e7ad5acd5",
        "c42a6dfbe7758d638780cea66eb94b68b7e020dc",
        "b41d128b932fad4c876eebddec37efbe274a83dc",
        "44e9ecd5ac0f0ee3449c260a7574bedc3344467f",
        "cb51a38eb2eaec0ba650d784454b32df14353a7c",
        "1b9902f19ced6865aeb7e6c87e777150e74c719f",
    }
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = args.root.resolve()
    findings: list[Finding] = []
    for scope in args.scope:
        if scope == "worktree":
            findings.extend(_scan_worktree(root))
        elif scope == "history":
            findings.extend(_scan_history(root))
        elif scope == "unpacked":
            if args.unpacked_root is None:
                raise RuntimeError("SECRET_SCAN_UNPACKED_ROOT_REQUIRED")
            findings.extend(_scan_directory(args.unpacked_root.resolve(), scope="unpacked"))
        else:
            raise RuntimeError("SECRET_SCAN_SCOPE_INVALID")
    if findings:
        print("SECRET_SCAN_FAILED", file=sys.stderr)
        for finding in findings:
            print(
                f"{finding.scope}:{finding.path}:{finding.line_number}: {finding.detector}",
                file=sys.stderr,
            )
        return 1
    print("SECRET_SCAN_PASSED")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--scope",
        action="append",
        choices=("worktree", "history", "unpacked"),
        default=None,
    )
    parser.add_argument("--unpacked-root", type=Path)
    args = parser.parse_args(argv)
    if args.scope is None:
        args.scope = ["worktree"]
    return args


def _scan_worktree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for relative_path in _candidate_files(root):
        path = root / relative_path
        if not path.exists():
            continue
        if _should_skip(relative_path, path):
            continue
        findings.extend(_scan_file(relative_path, path, scope="worktree"))
    return findings


def _scan_directory(root: Path, *, scope: Literal["unpacked"]) -> list[Finding]:
    if not root.is_dir():
        raise RuntimeError("SECRET_SCAN_UNPACKED_ROOT_INVALID")
    findings: list[Finding] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        relative_path = path.relative_to(root).as_posix()
        if _should_skip(relative_path, path):
            continue
        findings.extend(_scan_file(relative_path, path, scope=scope))
    return findings


def _scan_history(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    object_names = _git_lines(root, "rev-list", "--objects", "--all")
    object_ids = [line.split(maxsplit=1)[0] for line in object_names]
    for object_id in object_ids:
        object_type = _git_text(root, "cat-file", "-t", object_id).strip()
        if object_type == "blob":
            if object_id in _ALLOWED_HISTORY_SECRET_BLOBS:
                continue
            payload = _git_bytes(root, "cat-file", "blob", object_id)
            findings.extend(_scan_bytes(f"blob:{object_id}", payload, scope="history", line_number=1))
        elif object_type == "commit":
            payload = _git_bytes(root, "cat-file", "commit", object_id)
            findings.extend(_scan_bytes(f"commit:{object_id}", payload, scope="history", line_number=1))
        elif object_type == "tag":
            payload = _git_bytes(root, "cat-file", "tag", object_id)
            findings.extend(_scan_bytes(f"tag:{object_id}", payload, scope="history", line_number=1))
        elif object_type == "tree":
            tree_entries = _git_lines(root, "ls-tree", "-rz", object_id, text=False)
            for entry in b"\0".join(line.encode("utf-8") for line in tree_entries).split(b"\0"):
                if entry:
                    findings.extend(_scan_bytes(f"tree:{object_id}", entry, scope="history", line_number=1))
    return findings


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


def _scan_file(relative_path: str, path: Path, *, scope: str) -> tuple[Finding, ...]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ()
    findings: list[Finding] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for detector, pattern in _DETECTORS:
            if pattern.search(line):
                findings.append(Finding(relative_path, line_number, detector, scope))
    return tuple(findings)


def _scan_bytes(
    location: str,
    payload: bytes,
    *,
    scope: str,
    line_number: int,
) -> tuple[Finding, ...]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        text = payload.decode("utf-8", errors="ignore")
    findings: list[Finding] = []
    for detector, pattern in _DETECTORS:
        if pattern.search(text):
            findings.append(Finding(location, line_number, detector, scope))
    return tuple(findings)


def _git_lines(root: Path, *argv: str, text: bool = True) -> list[str]:
    if text:
        return _git_text(root, *argv).splitlines()
    return _git_bytes(root, *argv).decode("utf-8", errors="ignore").splitlines()


def _git_text(root: Path, *argv: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *argv],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError("SECRET_SCAN_GIT_FAILED")
    return result.stdout


def _git_bytes(root: Path, *argv: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *argv],
        check=False,
        capture_output=True,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError("SECRET_SCAN_GIT_FAILED")
    return result.stdout


if __name__ == "__main__":
    raise SystemExit(main())
