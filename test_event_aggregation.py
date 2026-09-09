"""
Synthetic scenario tests for event_aggregation.py - no FastAPI, no Unity,
no LLM. Each scenario replays a sequence of fabricated events through
record_event() and checks the resulting Collector/Report against the
design agreed in Planning_Autonomous_Movement.md.

Plain assert-based script, consistent with this project's existing
Swagger-manual-testing-by-choice practice (BACKLOG.md #13) - no pytest
dependency introduced.
"""

import event_aggregation as ea


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise AssertionError(label)


def scenario_rollup_many_chairs():
    """10 different chairs, ambivalence 0.3 each -> rollup should trigger
    on the 10th event (cumulative 3.0 meets the ambivalence threshold),
    same_instance should NOT trigger (each entity_id only hit once).

    Spaced 2.0s apart (not 1.0s) so this isolates the rollup trigger from
    all_instances (Instance C, default threshold 6): with instance_stale_
    after_seconds=5.0, 2.0s spacing keeps at most 3 entity_ids "live"
    (5.0 / 2.0 = 2.5, so up to 2 prior neighbors) at any one time, well
    under all_instances' threshold of 6 - at 1.0s spacing, 6 entity_ids
    stay live simultaneously and all_instances fires first, on the 6th
    event, before rollup ever gets a chance to reach 3.0."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()
    report = None
    now = 1000.0
    for i in range(10):
        collector, report = ea.record_event(
            collector, "chair", f"chair_{i:02d}", "ambivalence", 0.3, now, config
        )
        now += 2.0  # well-spaced, not stale, not a burst, and keeps all_instances from tripping first

    check("rollup: report fired on 10th event", report is not None)
    check("rollup: triggered_by.rollup is True", report["triggered_by"]["rollup"] is True)
    check("rollup: triggered_by.same_instance is False", report["triggered_by"]["same_instance"] is False)
    check("rollup: triggered_by.all_instances is False", report["triggered_by"]["all_instances"] is False)
    check("rollup: event_count == 10", report["rollup"]["event_count"] == 10)
    check("rollup: cumulative_strength ~= 3.0", abs(report["rollup"]["cumulative_strength"] - 3.0) < 1e-9)
    check("rollup: max_instance.collision_count == 1", report["max_instance"]["collision_count"] == 1)
    check("rollup: entity_type entry cleared after flush", "chair" not in collector)


def scenario_same_instance_burst():
    """3 hits on the SAME entity_id, low strength, close together in time
    -> same_instance should trigger (instance_count_threshold default is 3),
    rollup should NOT (cumulative stays well under threshold). Only 3 hits,
    not 4 - the collector resets the moment the 3rd hit crosses threshold,
    so a 4th call here would start a brand-new (non-triggering) accumulator
    rather than extending this one."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()
    report = None
    now = 2000.0
    for i in range(3):
        collector, report = ea.record_event(
            collector, "chair", "chair_09", "ambivalence", 0.1, now, config
        )
        now += 0.5

    check("burst: report fired on 3rd hit", report is not None)
    check("burst: triggered_by.same_instance is True", report["triggered_by"]["same_instance"] is True)
    check("burst: triggered_by.rollup is False", report["triggered_by"]["rollup"] is False)
    check("burst: triggered_by.all_instances is False", report["triggered_by"]["all_instances"] is False)
    check("burst: max_instance.entity_id == chair_09", report["max_instance"]["entity_id"] == "chair_09")
    check("burst: max_instance.collision_count == 3", report["max_instance"]["collision_count"] == 3)
    check("burst: elapsed_seconds ~= 1.0", abs(report["max_instance"]["elapsed_seconds"] - 1.0) < 1e-9)


def scenario_staleness_reset():
    """2 hits on the same entity_id close together (below the
    instance_count_threshold default of 3), then a 3rd after a long gap ->
    the long gap should reset that instance's count, so the 3rd hit should
    NOT trigger same_instance (count becomes 1, not 3)."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()

    now = 3000.0
    for i in range(2):
        collector, report = ea.record_event(
            collector, "chair", "chair_05", "ambivalence", 0.1, now, config
        )
        now += 0.5
    check("staleness: no report yet after 2 close hits", report is None)

    now += 100.0  # far beyond instance_stale_after_seconds (5.0s default)
    collector, report = ea.record_event(
        collector, "chair", "chair_05", "ambivalence", 0.1, now, config
    )

    check("staleness: no report after the stale-gap hit", report is None)
    instance_state = collector["chair"]["instances"]["chair_05"]
    check("staleness: count reset to 1, not 3", instance_state["collision_count"] == 1)


def scenario_both_trigger_same_event():
    """3 hits, same entity_id, disgust 0.5 each -> the 3rd event should
    cross BOTH the same-instance count threshold (3) and the rollup
    cumulative threshold for disgust (1.5 = 3 x 0.5), on the same event."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()
    report = None
    now = 4000.0
    for i in range(3):
        collector, report = ea.record_event(
            collector, "chair", "chair_02", "disgust", 0.5, now, config
        )
        now += 0.2

    check("both: report fired", report is not None)
    check("both: triggered_by.rollup is True", report["triggered_by"]["rollup"] is True)
    check("both: triggered_by.same_instance is True", report["triggered_by"]["same_instance"] is True)


