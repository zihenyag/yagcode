"""command adapter binds RunCommandAction to sandboxed command requests."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from yagcode.domain.actions import RunCommandAction, RunCommandPayload
from yagcode.domain.results import ToolStatus


def _action(
    template: str = "unit",
    *,
    cwd_root_id: str = "shadow",
    cwd: str = "",
    timeout: int = 9_000,
    args: dict[str, str] | None = None,
) -> RunCommandAction:
    return RunCommandAction(
        kind="run_command",
        action_id="cmd-1",
        run_id="run-1",
        generation=0,
        reason_summary="run validation command",
        payload=RunCommandPayload(
            template_id=template,
            arguments=args or {"name": "ok"},
            cwd_root_id=cwd_root_id,
            cwd_relative_path=cwd,
            timeout_ms=timeout,
        ),
    )


def test_owned_template_oracle_rejects_unknown_extra_args_and_caps_timeout() -> None:
    templates = {"unit": ("/usr/bin/true", ("--name={name}",), ("name",), 1_000)}
    assert "missing" not in templates
    assert set({"name", "extra"}) != set(templates["unit"][2])
    assert min(9_000, templates["unit"][3]) == 1_000
    assert templates["unit"][1][0].format(name="ok") == "--name=ok"


def load_command_contract():
    try:
        return importlib.import_module("yagcode.tools.commands")
    except ModuleNotFoundError as error:
        pytest.fail(f"TOOLS_CONTRACT_MISSING: {error.name}")


class FakeSandbox:
    def __init__(self) -> None:
        self.requests = []

    def start_command(self, request, attestation):
        self.requests.append((request, attestation))
        return type("Handle", (), {"started": True, "reason": "PROCESS_STARTED"})()


def _adapter(tmp_path: Path):
    commands = load_command_contract()
    shadow = tmp_path / "shadow"
    temporary = tmp_path / "tmp"
    protected = tmp_path / "protected"
    for directory in (shadow, temporary, protected):
        directory.mkdir()
    sandbox = FakeSandbox()
    adapter = commands.CommandAdapter(
        sandbox=sandbox,
        templates=commands.TemplateRegistry(
            (
                commands.CommandTemplate(
                    "unit",
                    "/usr/bin/true",
                    ("--name={name}",),
                    ("name",),
                    1_000,
                ),
            )
        ),
        shadow_root=shadow,
    )
    return commands, adapter, sandbox, shadow, temporary, protected


def test_registered_command_is_attested_sanitized_and_confined(tmp_path: Path) -> None:
    commands, adapter, sandbox, shadow, temporary, protected = _adapter(tmp_path)
    (shadow / "nested").mkdir()
    attestation = commands.attest_for_tests(shadow, temporary, protected)

    result = adapter.run_action(_action(cwd="nested", timeout=9_000), attestation)

    assert result.status is ToolStatus.SUCCEEDED
    request, observed_attestation = sandbox.requests[0]
    assert observed_attestation is attestation
    assert request.process.executable == "/usr/bin/true"
    assert request.process.argv == ("--name=ok",)
    assert request.cwd == shadow / "nested"
    assert request.environment == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
    assert request.timeout_ms == 1_000


@pytest.mark.parametrize(
    ("action", "expected_reason"),
    [
        (_action("missing"), "COMMAND_TEMPLATE_UNREGISTERED"),
        (_action(args={"name": "ok", "extra": "no"}), "COMMAND_ARGUMENTS_INVALID"),
        (_action(cwd="../outside"), "COMMAND_CWD_UNTRUSTED"),
        (_action(cwd_root_id="real"), "COMMAND_CWD_ROOT_UNSUPPORTED"),
    ],
)
def test_invalid_command_request_never_starts_sandbox(
    tmp_path: Path,
    action: RunCommandAction,
    expected_reason: str,
) -> None:
    _, adapter, sandbox, shadow, temporary, protected = _adapter(tmp_path)
    result = adapter.run_action(action, load_command_contract().attest_for_tests(shadow, temporary, protected))
    assert result.status is ToolStatus.DENIED
    assert result.reason_code == expected_reason
    assert sandbox.requests == []


def test_missing_or_stale_attestation_never_starts_sandbox(tmp_path: Path) -> None:
    commands, adapter, sandbox, shadow, temporary, protected = _adapter(tmp_path)
    result = adapter.run_action(_action(), None)
    assert result.reason_code == "SANDBOX_ATTESTATION_REQUIRED"
    assert sandbox.requests == []

    attestation = commands.attest_for_tests(shadow, temporary, protected)
    # Mutating a scoped root after attestation makes the snapshot stale.
    shadow.rename(tmp_path / "shadow-old")
    shadow.mkdir()
    stale = adapter.run_action(_action(), attestation)
    assert stale.reason_code == "SANDBOX_ATTESTATION_REQUIRED"
    assert sandbox.requests == []
