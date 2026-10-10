"""
Event aggregation / accumulator logic for the sensory-filter layer.

Implements the design in Planning_Autonomous_Movement.md, "Aggregation
Model - resolved design (first iteration)": a per-entity_type Collector
holding two accumulator instances -

  - rollup (Instance A): key = entity_type, measure = cumulative strength
    of whatever emotion is currently associated with that type (overwrite
    semantics, matching entity_sensitivities elsewhere in this codebase),
    threshold = per-emotion.
  - same-instance / stuck (Instance B): key = entity_id, measure =
    collision count, threshold = a small constant. An instance's count
    resets if too much time (instance_stale_after_seconds) has passed since
    its last event, so a slow trickle of hits over a long span never reads
    as "stuck" the way a genuine short burst does. Only Instance B gets
    this staleness reset - Instance A is meant to surface a slow-building
    pattern eventually, regardless of how long it takes, so time-boxing it
    would work against its own purpose.

Either accumulator crossing its threshold (OR, not AND) fires exactly one
Report for that entity_type, carrying both accumulators' current state, and
resets the ENTIRE entity_type's Collector entry - both the rollup and every
per-entity_id count under it, including ones that didn't trigger the flush.
That's a deliberate, accepted tradeoff (see "Reset policy" in the planning
doc), not an oversight.

Design intent: every function here takes plain data in and returns plain
data out (a Collector is a plain nested dict; nothing here reaches into
session_state.sessions or knows about FastAPI/Pydantic). record_event()
does not mutate its input - it returns a new Collector - so a sequence of
calls is trivially replayable and testable without a running session, per
a JIRA backlog concern about aggregation logic being easy to silently
break and hard to catch via manual testing alone.

Scope: this module is meaningful only for event types that always carry a
populated entity_id/emotion/strength - collision and proximity_threshold.
enter, boundary_encountered, and dirt_progress are out of scope; callers
are responsible for not routing those event types here.

Clock: callers should pass `now` as receipt time (e.g. time.time()) rather
than a Unity-side simulation tick, per the planning doc's "Clock" decision.
Tests pass explicit `now` values to make elapsed-time behavior
deterministic without real sleeping.

All threshold values below are placeholders, deliberately picked to be
plausible rather than analytically derived - per the planning doc's Open
Items, real values are expected to come from tuning against actual
gameplay traces once this is wired into the running game.
"""

from dataclasses import dataclass, field
from typing import Optional
import json 
from functools import reduce


DEFAULT_ROLLUP_THRESHOLDS = {
    # Fear is deliberately low - a single strong collision (the initial
    # couch fear strength in personalities.json is 0.8) should be able to
    # cross this in one event, matching "a couch at 0.95 might already
    # exceed the threshold" from the original design discussion.
    "fear": 0.8,
    "disgust": 1.5,
    "curiosity": 2.0,
    "joy": 2.0,
    # Ambivalence is deliberately the highest - "depress neutral emotions
    # like ambivalence without information loss" was an explicit goal.
    "ambivalence": 3.0,
}
DEFAULT_ROLLUP_THRESHOLD_FALLBACK = 2.0  # for any emotion not listed above

DEFAULT_INSTANCE_COUNT_THRESHOLD = 3
DEFAULT_INSTANCE_STALE_AFTER_SECONDS = 5.0

DEFAULT_TOTAL_ENTITY_COLLISIONS = 6

# Repeated float addition of "nice" values like 0.3 drifts slightly below
# the true sum (e.g. ten additions of 0.3 lands on 2.9999999999999996, not
# 3.0), which would silently fail to cross a round-number threshold by a
# hair. This tolerance absorbs that drift without meaningfully loosening
# the threshold itself.
_FLOAT_TOLERANCE = 1e-9


@dataclass
class AggregationConfig:
    rollup_thresholds: dict = field(default_factory=lambda: dict(DEFAULT_ROLLUP_THRESHOLDS))
    rollup_threshold_fallback: float = DEFAULT_ROLLUP_THRESHOLD_FALLBACK
    instance_count_threshold: int = DEFAULT_INSTANCE_COUNT_THRESHOLD
    instance_stale_after_seconds: float = DEFAULT_INSTANCE_STALE_AFTER_SECONDS
    instance_total_collisions_threshold: int = DEFAULT_TOTAL_ENTITY_COLLISIONS

    def rollup_threshold_for(self, emotion):
        return self.rollup_thresholds.get(emotion, self.rollup_threshold_fallback)


def new_collector():
    """An empty Collector - the starting state for a session with nothing accumulated yet."""
    return {}


