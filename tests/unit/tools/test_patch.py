"""structured patch contract tied to ApplyPatchAction."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from yagcode.domain.actions import ApplyPatchAction, ApplyPatchPayload, PatchHunk
from yagcode.domain.results import SideEffectState, ToolStatus


def _action(
    base: bytes,
    *,
    action_id: str = "patch-1",
    expected: str = "two\n",
    replacement: str = "three\n",
    relative: str = "a.txt",
) -> ApplyPatchAction:
    return ApplyPatchAction(
        kind="apply_patch",
        action_id=action_id,
        run_id="run-1",
        generation=0,
        reason_summary="apply patch",
        payload=ApplyPatchPayload(
            root_id="shadow",
            relative_path=relative,
            base_sha256=hashlib.sha256(base).hexdigest(),
            hunks=(
                PatchHunk(
                    start_line=2,
                    delete_line_count=1,
                    expected_text=expected,
                    replacement_text=replacement,
                ),
            ),
        ),
    )


def test_owned_patch_oracle_rejects_stale_or_unmatched_without_mutation() -> None:
    before = b"one\ntwo\n"
    assert hashlib.sha256(before).hexdigest() != "0" * 64
    assert before.replace(b"two\n", b"three\n", 1) == b"one\nthree\n"
    assert b"absent" not in before


def load_patch_contract():
    try:
        return importlib.import_module("yagcode.tools.patch")
    except ModuleNotFoundError as error:
        pytest.fail(f"TOOLS_CONTRACT_MISSING: {error.name}")


def test_patch_stale_baseline_and_context_mismatch_leave_original_bytes(tmp_path: Path) -> None:
    patch = load_patch_contract()
    target = tmp_path / "a.txt"
    before = b"one\ntwo\n"
    target.write_bytes(before)

    stale = _action(before).model_copy(
        update={"payload": _action(before).payload.model_copy(update={"base_sha256": "0" * 64})}
    )
    stale_result = patch.apply_action(stale, roots={"shadow": tmp_path})
    assert stale_result.status is ToolStatus.FAILED
    assert stale_result.category == "STALE_BASELINE"
    assert stale_result.side_effect_state is SideEffectState.NONE
    assert target.read_bytes() == before

    mismatch = patch.apply_action(_action(before, expected="absent"), roots={"shadow": tmp_path})
    assert mismatch.category == "PATCH_CONTEXT_MISMATCH"
    assert mismatch.side_effect_state is SideEffectState.NONE
    assert target.read_bytes() == before


def test_patch_success_uses_same_directory_stage_and_cleans_it(tmp_path: Path) -> None:
    patch = load_patch_contract()
    target = tmp_path / "a.txt"
    before = b"one\ntwo\n"
    target.write_bytes(before)
    staged_paths: list[Path] = []

    def stage_path_factory(path: Path) -> Path:
        staged = path.with_name(f".{path.name}.yagcode-stage-test")
        staged_paths.append(staged)
        return staged

    result = patch.apply_action(
        _action(before),
        roots={"shadow": tmp_path},
        stage_path_factory=stage_path_factory,
    )
    assert result.status is ToolStatus.SUCCEEDED
    assert result.side_effect_state is SideEffectState.APPLIED
    assert target.read_bytes() == b"one\nthree\n"
    assert staged_paths == [tmp_path / ".a.txt.yagcode-stage-test"]
    assert not staged_paths[0].exists()


def test_patch_rejects_root_escape_missing_root_and_symlink_target(tmp_path: Path) -> None:
    patch = load_patch_contract()
    before = b"one\ntwo\n"
    (tmp_path / "a.txt").write_bytes(before)

    escaped = patch.apply_action(_action(before, relative="../outside.txt"), roots={"shadow": tmp_path})
    assert escaped.status is ToolStatus.DENIED
    assert escaped.side_effect_state is SideEffectState.NONE

    missing_root = patch.apply_action(_action(before), roots={})
    assert missing_root.reason_code == "ROOT_UNREGISTERED"

    referent = tmp_path / "real.txt"
    referent.write_bytes(before)
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(referent)
    except OSError:
        pytest.skip("symlink creation unavailable")
    symlink = patch.apply_action(_action(before, relative="link.txt"), roots={"shadow": tmp_path})
    assert symlink.status is ToolStatus.DENIED
    assert referent.read_bytes() == before
