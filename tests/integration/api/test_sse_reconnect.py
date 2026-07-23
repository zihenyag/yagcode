from __future__ import annotations

import importlib


def test_owned_sse_replay_oracle_replays_only_after_last_sequence() -> None:
    events = [{"sequence": 1}, {"sequence": 2}]
    assert [event["sequence"] for event in events if event["sequence"] > 1] == [2]


def test_sse_reconnect_replays_only_after_last_sequence() -> None:
    events = importlib.import_module("yagcode.api.events")
    schemas = importlib.import_module("yagcode.api.schemas")
    store = events.EventStore(profile_id="p")
    store.append(
        schemas.EventEnvelope(
            profile_id="p",
            sequence=1,
            event_type="run.state",
            generation=0,
            payload={"run_id": "run-1", "state": "RUNNING"},
        )
    )
    store.append(
        schemas.EventEnvelope(
            profile_id="p",
            sequence=2,
            event_type="action.intent",
            generation=1,
            payload={"kind": "run_validation"},
        )
    )

    assert [event.sequence for event in store.replay_after("1")] == [2]
