"""
Targeted integration test for the /arena/event <-> event_aggregation wiring
in main.py - NOT covered by smoke_test.py's golden-master comparison (which
only exercises a single sub-threshold collision, i.e. the flushed=False
path). This drives both the no-flush and flush-producing paths through the
real FastAPI endpoint with a scripted fake Anthropic client, and checks the
response shape and the actual LLM input (render_report_facts's output,
Sequenced Plan Step 4's resolved "hand the LLM the facts" design - see
Planning_Autonomous_Movement.md, Aggregation Model) at each step.

Threshold values exercised here match event_aggregation.py's current
defaults as of 2026-09-08: instance_count_threshold (same_instance,
Instance B) = 3, instance_total_collisions_threshold (all_instances,
Instance C) = 6.

Run with cwd=refactored/ (needs main.py's import chain, same as smoke_test.py).
"""

import os

failures = []


def check(label, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


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

    # ---- Scenario 1: rollup-triggered flush on the very first event ----
    # fear threshold is 0.8 (DEFAULT_ROLLUP_THRESHOLDS) - a single 0.85 hit
    # crosses it immediately, same_instance stays far under its threshold (1).
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid = r.json()["session_id"]

    fake.messages.queue(fake_message(
        "That couch again!", {"pleasure": -0.3, "arousal": 0.5, "dominance": -0.2},
        should_pause=False, entity_sensitivities=[]
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid,
        "event_type": "collision",
        "emotion_states": [{"entity_id": "couch_07", "entity_type": "couch", "emotion": "fear", "strength": 0.85}]
    })
    body = r.json()
    check("scenario1: status 200", r.status_code == 200)
    check("scenario1: flushed is True", body.get("flushed") is True)
    check("scenario1: dialog came from the LLM", body.get("dialog") == "That couch again!")
    check("scenario1: pad updated to the LLM's value", body.get("pad") == {"pleasure": -0.3, "arousal": 0.5, "dominance": -0.2})

    last_call = fake.messages.calls[-1]
    # conversation_history's last user-role entry is the rendered report facts
    user_messages = [m for m in last_call["messages"] if m["role"] == "user"]
    prose = user_messages[-1]["content"]
    check("scenario1: facts open with the Pattern header for couch", "Pattern: repeated physical contact involving couch." in prose)
    check(
        "scenario1: facts mention the rollup clause, not the same-instance or all-instances clauses",
        "accumulated fear response" in prose
        and "repeated contact with the same" not in prose
        and "separate couch collisions" not in prose
    )
    check("scenario1: rollup clause reports strength 0.85 across 1 collision", "strength 0.85 total across 1 couch collisions" in prose)

    # ---- Scenario 2: same-instance-triggered flush, no rollup crossing ----
    # ambivalence threshold is 3.0; instance_count_threshold (Instance B) is 3.
    # Three 0.1-strength hits on the same entity_id keep cumulative strength
    # at 0.3 (nowhere near the rollup threshold) while the same-instance count
    # (3) crosses on the 3rd hit. total_collisions is also 3 there (a single
    # entity_id), well under all_instances' threshold of 6, so only
    # same_instance triggers - the B=3/C=6 tuning keeps a single-entity-stuck
    # case from also tripping the all-instances accumulator.
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid2 = r.json()["session_id"]

    responses_seen = []
    for i in range(1, 4):
        fake.messages.queue(fake_message(
            f"Chair bump #{i}", {"pleasure": -0.05 * i, "arousal": 0.05 * i, "dominance": 0.0},
            should_pause=False, entity_sensitivities=[]
        ))
        r = test_client.post("/arena/event", json={
            "session_id": sid2,
            "event_type": "collision",
            "emotion_states": [{"entity_id": "chair_09", "entity_type": "chair", "emotion": "ambivalence", "strength": 0.1}]
        })
        responses_seen.append(r.json())

    check("scenario2: hits 1-2 did not flush", all(resp.get("flushed") is False for resp in responses_seen[:2]))
    check("scenario2: hits 1-2 had empty dialog", all(resp.get("dialog") == "" for resp in responses_seen[:2]))
    check("scenario2: 3rd hit flushed", responses_seen[2].get("flushed") is True)
    check("scenario2: 3rd hit dialog came from the LLM", responses_seen[2].get("dialog") == "Chair bump #3")

    last_call2 = fake.messages.calls[-1]
    user_messages2 = [m for m in last_call2["messages"] if m["role"] == "user"]
    prose2 = user_messages2[-1]["content"]
    check("scenario2: facts open with the Pattern header for chair", "Pattern: repeated physical contact involving chair." in prose2)
    check(
        "scenario2: facts mention the same-instance clause, not the rollup or all-instances clauses",
        "repeated contact with the same chair: 3 times" in prose2
        and "accumulated" not in prose2
        and "separate chair collisions" not in prose2
    )
    check("scenario2: facts never name the specific entity_id (chair_09)", "chair_09" not in prose2)

    # A no-flush response's pad/entity_sensitivities should equal the
    # session's pad/entity_sensitivities as of just before this call (no LLM
    # turn happened) - check hit #2 against what hit #1 left behind.
    check(
        "scenario2: no-flush pad matches the prior (unchanged) session pad",
        responses_seen[1]["pad"] == responses_seen[0]["pad"]
    )

    # ---- Scenario 3: proximity_threshold is aggregated the same way ----
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid3 = r.json()["session_id"]
    r = test_client.post("/arena/event", json={
        "session_id": sid3,
        "event_type": "proximity_threshold",
        "emotion_states": [{"entity_id": "lamp_02", "entity_type": "lamp", "emotion": "curiosity", "strength": 0.2}]
    })
    body3 = r.json()
    check("scenario3: proximity_threshold under threshold does not flush", body3.get("flushed") is False)
    check("scenario3: proximity_threshold under threshold returns 200", r.status_code == 200)

    # ---- Scenario 4: enter/boundary_encountered are untouched by aggregation ----
    fake.messages.queue(fake_message(
        "Hello, arena!", {"pleasure": 0.1, "arousal": 0.1, "dominance": 0.1},
        should_pause=False, entity_sensitivities=[]
    ))
    r = test_client.post("/arena/event", json={
        "session_id": sid3,
        "event_type": "enter",
        "emotion_states": [{"entity_id": "lamp_02", "entity_type": "lamp", "emotion": "curiosity", "strength": 0.1}]
    })
    body4 = r.json()
    check("scenario4: enter event still flushes unconditionally (flushed True)", body4.get("flushed") is True)
    check("scenario4: enter event still calls the LLM directly", body4.get("dialog") == "Hello, arena!")

    # ---- Scenario 5: all-instances-triggered flush (Instance C) ----
    # instance_total_collisions_threshold is 6. Six single hits spread across
    # six distinct entity_ids of the same entity_type never let any one
    # entity_id's count reach same_instance's threshold (3), and curiosity's
    # rollup threshold (2.0) stays well above the cumulative strength (0.6) -
    # only the summed live-instance count (6) crosses. This is the "pinballs
    # between several different lamps" pattern Instance C exists to catch
    # (Planning_Autonomous_Movement.md, Aggregation Model) - same_instance
    # structurally cannot see it, since no single entity_id ever repeats.
    r = test_client.post("/session/start", json={"roomba_id": "couchaphobe_01"})
    sid5 = r.json()["session_id"]

    responses_seen5 = []
    for i in range(1, 7):
        fake.messages.queue(fake_message(
            f"Lamp bump #{i}", {"pleasure": -0.02 * i, "arousal": 0.02 * i, "dominance": 0.0},
            should_pause=False, entity_sensitivities=[]
        ))
        r = test_client.post("/arena/event", json={
            "session_id": sid5,
            "event_type": "collision",
            "emotion_states": [{"entity_id": f"lamp_0{i}", "entity_type": "lamp", "emotion": "curiosity", "strength": 0.1}]
        })
        responses_seen5.append(r.json())

    check("scenario5: hits 1-5 did not flush", all(resp.get("flushed") is False for resp in responses_seen5[:5]))
    check("scenario5: 6th hit (6th distinct entity_id) flushed", responses_seen5[5].get("flushed") is True)
    check("scenario5: 6th hit dialog came from the LLM", responses_seen5[5].get("dialog") == "Lamp bump #6")

    last_call5 = fake.messages.calls[-1]
    user_messages5 = [m for m in last_call5["messages"] if m["role"] == "user"]
    prose5 = user_messages5[-1]["content"]
    check("scenario5: facts open with the Pattern header for lamp", "Pattern: repeated physical contact involving lamp." in prose5)
    check(
        "scenario5: facts mention the all-instances clause, not the rollup or same-instance clauses",
        "6 separate lamp collisions" in prose5
        and "spread across different ones" in prose5
        and "accumulated" not in prose5
        and "repeated contact with the same" not in prose5
    )
    check("scenario5: facts never name a specific entity_id (lamp_01)", "lamp_01" not in prose5)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        raise SystemExit(1)
    print("All arena/event wiring scenarios passed.")


if __name__ == "__main__":
    run()
