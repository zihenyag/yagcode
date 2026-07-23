"""Private, byte-copy Git shadows that leave the source repository untouched."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from yagcode.git.baseline import BaselineManifest, digest_files
from yagcode.git.identity import git_environment, run_git
from yagcode.git.preflight import GitPreflightError, preflight_repository, read_index_entries


@dataclass(frozen=True, slots=True)
class ShadowBaseline:
    shadow_root: Path
    shadow_head_tree: str | None
    shadow_index: tuple[tuple[str, str], ...]
    shadow_worktree: dict[str, bytes]
    manifest: dict[str, bytes]
    baseline_manifest: BaselineManifest


def _head_tree(root: Path) -> str | None:
    result = run_git(root, "rev-parse", "HEAD^{tree}", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _git_path(root: Path, name: str) -> Path:
    return Path(
        run_git(root, "rev-parse", "--path-format=absolute", "--git-path", name).stdout.strip()
    ).resolve(strict=False)


def _copy_git_objects(source_common_dir: Path, shadow_git_dir: Path) -> None:
    source_objects = source_common_dir / "objects"
    target_objects = shadow_git_dir / "objects"
    alternates = source_objects / "info" / "alternates"
    if alternates.exists():
        raise GitPreflightError("GIT_ALTERNATES_UNSUPPORTED")
    for source in sorted(source_objects.rglob("*")):
        if source.is_symlink():
            raise GitPreflightError("GIT_OBJECT_SYMLINK_UNSUPPORTED")
        if not source.is_file():
            continue
        relative = source.relative_to(source_objects)
        if relative.parts == ("info", "alternates"):
            raise GitPreflightError("GIT_ALTERNATES_UNSUPPORTED")
        destination = target_objects / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)


def _tracked_and_untracked(root: Path) -> dict[str, bytes]:
    tracked = {entry.path for entry in read_index_entries(root)}
    untracked = set(filter(None, run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")))
    files: dict[str, bytes] = {}
    for relative in sorted(tracked | untracked):
        candidate = root / relative
        if candidate.is_symlink():
            raise GitPreflightError("SHADOW_SYMLINK_UNSUPPORTED")
        if candidate.is_file():
            files[relative] = candidate.read_bytes()
    return files


class ShadowService:
    def __init__(self, private_root: Path) -> None:
        self._private_root = Path(private_root)

    def capture_and_create(self, root: Path, *, run_id: str) -> ShadowBaseline:
        identity = preflight_repository(root)
        if not run_id or Path(run_id).name != run_id:
            raise GitPreflightError("SHADOW_RUN_ID_INVALID")
        source = identity.worktree_root
        files = _tracked_and_untracked(source)
        entries = read_index_entries(source)
        head_tree = _head_tree(source)
        target = self._private_root / run_id
        if target.exists():
            raise GitPreflightError("SHADOW_RUN_EXISTS")
        target.mkdir(parents=True)
        bundle = target / "objects.bundle"
        worktree = target / "worktree"
        try:
            if head_tree is None:
                subprocess.run(
                    ["git", "init", os.fspath(worktree)],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=git_environment(),
                    shell=False,
                )
            else:
                run_git(source, "bundle", "create", os.fspath(bundle), "--all")
                run_git(target, "clone", "--no-hardlinks", os.fspath(bundle), os.fspath(worktree))
            for relative, content in files.items():
                destination = worktree / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            if head_tree is None:
                # An unborn index refers to objects held only by the source
                # object database. Rebuild it from copied bytes inside the
                # private repository instead of borrowing that database.
                for entry in entries:
                    run_git(worktree, "add", "--", entry.path)
            else:
                shadow_git_dir = _git_path(worktree, ".")
                _copy_git_objects(identity.common_dir, shadow_git_dir)
                source_index = _git_path(source, "index")
                shadow_index = _git_path(worktree, "index")
                if source_index.exists():
                    shutil.copyfile(source_index, shadow_index)
            if head_tree is None:
                synthetic_tree = run_git(worktree, "write-tree").stdout.strip()
                synthetic_commit = run_git(
                    worktree,
                    "-c",
                    "user.name=YagCode Shadow",
                    "-c",
                    "user.email=shadow@invalid",
                    "commit-tree",
                    synthetic_tree,
                    "-m",
                    "synthetic unborn baseline",
                ).stdout.strip()
                run_git(worktree, "update-ref", f"refs/yagcode/runs/{run_id}", synthetic_commit)
            observed = _tracked_and_untracked(worktree)
            if observed != files:
                raise GitPreflightError("SHADOW_MANIFEST_MISMATCH")
            protected = hashlib.sha256(repr((head_tree, entries, sorted(files))).encode()).hexdigest()
            return ShadowBaseline(
                target,
                head_tree,
                tuple((entry.object_id, entry.path) for entry in entries),
                observed,
                files,
                BaselineManifest(head_tree, entries, digest_files(files), (), protected),
            )
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
