"""
Standalone assertion-based smoke test for the non-aggregated surface of the
Orchestrator API: /health, /session/start, /therapy/message, /arena/entity,
/arena/event's dirt_progress branch, /session/state, /session/end, and the
404/422 error paths across them.

This replaced an earlier golden-master version of this file that diffed a
JSON dump from an old copy of main.py against the current one - useful once,
during the module-split refactor, but not committed to the repo and not fit
to persist: it depended on a hand-maintained "original/" baseline copy of
old code, and asserted "matches the old behavior" rather than "matches the
intended behavior". This version asserts fixed expected values instead, so
it stands alone as permanent regression coverage with nothing else to
maintain.

Deliberately out of scope here: collision/proximity_threshold and the
event_aggregation Collector they drive. That behavior has its own dedicated
coverage - test_event_aggregation.py (the accumulator logic in isolation)
and test_arena_event_wiring.py (the /arena/event <-> Collector wiring).

Uses the same scripted-fake-Anthropic-client approach as those two, so it
needs no real API key or network call. Run with cwd=the repo root (needs
main.py's import chain to resolve).
"""

import os

failures = []


def check(label, condition, detail=None):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label if detail is None else f"{label} ({detail})")


def fake_message(dialog, pad, should_pause=False, entity_sensitivities=None):
    class Block:
        type = "tool_use"
        input = {
            "dialog": dialog,
            "pad": pad,
            "should_pause": should_pause,
            "entity_sensitivities": entity_sensitivities or [],
        }

    class Message:
        content = [Block()]

    return Message()


class FakeMessages:
    def __init__(self):
        self.calls = []
        self._script = []

    def queue(self, *responses):
        self._script = list(responses)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._script:
            return self._script.pop(0)
        return fake_message("...", {"pleasure": 0, "arousal": 0, "dominance": 0})


class FakeClient:
    def __init__(self, *a, **k):
        self.messages = FakeMessages()