def scenario_reset_scope_is_whole_type():
    """After a rollup-triggered flush for 'chair', a fresh event for a new
    chair entity_id should start completely clean - no leftover instances,
    rollup event_count back to 1.

    2.0s spacing, same reasoning as scenario_rollup_many_chairs: isolates
    the rollup trigger from all_instances (threshold 6)."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()
    now = 5000.0
    for i in range(10):
        collector, report = ea.record_event(
            collector, "chair", f"chair_{i:02d}", "ambivalence", 0.3, now, config
        )
        now += 2.0
    check("reset-scope: rollup fired as expected", report is not None and report["triggered_by"]["rollup"])
    check("reset-scope: chair cleared immediately after flush", "chair" not in collector)

    collector, report2 = ea.record_event(
        collector, "chair", "chair_99", "ambivalence", 0.05, now, config
    )
    check("reset-scope: no report on the very next low-strength event", report2 is None)
    check("reset-scope: rollup event_count reset to 1", collector["chair"]["rollup"]["event_count"] == 1)
    check("reset-scope: only the new instance is present", list(collector["chair"]["instances"].keys()) == ["chair_99"])


def scenario_total_collisions_excludes_dormant_instances():
    """A one-off touch on chair_A, then nothing else ever hits it again.
    Much later, a genuine rapid burst on chair_B triggers a report (its 3rd
    hit, crossing instance_count_threshold=3). total_collisions should
    reflect only the live burst, not be dragged back in time by chair_A's
    long-dormant, never-revisited entry."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()

    collector, report = ea.record_event(collector, "chair", "chair_A", "ambivalence", 0.05, 0.0, config)
    check("dormant: no report from the lone touch", report is None)

    now = 10000.0  # chair_A is now far past instance_stale_after_seconds
    for i in range(3):
        collector, report = ea.record_event(collector, "chair", "chair_B", "ambivalence", 0.05, now, config)
        now += 0.5

    check("dormant: report fired on chair_B's burst", report is not None)
    check(
        "dormant: total_collisions.collision_count excludes chair_A (3, not 4)",
        report["total_collisions"]["collision_count"] == 3,
    )
    check(
        "dormant: total_collisions.elapsed_seconds reflects the burst (~1.0), not the dormant gap",
        abs(report["total_collisions"]["elapsed_seconds"] - 1.0) < 1e-9,
    )


def scenario_total_collisions_undercount_from_staleness_is_expected():
    """A staleness reset on a revisited entity_id is still expected to make
    total_collisions diverge from rollup.event_count - rollup.event_count
    is the true lifetime total; total_collisions is deliberately scoped to
    currently-live instances only, so this divergence is correct behavior,
    not a bug to chase away.

    chair_C gets only 2 close hits (not 3) before its stale gap, and
    chair_D's burst is 3 hits (not 4) - both capped below
    instance_count_threshold=3 until the specific hit meant to cross it,
    same reasoning as the other scenarios above."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()

    now = 0.0
    for i in range(2):
        collector, report = ea.record_event(collector, "chair", "chair_C", "ambivalence", 0.05, now, config)
        now += 0.5

    now += 100.0  # stale gap - chair_C's own count resets on its next hit
    collector, report = ea.record_event(collector, "chair", "chair_C", "ambivalence", 0.05, now, config)

    now += 0.5
    for i in range(3):
        collector, report = ea.record_event(collector, "chair", "chair_D", "ambivalence", 0.05, now, config)
        now += 0.5

    check("undercount: report fired on chair_D's burst", report is not None)
    check("undercount: rollup.event_count is the true total (6)", report["rollup"]["event_count"] == 6)
    check(
        "undercount: total_collisions.collision_count is live-only (4: chair_C's post-reset 1 + chair_D's 3)",
        report["total_collisions"]["collision_count"] == 4,
    )


def scenario_entity_types_are_independent():
    """Hitting 'chair' repeatedly should not affect an independent 'couch' accumulator."""
    config = ea.AggregationConfig()
    collector = ea.new_collector()
    now = 6000.0
    for i in range(3):
        collector, _ = ea.record_event(collector, "chair", f"chair_{i}", "ambivalence", 0.2, now, config)
        now += 1.0

    collector, report = ea.record_event(collector, "couch", "couch_01", "fear", 0.85, now, config)

    check("independence: couch/fear bypasses on one strong hit", report is not None)
    check("independence: report is for couch, not chair", report["entity_type"] == "couch")
    check("independence: chair accumulator untouched", collector["chair"]["rollup"]["event_count"] == 3)


def main():
    scenario_rollup_many_chairs()
    scenario_same_instance_burst()
    scenario_staleness_reset()
    scenario_both_trigger_same_event()
    scenario_reset_scope_is_whole_type()
    scenario_total_collisions_excludes_dormant_instances()
    scenario_total_collisions_undercount_from_staleness_is_expected()
    scenario_entity_types_are_independent()
    print("\nAll event_aggregation scenarios passed.")


if __name__ == "__main__":
    main()
