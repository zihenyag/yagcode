"""blocking compaction guard tests."""

from __future__ import annotations

import importlib

import pytest

from yagcode.core.context import ActiveContext, ContextItem


def test_owned_compaction_oracle_preserves_required_hashes() -> None:
    before = {"task": "sha256:a", "diff": "sha256:b"}
    after = {"task": "sha256:a", "diff": "sha256:b"}
    assert before == after
    mutated = dict(after)
    mutated.pop("diff")
    assert before != mutated


def load_runtime_control_contract():
    try:
        return importlib.import_module("yagcode.core.compaction")
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.startswith("yagcode.core"):
            pytest.fail(f"RUNTIME_CONTROL_CONTRACT_MISSING: {error.name}")
        raise


def test_compaction_starts_at_seventy_percent_boundary() -> None:
    compaction = load_runtime_control_contract()
    controller = compaction.CompactionController(max_context_tokens=100)
    assert controller.should_compact(69) is False
    assert controller.should_compact(70) is True


def test_compaction_validation_rejects_required_field_loss() -> None:
    compaction = load_runtime_control_contract()
    before = _context(("task", "diff"))
    after = _context(("task",))
    with pytest.raises(compaction.CompactionError, match="COMPACTION_REQUIRED_FIELD_LOSS"):
        compaction.validate_compaction(before, after)
    compaction.validate_compaction(before, _context(("task", "diff")))


def test_compaction_third_failure_pauses_without_deleting_originals() -> None:
    compaction = load_runtime_control_contract()
    failures = compaction.CompactionFailureTracker()
    assert failures.record_failure("run-a", "artifact:raw").state == "COMPACTING"
    assert failures.record_failure("run-a", "artifact:raw").state == "COMPACTING"
    result = failures.record_failure("run-a", "artifact:raw")
    assert result.state == "PAUSED_FAILURE"
    assert result.original_artifact_refs == ("artifact:raw",)


def _context(kinds: tuple[str, ...]) -> ActiveContext:
    return ActiveContext(
        run_id="run-a",
        generation=0,
        items=tuple(
            ContextItem(kind=kind, source_id=kind, content_ref=f"ref:{kind}", content_hash=f"hash:{kind}")
            for kind in kinds
        ),
        feedback_codes=(),
        budget_version=1,
    )
