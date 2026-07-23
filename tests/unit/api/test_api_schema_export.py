from __future__ import annotations

import importlib
import json

from pathlib import Path

import pytest


def test_owned_api_schema_oracle_rejects_required_and_extra_mutations() -> None:
    required = {"kind", "state"}
    allowed = {"kind", "state"}
    valid = {"kind": "review", "state": "READY"}
    missing = {"kind": "review"}
    extra = {"kind": "review", "state": "READY", "extra": True}
    assert required.issubset(valid) and set(valid).issubset(allowed)
    assert not required.issubset(missing)
    assert not set(extra).issubset(allowed)


def test_export_api_schemas_check_or_write_and_check(tmp_path: Path) -> None:
    exporter = importlib.import_module("scripts.export_api_schemas")
    target = tmp_path / "contracts" / "api"

    assert exporter.main(["--check-or-write", "--target-dir", str(target)]) == 0
    assert exporter.main(["--check", "--target-dir", str(target)]) == 0

    public_schema = json.loads((target / "public-views.schema.json").read_text())
    event_schema = json.loads((target / "events.schema.json").read_text())
    assert public_schema["$schema"].endswith("2020-12/schema")
    assert event_schema["$schema"].endswith("2020-12/schema")
    assert public_schema["discriminator"]["propertyName"] == "kind"
    for name in ("ReviewView", "RunView", "TaskView", "ProjectView"):
        definition = public_schema["$defs"][name]
        assert definition["additionalProperties"] is False
        assert "kind" in definition["required"]
    assert "JsonValue" not in event_schema.get("$defs", {})
    assert event_schema["properties"]["payload"]["anyOf"]
    for name in ("RunStatePayload", "ActionIntentPayload"):
        assert event_schema["$defs"][name]["additionalProperties"] is False
    review_fixture = json.loads((target / "fixtures" / "review-view.json").read_text())
    event_fixture = json.loads((target / "fixtures" / "run-state-event.json").read_text())
    assert review_fixture["kind"] == "review"
    assert "reviewId" not in review_fixture
    assert event_fixture["event_type"] == "run.state"
    assert "eventType" not in event_fixture
    (target / "fixtures" / "review-view.json").write_text("{}\n")
    assert exporter.main(["--check", "--target-dir", str(target)]) == 1


def test_public_schema_models_reject_mutations() -> None:
    schemas = importlib.import_module("yagcode.api.schemas")

    with pytest.raises(Exception):
        schemas.PUBLIC_VIEW_ADAPTER.validate_python(
            {"review_id": "r", "state": "READY", "generation": 1, "summary": "missing kind"}
        )
    with pytest.raises(Exception):
        schemas.PUBLIC_VIEW_ADAPTER.validate_python(
            {
                "kind": "review",
                "review_id": "r",
                "state": "BOGUS",
                "generation": 1,
                "summary": "bad state",
            }
        )
    with pytest.raises(Exception):
        schemas.PUBLIC_VIEW_ADAPTER.validate_python(
            {
                "kind": "review",
                "reviewId": "r",
                "state": "READY",
                "generation": 1,
                "summary": "camel",
            }
        )
    with pytest.raises(Exception):
        schemas.EVENT_ADAPTER.validate_python(
            {
                "profile_id": "p",
                "sequence": 1,
                "event_type": "run.state",
                "generation": "1",
                "payload": {"run_id": "r", "state": "RUNNING"},
            }
        )
    with pytest.raises(Exception):
        schemas.EVENT_ADAPTER.validate_python(
            {
                "profile_id": "p",
                "sequence": 1,
                "event_type": "run.state",
                "payload": {"run_id": "r", "state": "RUNNING", "open": {"object": True}},
            }
        )