def record_event(collector, entity_type, entity_id, emotion, strength, now, config=None):
    """
    Record one raw collision/proximity_threshold event into the Collector.

    Returns (updated_collector, report_or_none):
      - updated_collector is a NEW Collector reflecting this event (the
        input `collector` is not mutated).
      - report_or_none is a Report dict if either accumulator crossed
        threshold as a result of this event, else None.

    `now` is required (not defaulted to time.time() here) so callers -
    especially tests - always control the clock explicitly; production
    call sites pass receipt time.
    """
    if config is None:
        config = AggregationConfig()

    collector = {et: _copy_entity_type_entry(entry) for et, entry in collector.items()}

    # print(json.dumps(collector, indent=3))

    entry = collector.get(entity_type)
    if entry is None:
        entry = _new_entity_type_entry(emotion, now)
        collector[entity_type] = entry

    rollup = entry["rollup"]
    rollup["emotion"] = emotion  # overwrite semantics, matching entity_sensitivities elsewhere
    rollup["cumulative_strength"] += strength
    rollup["event_count"] += 1
    rollup["last_event_at"] = now

    instances = entry["instances"]
    instance = instances.get(entity_id)
    if instance is not None and (now - instance["last_event_at"]) > config.instance_stale_after_seconds:
        # Too much time has passed since this entity_id's last hit for the
        # new one to be part of the same episode - start its count over.
        instance = None
    if instance is None:
        instance = {"collision_count": 0, "first_event_at": now, "last_event_at": now}
        instances[entity_id] = instance
    instance["collision_count"] += 1
    instance["last_event_at"] = now

    rollup_triggered = (
        rollup["cumulative_strength"] >= config.rollup_threshold_for(rollup["emotion"]) - _FLOAT_TOLERANCE
    )

    max_instance_id, max_instance = _max_instance(instances)
    same_instance_triggered = (
        max_instance is not None
        and max_instance["collision_count"] >= config.instance_count_threshold
    )


    # Only count instances that are still "live" (not stale) as of this
    # event - a long-dormant entity_id that hasn't been hit again would
    # otherwise drag total_collisions' elapsed_seconds back to whenever it
    # was last touched, misrepresenting a fast recent burst as a slow
    # pattern spanning however long that dormant entry has been sitting
    # there. The just-recorded entity_id is always live by construction
    # (its last_event_at was just set to `now`), so this is never empty.
    live_instances = {
        eid: inst for eid, inst in instances.items()
        if now - inst["last_event_at"] <= config.instance_stale_after_seconds
    }
    total_collisions_count = sum(item["collision_count"] for item in live_instances.values())
    total_collisions_earliest = min(item["first_event_at"] for item in live_instances.values())
    total_collisions_latest = max(item["last_event_at"] for item in live_instances.values())

    all_instances_triggered = ( 
        total_collisions_count is not None 
        and total_collisions_count >= config.instance_total_collisions_threshold 
    )

    if not (rollup_triggered or same_instance_triggered or all_instances_triggered):
        return collector, None

    report = {
        "entity_type": entity_type,
        "triggered_by": {
            "rollup": rollup_triggered,
            "same_instance": same_instance_triggered,
            "all_instances": all_instances_triggered
        },
        "rollup": {
            "emotion": rollup["emotion"],
            "cumulative_strength": rollup["cumulative_strength"],
            "event_count": rollup["event_count"],
        },
        "max_instance": {
            "entity_id": max_instance_id,
            "collision_count": max_instance["collision_count"],
            "elapsed_seconds": max_instance["last_event_at"] - max_instance["first_event_at"],
        },
        "total_collisions": {
            "collision_count": total_collisions_count,
            "elapsed_seconds": total_collisions_latest - total_collisions_earliest,
        },
        "reported_at": now,
    }

    # print(json.dumps(report, indent=3))

    # Reset the WHOLE entity_type entry - rollup and every instance under
    # it, including any that didn't trigger this flush. Accepted tradeoff,
    # not an oversight - see module docstring / planning doc "Reset policy".
    del collector[entity_type]

    return collector, report


def _new_entity_type_entry(emotion, now):
    return {
        "rollup": {
            "emotion": emotion,
            "cumulative_strength": 0.0,
            "event_count": 0,
            "first_event_at": now,
            "last_event_at": now,
        },
        "instances": {},
    }


def _max_instance(instances):
    if not instances:
        return None, None
    max_id = max(instances, key=lambda eid: instances[eid]["collision_count"])
    return max_id, instances[max_id]


def _copy_entity_type_entry(entry):
    return {
        "rollup": dict(entry["rollup"]),
        "instances": {eid: dict(inst) for eid, inst in entry["instances"].items()},
    }
