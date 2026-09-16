"""
Synthetic scenario tests for story_log.py - no FastAPI, no Unity, no LLM.
Plain assert-based script, consistent with test_event_aggregation.py and
test_entity_roster.py's existing practice (per the JIRA backlog) - no
pytest dependency introduced.
"""

import os
import tempfile

import story_log


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise AssertionError(label)


def scenario_first_collision_is_logged():
    state = story_log.new_story_state()
    state, line = story_log.record_collision_or_proximity(
        state, "collision", "Dusty", "chair", "chair_01"
    )
    check("first collision: line produced", line == "Dusty collides with a chair.")
    check("first collision: last_collision_key set", state["last_collision_key"] == ("collision", "chair_01"))


def scenario_immediate_repeat_is_suppressed():
    state = story_log.new_story_state()
    state, _ = story_log.record_collision_or_proximity(state, "collision", "Dusty", "chair", "chair_01")
    state, line = story_log.record_collision_or_proximity(state, "collision", "Dusty", "chair", "chair_01")
    check("immediate repeat: suppressed (None)", line is None)


def scenario_different_entity_in_between_resets_dedup():
    state = story_log.new_story_state()
    state, line1 = story_log.record_collision_or_proximity(state, "collision", "Dusty", "chair", "chair_01")
    state, line2 = story_log.record_collision_or_proximity(state, "collision", "Dusty", "couch", "couch_01")
    state, line3 = story_log.record_collision_or_proximity(state, "collision", "Dusty", "chair", "chair_01")

    check("different entity in between: first chair logged", line1 is not None)
    check("different entity in between: couch logged", line2 is not None)
    check("different entity in between: chair logged again after couch", line3 is not None)


def scenario_proximity_uses_a_different_verb():
    state = story_log.new_story_state()
    _, line = story_log.record_collision_or_proximity(state, "proximity_threshold", "Dusty", "lamp", "lamp_01")
    check("proximity: uses 'senses'", line == "Dusty senses a lamp.")


def scenario_an_leading_vowel_gets_an_article():
    state = story_log.new_story_state()
    _, line = story_log.record_collision_or_proximity(state, "collision", "Dusty", "ottoman", "ottoman_01")
    check("vowel-leading entity_type: 'an' article", line == "Dusty collides with an ottoman.")


def scenario_journey_started_uses_richer_wording():
    state = story_log.new_story_state()
    _, line = story_log.record_collision_or_proximity(
        state, "collision", "Dusty", "chair", "chair_01",
        journey_started=True, journey_emotion="ambivalence", journey_distance=2.3456,
    )
    check(
        "journey_started: richer wording with rounded distance",
        line == "Dusty collides with a chair, then starts moving to a distance of 2.3 "
                "because Dusty is ambivalence about chair.",
    )


def scenario_journey_started_without_distance_falls_back_to_plain_line():
    state = story_log.new_story_state()
    _, line = story_log.record_collision_or_proximity(
        state, "collision", "Dusty", "chair", "chair_01",
        journey_started=True, journey_emotion="ambivalence", journey_distance=None,
    )
    check("journey_started with no distance: plain line", line == "Dusty collides with a chair.")


def scenario_record_collision_does_not_mutate_input():
    state = story_log.new_story_state()
    state_before = dict(state)
    story_log.record_collision_or_proximity(state, "collision", "Dusty", "chair", "chair_01")
    check("immutability: original state untouched", state == state_before)


def scenario_roomba_dialog_skips_empty():
    check("empty dialog -> None", story_log.render_roomba_dialog("Dusty", "") is None)
    check("non-empty dialog -> quoted line", story_log.render_roomba_dialog("Dusty", "hello") == 'Dusty says "hello"')


def scenario_therapist_and_session_start_lines():
    check("session start line", story_log.render_session_start("Dusty") == "Dusty enters the arena.")
    check(
        "therapist dialog line",
        story_log.render_therapist_dialog("how are you?") == 'the therapist says "how are you?"',
    )


def scenario_pattern_report_same_instance_names_via_roster():
    roster = {"entries": {"chair_01": {"entity_id": "chair_01", "entity_type": "chair", "name": "chair-1", "last_encountered": 10.0}}}
    report = {
        "entity_type": "chair",
        "triggered_by": {"rollup": False, "same_instance": True, "all_instances": False},
        "max_instance": {"entity_id": "chair_01", "collision_count": 3, "elapsed_seconds": 1.2},
    }
    lines = story_log.render_pattern_report("Dusty", report, roster)
    check("pattern report: one line", len(lines) == 1)
    check("pattern report: names via roster", lines[0] == "Dusty collided with chair-1 3 times and the LLM was informed.")


def scenario_pattern_report_falls_back_to_entity_id_if_not_on_roster():
    roster = {"entries": {}}
    report = {
        "entity_type": "chair",
        "triggered_by": {"rollup": False, "same_instance": True, "all_instances": False},
        "max_instance": {"entity_id": "chair_99", "collision_count": 3, "elapsed_seconds": 1.2},
    }
    lines = story_log.render_pattern_report("Dusty", report, roster)
    check("pattern report fallback: uses bare entity_id", lines[0] == "Dusty collided with chair_99 3 times and the LLM was informed.")


