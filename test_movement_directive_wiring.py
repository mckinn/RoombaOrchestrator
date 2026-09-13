"""
Targeted integration test for the Step 5 movement-directive wiring:
entity_roster population from /arena/event, the ROOMBA_STATE_TOOL
movement_directive extension in llm.py, and its resolution to a
MovementDirective (name -> entity_id) in main.py. Not covered by
smoke_test.py or test_arena_event_wiring.py, which predate this feature.

Same scripted-fake-Anthropic-client approach as test_arena_event_wiring.py
- drives the real FastAPI endpoints end to end, no mocking below the
Anthropic client boundary. See Movement_Concurrency_Plan.md, section 4,
items 1-3, and Planning_Autonomous_Movement.md, Sequenced Plan item 5 /
Open Items item 5.

Run with cwd=refactored/ (needs main.py's import chain, same as
smoke_test.py and test_arena_event_wiring.py).
"""

import os

failures = []


def check(label, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


def fake_message(dialog, pad, should_pause=False, entity_sensitivities=None, movement_directive=None):
    input_data = {
        "dialog": dialog,
        "pad": pad,
        "should_pause": should_pause,
        "entity_sensitivities": entity_sensitivities or [],
    }
    # Only included when not None - matches the schema's "omit entirely if
    # you don't want to move" allowance, and exercises the same code path
    # a real LLM turn with nothing to say about movement would take.
    if movement_directive is not None:
        input_data["movement_directive"] = movement_directive

    class Block:
        type = "tool_use"
        input = input_data

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
    anthropic.Anthropic = FakeClient
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-test-key")

    import main
    from fastapi.testclient import TestClient
    test_client = TestClient(main.app)

    fake = main.client if hasattr(main, "client") else None
    if fake is None:
        import sys
        for modname in ("main", "llm"):
            mod = sys.modules.get(modname)
            if mod is not None and hasattr(mod, "client"):
                fake = mod.client
                break
    assert fake is not None, "could not locate the anthropic client instance"

    # ---- Scenario 1: directive against a rostered entity resolves ----
    # A collision puts chair_07 on the roster (assigned name chair-1, since
    # it's the first collision this session). A same-instance burst (3
    # low-strength hits) then flushes and the LLM issues a directive
    # naming it - the response should carry a resolved MovementDirective
    # with chair_07's entity_id, not the name.
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid = r.json()["session_id"]

    for i in range(1, 3):
        fake.messages.queue(fake_message(
            f"bump {i}", {"pleasure": 0, "arousal": 0, "dominance": 0}
        ))
        test_client.post("/arena/event", json={
            "session_id": sid,
            "event_type": "collision",
            "emotion_states": [{"entity_id": "chair_07", "entity_type": "chair", "emotion": "ambivalence", "strength": 0.1}]
        })

    fake.messages.queue(fake_message(
        "I want a closer look.", {"pleasure": 0.1, "arousal": 0.2, "dominance": 0.0},
        movement_directive={"target_name": "chair-1", "direction": "closer", "percent": 40}
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid,
        "event_type": "collision",
        "emotion_states": [{"entity_id": "chair_07", "entity_type": "chair", "emotion": "ambivalence", "strength": 0.1}]
    })
    body = r.json()

    check("scenario1: status 200", r.status_code == 200)
    check("scenario1: flushed (3rd hit)", body.get("flushed") is True)
    check("scenario1: movement_directive present", body.get("movement_directive") is not None)
    if body.get("movement_directive"):
        check("scenario1: resolved to chair_07's entity_id, not the name", body["movement_directive"]["target_entity_id"] == "chair_07")
        check("scenario1: direction passed through", body["movement_directive"]["direction"] == "closer")
        check("scenario1: percent passed through", body["movement_directive"]["percent"] == 40)

    # The roster context actually reached the LLM - check the prompt sent
    # on the flush-producing call named chair-1 by its assigned name.
    last_call = fake.messages.calls[-1]
    check("scenario1: system prompt lists chair-1 in roster context", "chair-1" in last_call["system"])

    # ---- Scenario 2: omitted movement_directive resolves to None ----
    fake.messages.queue(fake_message(
        "Just passing through.", {"pleasure": 0, "arousal": 0, "dominance": 0}
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid,
        "event_type": "enter",
        "emotion_states": []
    })
    body2 = r.json()

    check("scenario2: status 200", r.status_code == 200)
    check("scenario2: movement_directive is None when omitted", body2.get("movement_directive") is None)

    # ---- Scenario 3: directive naming an unknown/hallucinated entity is dropped ----
    fake.messages.queue(fake_message(
        "Let's go check out the lamp.", {"pleasure": 0, "arousal": 0, "dominance": 0},
        movement_directive={"target_name": "lamp-99", "direction": "closer", "percent": 50}
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid,
        "event_type": "enter",
        "emotion_states": []
    })
    body3 = r.json()

    check("scenario3: status 200", r.status_code == 200)
    check("scenario3: unresolvable directive dropped, not errored", body3.get("movement_directive") is None)
    check("scenario3: dialog still came through despite the dropped directive", body3.get("dialog") == "Let's go check out the lamp.")

    # ---- Scenario 4: percent is clamped even if the LLM ignores the schema bounds ----
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid4 = r.json()["session_id"]
    fake.messages.queue(fake_message(
        "bump", {"pleasure": 0, "arousal": 0, "dominance": 0}
    ))
    test_client.post("/arena/event", json={
        "session_id": sid4,
        "event_type": "collision",
        "emotion_states": [{"entity_id": "lamp_01", "entity_type": "lamp", "emotion": "fear", "strength": 0.9}]
    })
    # fear threshold (0.8) crosses on this single hit - lamp-1 is on the roster now.
    fake.messages.queue(fake_message(
        "Get me far away.", {"pleasure": -0.5, "arousal": 0.8, "dominance": -0.5},
        movement_directive={"target_name": "lamp-1", "direction": "further", "percent": 250}
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid4,
        "event_type": "collision",
        "emotion_states": [{"entity_id": "lamp_01", "entity_type": "lamp", "emotion": "fear", "strength": 0.9}]
    })
    body4 = r.json()

    check("scenario4: status 200", r.status_code == 200)
    check("scenario4: movement_directive present", body4.get("movement_directive") is not None)
    if body4.get("movement_directive"):
        check("scenario4: percent clamped to 100, not passed through as 250", body4["movement_directive"]["percent"] == 100)

    # ---- Scenario 5: invalid direction value is dropped defensively ----
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid5 = r.json()["session_id"]
    fake.messages.queue(fake_message(
        "bump", {"pleasure": 0, "arousal": 0, "dominance": 0}
    ))
    test_client.post("/arena/event", json={
        "session_id": sid5,
        "event_type": "collision",
        "emotion_states": [{"entity_id": "couch_01", "entity_type": "couch", "emotion": "fear", "strength": 0.9}]
    })
    fake.messages.queue(fake_message(
        "Hmm.", {"pleasure": 0, "arousal": 0, "dominance": 0},
        movement_directive={"target_name": "couch-1", "direction": "sideways", "percent": 50}
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid5,
        "event_type": "collision",
        "emotion_states": [{"entity_id": "couch_01", "entity_type": "couch", "emotion": "fear", "strength": 0.9}]
    })
    body5 = r.json()

    check("scenario5: status 200", r.status_code == 200)
    check("scenario5: invalid direction dropped, no crash", body5.get("movement_directive") is None)

    # ---- Scenario 6: proximity_threshold does NOT populate the roster ----
    # An entity seen only via proximity_threshold should never become
    # nameable/targetable - the hard rule from Movement_Concurrency_Plan.md
    # section 4 item 2 ("if the Roomba has not run into an entity, it for
    # all intents and purposes does not exist"). Cross proximity_threshold's
    # own rollup with a single strong hit, then try to direct a movement
    # at the name it WOULD have gotten had it been a collision - it must
    # fail to resolve, because it was never actually collided with.
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid6 = r.json()["session_id"]
    fake.messages.queue(fake_message(
        "Something's near.", {"pleasure": 0, "arousal": 0, "dominance": 0},
        movement_directive={"target_name": "table-1", "direction": "closer", "percent": 30}
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid6,
        "event_type": "proximity_threshold",
        "emotion_states": [{"entity_id": "table_01", "entity_type": "table", "emotion": "fear", "strength": 0.9}]
    })
    body6 = r.json()

    check("scenario6: status 200", r.status_code == 200)
    check("scenario6: proximity-only entity flushed an LLM turn (fear crosses on one hit)", body6.get("flushed") is True)
    check(
        "scenario6: directive naming the proximity-only entity's would-be name fails to resolve",
        body6.get("movement_directive") is None
    )
    last_call6 = fake.messages.calls[-1]
    check(
        "scenario6: proximity-only entity is NOT listed in the roster context sent to the LLM",
        "table-1" not in last_call6["system"]
    )

    # ---- Scenario 7: the same resolution wiring applies to /therapy/message ----
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid7 = r.json()["session_id"]
    fake.messages.queue(fake_message(
        "bump", {"pleasure": 0, "arousal": 0, "dominance": 0}
    ))
    test_client.post("/arena/event", json={
        "session_id": sid7,
        "event_type": "collision",
        "emotion_states": [{"entity_id": "couch_02", "entity_type": "couch", "emotion": "fear", "strength": 0.9}]
    })
    fake.messages.queue(fake_message(
        "I'd rather move away from it.", {"pleasure": -0.2, "arousal": 0.3, "dominance": -0.1},
        movement_directive={"target_name": "couch-1", "direction": "further", "percent": 60}
    ))
    r = test_client.post("/therapy/message", json={"session_id": sid7, "message": "How are you feeling about the couch?"})
    body7 = r.json()

    check("scenario7: status 200", r.status_code == 200)
    check("scenario7: movement_directive resolves through /therapy/message too", body7.get("movement_directive") is not None)
    if body7.get("movement_directive"):
        check("scenario7: resolved entity_id correct", body7["movement_directive"]["target_entity_id"] == "couch_02")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        raise SystemExit(1)
    print("All movement-directive wiring scenarios passed.")


if __name__ == "__main__":
    run()