def run():
    import anthropic
    anthropic.Anthropic = FakeClient  # patch before main.py's import chain constructs its client
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-test-key")

    import sys
    import main
    from fastapi.testclient import TestClient
    # raise_server_exceptions=False: an unknown roomba_id currently raises an
    # uncaught ValueError out of load_personality() rather than a handled
    # HTTPException (see the assertion below) - this lets that surface as a
    # 500 response instead of crashing the whole test run.
    test_client = TestClient(main.app, raise_server_exceptions=False)

    fake = None
    for modname in ("main", "llm"):
        mod = sys.modules.get(modname)
        if mod is not None and hasattr(mod, "client"):
            fake = mod.client
            break
    assert fake is not None, "could not locate the anthropic client instance on main or llm"

    ZERO_PAD = {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0}
    DUSTY_DESCRIPTION = "A well-meaning Roomba with an irrational and total terror of couches."

    # ---- /health ----
    r = test_client.get("/health")
    check("health: 200", r.status_code == 200)
    check("health: body", r.json() == {"status": "ok"}, r.json())

    # ---- /session/start, no arena_manifest ----
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    body = r.json()
    check("session_start: 200", r.status_code == 200)
    check("session_start: session_id looks right", body.get("session_id", "").startswith("session_"), body.get("session_id"))
    check("session_start: roomba_name", body.get("roomba_name") == "Dusty", body.get("roomba_name"))
    check("session_start: roomba_description", body.get("roomba_description") == DUSTY_DESCRIPTION)
    check("session_start: initial_pad is zeroed", body.get("initial_pad") == ZERO_PAD, body.get("initial_pad"))
    check(
        "session_start: entity_sensitivities seeded from personalities.json",
        body.get("entity_sensitivities") == [{"entity_type": "couch", "emotion": "fear", "strength": 0.8}],
        body.get("entity_sensitivities"),
    )
    check("session_start: known_entities empty with no manifest", body.get("known_entities") == [])
    sid_basic = body["session_id"]

    # ---- /session/start, with an arena_manifest introducing a new type ----
    r = test_client.post("/session/start", json={
        "roomba_id": "couchaphobe_01",
        "arena_manifest": [{"entity_id": "lamp_01", "entity_type": "lamp"}]
    })
    body = r.json()
    check("session_start+manifest: 200", r.status_code == 200)
    check(
        "session_start+manifest: lamp seeded at zero alongside couch",
        {"entity_type": "lamp", "emotion": "none", "strength": 0.0} in body.get("entity_sensitivities", []),
        body.get("entity_sensitivities"),
    )
    check(
        "session_start+manifest: known_entities carries the manifest entity",
        body.get("known_entities") == [{"entity_id": "lamp_01", "entity_type": "lamp"}],
        body.get("known_entities"),
    )

    # ---- /session/start, unknown roomba_id ----
    # Documents CURRENT behavior, not necessarily desired behavior: this is
    # an uncaught ValueError out of load_personality(), not a handled
    # HTTPException, so it surfaces as a bare 500 rather than a clean 404 or
    # 422 with a useful detail message. Flagged as a pre-existing gap,
    # unrelated to the aggregation wiring - out of scope to fix here.
    r = test_client.post("/session/start", json={"roomba_id": "no_such_personality"})
    check("session_start: unknown roomba_id currently surfaces as an unhandled 500", r.status_code == 500, r.status_code)

    # ---- /therapy/message: override an existing type, add a new one ----
    fake.messages.queue(fake_message(
        "The chair seems fine, actually.",
        {"pleasure": 0.1, "arousal": -0.1, "dominance": 0.2},
        should_pause=False,
        entity_sensitivities=[
            {"entity_type": "couch", "emotion": "fear", "strength": 0.95},
            {"entity_type": "chair", "emotion": "curiosity", "strength": 0.3},
        ],
    ))
    r = test_client.post("/therapy/message", json={"session_id": sid_basic, "message": "How do you feel about the furniture?"})
    body = r.json()
    check("therapy_message: 200", r.status_code == 200)
    check("therapy_message: dialog passthrough", body.get("dialog") == "The chair seems fine, actually.")
    check("therapy_message: pad passthrough", body.get("pad") == {"pleasure": 0.1, "arousal": -0.1, "dominance": 0.2})
    check("therapy_message: should_pause default", body.get("should_pause") is False)
    check(
        "therapy_message: existing type (couch) overwritten in place",
        {"entity_type": "couch", "emotion": "fear", "strength": 0.95} in body.get("entity_sensitivities", []),
        body.get("entity_sensitivities"),
    )
    check(
        "therapy_message: new type (chair) added with the LLM's actual stated value, not seeded at zero",
        {"entity_type": "chair", "emotion": "curiosity", "strength": 0.3} in body.get("entity_sensitivities", []),
        body.get("entity_sensitivities"),
    )

    # ---- /therapy/message, missing session ----
    r = test_client.post("/therapy/message", json={"session_id": "does-not-exist", "message": "hello?"})
    check("therapy_message: missing session is 404", r.status_code == 404, r.status_code)

    # ---- /arena/entity: add then remove, verified via /session/state ----
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid_entity = r.json()["session_id"]

    r = test_client.post("/arena/entity", json={
        "session_id": sid_entity, "action": "added",
        "entity": {"entity_id": "table_01", "entity_type": "table"}
    })
    check("arena_entity add: 200", r.status_code == 200)
    check("arena_entity add: acknowledged", r.json() == {"acknowledged": True})

    r = test_client.get("/session/state", params={"session_id": sid_entity})
    check(
        "arena_entity add: table now in known_entities",
        {"entity_id": "table_01", "entity_type": "table", "emotion": "none", "strength": 0.0}
        in r.json().get("known_entities", []),
        r.json().get("known_entities"),
    )

    r = test_client.post("/arena/entity", json={
        "session_id": sid_entity, "action": "removed",
        "entity": {"entity_id": "table_01", "entity_type": "table"}
    })
    check("arena_entity remove: 200", r.status_code == 200)

    r = test_client.get("/session/state", params={"session_id": sid_entity})
    check(
        "arena_entity remove: table gone from known_entities",
        "table_01" not in {e["entity_id"] for e in r.json().get("known_entities", [])},
        r.json().get("known_entities"),
    )

    # ---- /arena/entity, missing session ----
    r = test_client.post("/arena/entity", json={
        "session_id": "does-not-exist", "action": "added",
        "entity": {"entity_id": "x", "entity_type": "x"}
    })
    check("arena_entity: missing session is 404", r.status_code == 404, r.status_code)

    # ---- /arena/event, dirt_progress (in progress) ----
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid_dirt = r.json()["session_id"]

    fake.messages.queue(fake_message(
        "Making progress!", {"pleasure": 0.2, "arousal": 0.1, "dominance": 0.2},
        should_pause=False, entity_sensitivities=[]
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid_dirt, "event_type": "dirt_progress",
        "percent_complete": 42.0, "is_complete": False
    })
    body = r.json()
    check("dirt_progress: 200", r.status_code == 200)
    check("dirt_progress: dialog passthrough", body.get("dialog") == "Making progress!")
    check("dirt_progress: flushed True", body.get("flushed") is True)
    # "messages" is a live reference to the session's conversation_history,
    # not a snapshot - by the time we inspect it here it already has the
    # assistant reply appended too, so filter to the last USER turn rather
    # than assuming [-1] (same subtlety test_arena_event_wiring.py accounts
    # for already).
    user_msgs = [m["content"] for m in fake.messages.calls[-1]["messages"] if m["role"] == "user"]
    prose = user_msgs[-1]
    check("dirt_progress: prose reflects in-progress phrasing", "pauses mid-clean" in prose and "42" in prose, prose)

    # ---- /arena/event, dirt_progress (complete) ----
    fake.messages.queue(fake_message(
        "All done!", {"pleasure": 0.5, "arousal": 0.0, "dominance": 0.3},
        should_pause=False, entity_sensitivities=[]
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid_dirt, "event_type": "dirt_progress",
        "percent_complete": 97.0, "is_complete": True
    })
    body = r.json()
    check("dirt_progress complete: 200", r.status_code == 200)
    user_msgs = [m["content"] for m in fake.messages.calls[-1]["messages"] if m["role"] == "user"]
    prose = user_msgs[-1]
    check("dirt_progress complete: prose reflects final-sweep phrasing", "finishes a final sweep" in prose and "97" in prose, prose)

    # ---- /arena/event, dirt_progress missing percent_complete ----
    r = test_client.post("/arena/event", json={"session_id": sid_dirt, "event_type": "dirt_progress"})
    check("dirt_progress missing percent_complete: 422", r.status_code == 422, r.status_code)

    # ---- /arena/event, missing session ----
    r = test_client.post("/arena/event", json={
        "session_id": "does-not-exist", "event_type": "dirt_progress",
        "percent_complete": 10.0, "is_complete": False
    })
    check("arena_event: missing session is 404", r.status_code == 404, r.status_code)

    # ---- /session/state, missing session ----
    r = test_client.get("/session/state", params={"session_id": "does-not-exist"})
    check("session_state: missing session is 404", r.status_code == 404, r.status_code)

    # ---- /session/end: message_count reflects exactly the two dirt_progress turns ----
    # sid_dirt has had exactly two successful (user, assistant) turns appended -
    # the two dirt_progress calls above. The missing-percent_complete 422 and
    # the /session/state call append nothing.
    r = test_client.post("/session/end", json={"session_id": sid_dirt})
    check("session_end: 200", r.status_code == 200)
    check("session_end: message_count == 4", r.json().get("message_count") == 4, r.json())

    # ---- /session/end, missing session ----
    r = test_client.post("/session/end", json={"session_id": "does-not-exist"})
    check("session_end: missing session is 404", r.status_code == 404, r.status_code)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("All smoke-test scenarios passed.")


if __name__ == "__main__":
    run()
