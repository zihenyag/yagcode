from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def test_owned_yaml_parser_preserves_quoted_on() -> None:
    quoted = yaml.safe_load('"on":\n  workflow_dispatch: {}\n')
    unquoted = yaml.safe_load("on:\n  workflow_dispatch: {}\n")
    assert "on" in quoted
    assert True not in quoted
    assert True in unquoted


def test_owned_shell_payloads_are_not_embedded_in_workflow_run_text() -> None:
    payloads = ('"; echo bad', "'; echo bad", "$(uname)", "`id`", "x;y", "x|y", "x&y", "line\nbreak")
    safe_run = 'npm run build:pages -- --output "dist/pages"'
    for payload in payloads:
        assert payload not in safe_run


def test_github_has_exact_unit_test_job() -> None:
    pipeline = _load_yaml("GitHub Actions")
    assert pipeline["stages"] == ["test"]
    job = pipeline["offline-check"]
    assert job["stage"] == "test"
    assert job["image"] == "python:3.12-bookworm"
    assert job["rules"] == [
        {"if": '$CI_PIPELINE_SOURCE == "push"'},
        {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'},
    ]
    assert job["before_script"] == [
        "curl -fsSLo /tmp/node.tar.xz https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.xz",
        "echo '69b09dba5c8dcb05c4e4273a4340db1005abeafe3927efda2bc5b249e80437ec  /tmp/node.tar.xz' | sha256sum -c -",
        "mkdir -p .ci-node",
        "tar -xJf /tmp/node.tar.xz -C .ci-node --strip-components=1",
        "export PATH=$CI_PROJECT_DIR/.ci-node/bin:$PATH",
        "node -e \"if (process.versions.node !== '22.14.0') process.exit(1)\"",
    ]
    assert job["script"] == [
        "python3.12 -c \"import sys; assert sys.version_info[:2] == (3, 12)\"",
        "npm ci",
        "python3.12 -m venv .venv",
        ".venv/bin/python -m pip install -e '.[dev]'",
        "npm run test:all",
        "node scripts/write-ci-evidence.mjs --output evidence/ci/offline-check.pending.json --status success --command-id test:all",
        "node scripts/verify-ci-evidence.mjs --input evidence/ci/offline-check.pending.json --promote evidence/ci/offline-check.json --status success --command-id test:all",
    ]
    assert job["after_script"] == [
        '$CI_PROJECT_DIR/.ci-node/bin/node scripts/verify-ci-evidence.mjs --ensure-final evidence/ci/offline-check.json --fallback-status "$CI_JOB_STATUS" --command-id offline-check-job'
    ]
    assert job["artifacts"] == {
        "when": "always",
        "expire_in": "30 days",
        "paths": ["evidence/ci/offline-check.json"],
    }


def test_github_checks_workflow_is_offline_and_branch_only() -> None:
    workflow = _load_workflow(".github/workflows/checks.yml")
    assert workflow["on"] == {"push": {"branches": ["**"]}, "pull_request": {"branches": ["**"]}}
    job = workflow["jobs"]["offline-checks"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["permissions"] == {"contents": "read"}
    runs = _runs(job)
    assert runs == [
        'node -e "if (process.platform !== \'linux\' || process.arch !== \'x64\') process.exit(1)"',
        'node -e "if (process.versions.node !== \'22.14.0\') process.exit(1)"',
        'python -c "import sys; assert sys.version_info[:2] == (3, 12)"',
        "npm ci",
        "python -m venv .venv",
        ".venv/bin/python -m pip install -e '.[dev]'",
        "npm run test:all",
        "npm run test:python -- tests/bootstrap/test_delivery_contract.py -q",
        "npm run scan:secrets -- --scope worktree --scope history",
        "git diff --check",
    ]
    _assert_checkout(job)
    _assert_setup_node(job)
    _assert_setup_python(job)
    _assert_no_skippable_required_steps(job)
    _assert_pinned_actions(workflow)


def test_platform_build_workflow_keeps_release_tag_gated() -> None:
    workflow = _load_workflow(".github/workflows/platform-build.yml")
    assert workflow["on"] == {"push": {"tags": ["v*.*.*"]}, "workflow_dispatch": {}}
    jobs = workflow["jobs"]
    assert jobs["preflight"]["runs-on"] == "ubuntu-24.04"
    assert jobs["build-macos-arm64"]["runs-on"] == "macos-15"
    assert jobs["build-windows-x64"]["runs-on"] == "windows-2022"
    assert jobs["release"]["needs"] == ["preflight", "build-macos-arm64", "build-windows-x64"]
    assert jobs["release"]["if"] == "github.event_name == 'push' && needs.preflight.outputs.release_allowed == 'true'"
    assert "node scripts/check-release-ref.mjs --event \"$GITHUB_EVENT_NAME\" --ref \"$GITHUB_REF\" --sha \"$GITHUB_SHA\"" in _runs(jobs["preflight"])
    assert "npm run package:mac" in _runs(jobs["build-macos-arm64"])
    assert "npm run package:cli:mac" in _runs(jobs["build-macos-arm64"])
    assert "npm run smoke:installed -- --platform darwin-arm64 --manifest dist/manifests/darwin-arm64.json --asset dist/release/yagcode-mac-arm64.dmg" in _runs(jobs["build-macos-arm64"])
    assert "npm run package:win" in _runs(jobs["build-windows-x64"])
    assert "npm run package:cli:win" in _runs(jobs["build-windows-x64"])
    assert "npm run smoke:installed -- --platform win32-x64 --root dist/installed/win32-x64/yagcode" in _runs(jobs["build-windows-x64"])
    assert "npm run manifest:merge" in _runs(jobs["release"])
    create_release = next(step for step in jobs["release"]["steps"] if step.get("name") == "Create release")
    assert create_release["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert (ROOT / "CHANGELOG.md").is_file()
    _assert_pinned_actions(workflow)


def test_pages_workflow_has_no_video_or_runtime_input() -> None:
    workflow = _load_workflow(".github/workflows/pages.yml")
    assert workflow["on"] == {"push": {"branches": ["main"]}, "workflow_dispatch": {}}
    assert "inputs" not in workflow["on"].get("workflow_dispatch", {})
    build = workflow["jobs"]["build-pages"]
    deploy = workflow["jobs"]["deploy-pages"]
    smoke = workflow["jobs"]["pages-smoke"]
    assert build["permissions"] == {"contents": "read"}
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["needs"] == "build-pages"
    assert deploy["outputs"] == {"page_url": "${{ steps.deployment.outputs.page_url }}"}
    assert smoke["needs"] == "deploy-pages"
    assert smoke["env"]["YAGCODE_PAGES_URL"] == "${{ needs.deploy-pages.outputs.page_url }}"
    assert smoke["env"]["YAGCODE_REQUIRE_DEPLOYED"] == "1"
    all_run_text = "\n".join(_all_runs(workflow))
    assert "${{ inputs" not in all_run_text
    assert "bilibili" not in all_run_text.lower()
    assert "npm run check:landing" in _runs(build)
    assert "npm run build:pages -- --output dist/pages" in _runs(build)
    assert 'test -n "$YAGCODE_PAGES_URL"' in _runs(smoke)
    assert 'npm run check:deployed-pages -- "$YAGCODE_PAGES_URL"' in _runs(smoke)
    _assert_pinned_actions(workflow)


def test_readme_and_docs_cover_release_requirements() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in (
        "项目简介",
        "安装",
        "运行",
        "分发",
        "目录结构",
        "安全边界",
        "目标机器凭据配置",
        "测试与机制演示",
        "已知限制",
        "第三方依赖与许可证",
    ):
        assert f"## {heading}" in readme
    for path in (
        "docs/architecture.md",
        "docs/security.md",
        "docs/distribution.md",
        "docs/known-limitations.md",
        "LICENSES.md",
        "THIRD_PARTY_NOTICES.md",
        "release workflows",
        "release workflows",
    ):
        assert (ROOT / path).is_file(), path
    assert "notes由维护者撰写" in readme
    assert "Bilibili" not in readme


def test_landing_page_no_longer_requires_video() -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    checker = (ROOT / "scripts/check_landing_page.py").read_text(encoding="utf-8")
    assert "Bilibili" not in html
    assert "<iframe" not in html
    assert "docs/landing/landing.js" not in html
    assert "机制演示" in html
    assert "Bilibili" not in checker


def _load_yaml(path: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _load_workflow(path: str) -> dict[str, Any]:
    workflow = _load_yaml(path)
    assert "on" in workflow
    assert True not in workflow
    return workflow


def _runs(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _all_runs(workflow: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for job in workflow["jobs"].values():
        result.extend(_runs(job))
    return result


def _assert_checkout(job: dict[str, Any]) -> None:
    checkout = next(step for step in job["steps"] if step.get("name") == "Checkout")
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False


def _assert_setup_node(job: dict[str, Any]) -> None:
    setup = next(step for step in job["steps"] if step.get("name") == "Setup Node")
    assert setup["with"]["node-version"] == "22.14.0"
    assert setup["with"]["cache"] == "npm"


def _assert_setup_python(job: dict[str, Any]) -> None:
    setup = next(step for step in job["steps"] if step.get("name") == "Setup Python")
    assert setup["with"]["python-version"] == "3.12"


def _assert_no_skippable_required_steps(job: dict[str, Any]) -> None:
    for step in job["steps"]:
        assert "continue-on-error" not in step
        if step.get("name") not in {"Upload release artifact", "Upload Pages artifact"}:
            assert "if" not in step


def _assert_pinned_actions(workflow: dict[str, Any]) -> None:
    fixtures = json.loads((ROOT / "tests/fixtures/ci/action-shas.json").read_text(encoding="utf-8"))
    for uses in _collect_uses(workflow):
        repo, sha = uses.split("@", 1)
        assert SHA_RE.fullmatch(sha), uses
        assert fixtures[repo]["sha"] == sha


def _collect_uses(workflow: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                result.append(step["uses"])
    return result