def scenario_pattern_report_all_instances_and_rollup():
    roster = {"entries": {}}
    report = {
        "entity_type": "chair",
        "triggered_by": {"rollup": True, "same_instance": False, "all_instances": True},
        "total_collisions": {"collision_count": 7, "elapsed_seconds": 4.0},
        "rollup": {"emotion": "fear", "cumulative_strength": 2.4, "event_count": 5},
    }
    lines = story_log.render_pattern_report("Dusty", report, roster)
    check("pattern report: two lines when two flags fire", len(lines) == 2)
    check("pattern report: all_instances line", "different chairs" in lines[0])
    check("pattern report: rollup line", "fear" in lines[1] and "building up" in lines[1])


def scenario_movement_directive_wording():
    closer = story_log.render_movement_directive("Dusty", "chair-01", "closer")
    further = story_log.render_movement_directive("Dusty", "chair-01", "further")
    check("movement directive: closer -> towards", closer == "Dusty-LLM directs the roomba to move towards chair-01.")
    check("movement directive: further -> away from", further == "Dusty-LLM directs the roomba to move away from chair-01.")


def scenario_pause_transition_logs_once():
    state = story_log.new_story_state()
    state, line1 = story_log.record_pause(state, "Dusty", True)
    state, line2 = story_log.record_pause(state, "Dusty", True)
    check("pause: first True logs", line1 == "Dusty pauses.")
    check("pause: repeated True does not re-log", line2 is None)


def scenario_pause_false_then_true_logs_again():
    state = story_log.new_story_state()
    state, _ = story_log.record_pause(state, "Dusty", True)
    state, resume_line = story_log.record_pause(state, "Dusty", False)
    state, line2 = story_log.record_pause(state, "Dusty", True)
    check("pause: false transition produces no line", resume_line is None)
    check("pause: true again after false logs again", line2 == "Dusty pauses.")


def scenario_record_pause_does_not_mutate_input():
    state = story_log.new_story_state()
    state_before = dict(state)
    story_log.record_pause(state, "Dusty", True)
    check("pause immutability: original state untouched", state == state_before)


def scenario_open_write_close_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        original_dir = story_log.STORY_LOG_DIR
        story_log.STORY_LOG_DIR = tmp
        try:
            log_file = story_log.open_session_log("session_1")
            story_log.write_line(log_file, "Dusty enters the arena.")
            story_log.write_line(log_file, None)  # no-op, must not raise or write a blank line
            story_log.close_session_log(log_file)

            files = os.listdir(tmp)
            check("round trip: exactly one log file created", len(files) == 1)
            check("round trip: filename is session-scoped", files[0].startswith("session_1_"))

            with open(os.path.join(tmp, files[0])) as f:
                contents = f.read()
            check("round trip: one line written", contents.count("\n") == 1)
            check("round trip: line content present", "Dusty enters the arena." in contents)
            check("round trip: line is timestamped", contents.startswith("["))
        finally:
            story_log.STORY_LOG_DIR = original_dir


def scenario_two_sessions_get_distinct_files():
    with tempfile.TemporaryDirectory() as tmp:
        original_dir = story_log.STORY_LOG_DIR
        story_log.STORY_LOG_DIR = tmp
        try:
            f1 = story_log.open_session_log("session_1")
            f2 = story_log.open_session_log("session_1")  # same session_id, e.g. a process restart
            story_log.close_session_log(f1)
            story_log.close_session_log(f2)
            files = os.listdir(tmp)
            check("distinct files: two files, not one overwritten", len(files) == 2)
        finally:
            story_log.STORY_LOG_DIR = original_dir


def main():
    scenario_first_collision_is_logged()
    scenario_immediate_repeat_is_suppressed()
    scenario_different_entity_in_between_resets_dedup()
    scenario_proximity_uses_a_different_verb()
    scenario_an_leading_vowel_gets_an_article()
    scenario_journey_started_uses_richer_wording()
    scenario_journey_started_without_distance_falls_back_to_plain_line()
    scenario_record_collision_does_not_mutate_input()
    scenario_roomba_dialog_skips_empty()
    scenario_therapist_and_session_start_lines()
    scenario_pattern_report_same_instance_names_via_roster()
    scenario_pattern_report_falls_back_to_entity_id_if_not_on_roster()
    scenario_pattern_report_all_instances_and_rollup()
    scenario_movement_directive_wording()
    scenario_pause_transition_logs_once()
    scenario_pause_false_then_true_logs_again()
    scenario_record_pause_does_not_mutate_input()
    scenario_open_write_close_round_trip()
    scenario_two_sessions_get_distinct_files()
    print("\nAll story_log scenarios passed.")


if __name__ == "__main__":
    main()
