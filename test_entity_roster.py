"""
Synthetic scenario tests for entity_roster.py - no FastAPI, no Unity, no
LLM. Each scenario replays a sequence of fabricated collisions through
record_collision() and checks the resulting Roster against the design
agreed in Movement_Concurrency_Plan.md, section 4, item 2.

Plain assert-based script, consistent with test_event_aggregation.py and
this project's existing Swagger-manual-testing-by-choice practice
(per the JIRA backlog) - no pytest dependency introduced.
"""

import json
import entity_roster as er


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise AssertionError(label)


def scenario_first_collision_assigns_a_name():
    """A brand-new entity_id gets a fresh name on first collision, built
    from the type and the next counter value."""
    roster = er.new_roster()
    roster, name = er.record_collision(roster, "chair_01", "chair", 1000.0)

    check("first collision: name is chair-1", name == "chair-1")
    check("first collision: one entry present", len(roster["entries"]) == 1)
    entry = roster["entries"]["chair_01"]
    check("first collision: entity_type stored", entry["entity_type"] == "chair")
    check("first collision: last_encountered stored", entry["last_encountered"] == 1000.0)
    check("first collision: next_index advanced", roster["next_index"] == 2)


def scenario_recollision_refreshes_timestamp_keeps_name():
    """A second collision with an already-known entity_id updates
    last_encountered but never reassigns the name, and does not consume a
    new counter value."""
    roster = er.new_roster()
    roster, name1 = er.record_collision(roster, "chair_01", "chair", 1000.0)
    roster, name2 = er.record_collision(roster, "chair_01", "chair", 1050.0)

    check("recollision: name unchanged", name1 == name2)
    check("recollision: last_encountered refreshed", roster["entries"]["chair_01"]["last_encountered"] == 1050.0)
    check("recollision: next_index not consumed again", roster["next_index"] == 2)
    check("recollision: still only one entry", len(roster["entries"]) == 1)
    
    print(json.dumps(roster, indent=3))


def scenario_names_are_unique_across_types():
    """Two entities of the same entity_type never collide on a name - the
    counter is global, not per-type - and the type is never something the
    name needs to be parsed to recover."""
    roster = er.new_roster()
    roster, name1 = er.record_collision(roster, "chair_01", "chair", 1000.0)
    roster, name2 = er.record_collision(roster, "chair_02", "chair", 1001.0)
    roster, name3 = er.record_collision(roster, "couch_01", "couch", 1002.0)

    check("uniqueness: chair-1 assigned", name1 == "chair-1")
    check("uniqueness: chair-2 assigned", name2 == "chair-2")
    check("uniqueness: couch-3 assigned (global counter, not per-type)", name3 == "couch-3")
    check("uniqueness: all three names distinct", len({name1, name2, name3}) == 3)
    
    print(json.dumps(roster, indent=3))


def scenario_eviction_is_true_lru_by_last_encountered():
    """At capacity, a new collision evicts the entry least recently
    encountered - even if it was NOT the first one ever met - because
    eviction is keyed on last_encountered, not first_encountered."""
    config = er.RosterConfig(capacity=3)
    roster = er.new_roster()

    roster, _ = er.record_collision(roster, "e1", "chair", 1000.0, config)
    roster, _ = er.record_collision(roster, "e2", "chair", 1001.0, config)
    roster, _ = er.record_collision(roster, "e3", "chair", 1002.0, config)
    # e1 is the oldest by first-contact, but touch it again so it's the
    # MOST recently encountered by the time e4 arrives - it should survive.
    roster, _ = er.record_collision(roster, "e1", "chair", 1003.0, config)

    check("eviction: at capacity before new entity", len(roster["entries"]) == 3)

    roster, _ = er.record_collision(roster, "e4", "chair", 1004.0, config)

    check("eviction: still at capacity after eviction+insert", len(roster["entries"]) == 3)
    check("eviction: e1 survives (most recently touched)", "e1" in roster["entries"])
    check("eviction: e2 evicted (least recently touched, not least recently met)", "e2" not in roster["entries"])
    check("eviction: e3 survives", "e3" in roster["entries"])
    check("eviction: e4 present", "e4" in roster["entries"])
    
    print(json.dumps(roster, indent=3))


def scenario_resolve_name_finds_known_entries():
    """resolve_name() returns the full entry for a name currently on the
    roster."""
    roster = er.new_roster()
    roster, name = er.record_collision(roster, "chair_01", "chair", 1000.0)

    resolved = er.resolve_name(roster, name)

    check("resolve: found", resolved is not None)
    check("resolve: entity_id correct", resolved["entity_id"] == "chair_01")
    check("resolve: entity_type correct", resolved["entity_type"] == "chair")
    
    print(json.dumps(roster, indent=3))


def scenario_resolve_name_returns_none_for_unknown_or_evicted():
    """resolve_name() returns None, not an error, for a name that was
    never assigned or has since been evicted - callers must treat this as
    'directive cannot be resolved right now.'"""
    roster = er.new_roster()

    check("resolve unknown: never-assigned name", er.resolve_name(roster, "chair-99") is None)

    config = er.RosterConfig(capacity=1)
    roster, name1 = er.record_collision(roster, "e1", "chair", 1000.0, config)
    roster, _ = er.record_collision(roster, "e2", "chair", 1001.0, config)

    check("resolve unknown: evicted name", er.resolve_name(roster, name1) is None)
    
    print(json.dumps(roster, indent=3))


def scenario_list_entries_orders_most_recent_first():
    """list_entries() presents entries most-recently-encountered first,
    the natural order for the LLM-facing context block."""
    roster = er.new_roster()
    roster, _ = er.record_collision(roster, "e1", "chair", 1000.0)
    roster, _ = er.record_collision(roster, "e2", "chair", 1002.0)
    roster, _ = er.record_collision(roster, "e3", "chair", 1001.0)

    ordered = er.list_entries(roster)

    check("ordering: three entries", len(ordered) == 3)
    check("ordering: e2 first (last_encountered 1002.0)", ordered[0]["entity_id"] == "e2")
    check("ordering: e3 second (last_encountered 1001.0)", ordered[1]["entity_id"] == "e3")
    check("ordering: e1 last (last_encountered 1000.0)", ordered[2]["entity_id"] == "e1")
    
    print(json.dumps(roster, indent=3))


def scenario_record_collision_does_not_mutate_input():
    """Matching event_aggregation.py's convention: record_collision()
    returns a new Roster rather than mutating its input, so a sequence of
    calls is trivially replayable."""
    roster = er.new_roster()
    roster_before = {"entries": dict(roster["entries"]), "next_index": roster["next_index"]}

    er.record_collision(roster, "e1", "chair", 1000.0)

    check("immutability: original roster untouched", roster == roster_before)
    
    print(json.dumps(roster, indent=3))


def main():
    scenario_first_collision_assigns_a_name()
    scenario_recollision_refreshes_timestamp_keeps_name()
    scenario_names_are_unique_across_types()
    scenario_eviction_is_true_lru_by_last_encountered()
    scenario_resolve_name_finds_known_entries()
    scenario_resolve_name_returns_none_for_unknown_or_evicted()
    scenario_list_entries_orders_most_recent_first()
    scenario_record_collision_does_not_mutate_input()
    print("\nAll entity_roster scenarios passed.")


if __name__ == "__main__":
    main()
