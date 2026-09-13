"""
Entity roster - the Brain tier's nameable memory of collided-with entities.

Implements the design in Movement_Concurrency_Plan.md, section 4, item 2
("Naming and roster") and Planning_Autonomous_Movement.md, Sequenced Plan
item 5 / Open Items item 5.2. A small, capped, Orchestrator-side structure
that exists for exactly one reason: giving the LLM something stable to
name and refer back to when issuing a movement directive (Sequenced Plan
item 5's ROOMBA_STATE_TOOL extension). It deliberately does NOT duplicate
position data - Unity's JourneyCalculator.activeJourneys already retains
LastKnownPosition indefinitely for every entity ever collided with; this
module only tracks what Unity's reflex tier doesn't: a stable name and
when the entity was last encountered.

This is intentionally a completely separate concept from session_state's
existing `known_entities` (the full arena-membership manifest, populated
from StartSessionRequest.arena_manifest and the now-deprecated
/arena/entity endpoint) - see Planning_Autonomous_Movement.md, Parking Lot,
for that discussion. The two are not meant to be reconciled or merged at
this stage.

Population rule - a hard rule, deliberate game design, not a shortcut:
record_collision() must be called ONLY for `collision` events, never for
`proximity_threshold` or any other event type that happens to carry an
entity_id. Steve's framing: "if the Roomba has not run into an entity, it
for all intents and purposes does not exist." This is also what
guarantees the D-computation dependency in Movement_Concurrency_Plan.md
section 4 item 1 is always satisfiable: roster membership and Unity's
activeJourneys membership are gated on the exact same trigger (a real
collision), so anything the LLM can name is always something Unity can
already compute a target distance for.

Design intent, matching event_aggregation.py's conventions: every function
here takes plain data in and returns plain data out (a Roster is a plain
dict; nothing here reaches into session_state.sessions or knows about
FastAPI/Pydantic). record_collision() does not mutate its input - it
returns a new Roster - so a sequence of calls is trivially replayable and
testable without a running session.

Eviction: true LRU by `last_encountered` only. first_encountered was
considered and explicitly dropped (Planning_Autonomous_Movement.md, Open
Items item 5.2) - nothing depends on it, and it's easy to reintroduce
later if a concrete narrative need for it shows up in play.

Naming: assigned once, at first collision, from a single
continuously-increasing per-session counter, independent of entity_type.
This guarantees uniqueness with no bookkeeping beyond "hand out the next
integer" - no duplicate-checking pass is needed. The name is built as
"{entity_type}-{index}" for human readability in logs/debugging, but
entity_type is always carried as its own separate field on the roster
entry - nothing may ever depend on parsing the type back out of the name
string (Steve's explicit constraint).
"""

from dataclasses import dataclass


DEFAULT_ROSTER_CAPACITY = 10


@dataclass
class RosterConfig:
    capacity: int = DEFAULT_ROSTER_CAPACITY


def new_roster():
    """An empty Roster - the starting state for a session with no collisions yet."""
    return {"entries": {}, "next_index": 1}


def record_collision(roster, entity_id, entity_type, now, config=None):
    """
    Record one `collision` event into the Roster. Callers MUST NOT call this
    for any other event type - see module docstring, "Population rule."

    Returns (updated_roster, name):
      - updated_roster is a NEW Roster reflecting this collision (the input
        `roster` is not mutated).
      - name is the entity's roster name - freshly assigned if this is the
        first time this entity_id has been seen, otherwise its existing,
        unchanged name.

    If entity_id is already on the roster, only `last_encountered` is
    refreshed - name and entity_type are permanent once assigned. If
    entity_id is new and the roster is already at capacity, the entry
    least recently encountered (by `last_encountered`, true LRU - NOT by
    `first_encountered`, which this module doesn't track) is evicted first.
    """
    if config is None:
        config = RosterConfig()

    entries = {eid: dict(entry) for eid, entry in roster["entries"].items()}
    next_index = roster["next_index"]

    existing = entries.get(entity_id)
    if existing is not None:
        existing["last_encountered"] = now
        return {"entries": entries, "next_index": next_index}, existing["name"]

    if len(entries) >= config.capacity:
        oldest_id = min(entries, key=lambda eid: entries[eid]["last_encountered"])
        del entries[oldest_id]

    name = f"{entity_type}-{next_index}"
    entries[entity_id] = {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "name": name,
        "last_encountered": now,
    }
    next_index += 1

    return {"entries": entries, "next_index": next_index}, name


def resolve_name(roster, name):
    """
    Look up the roster entry for a given name, or None if no entry with
    that name currently exists - e.g. the LLM referenced something that
    has since been evicted, or hallucinated a name that was never assigned.
    Callers (Sequenced Plan item 5's directive-resolution logic) must treat
    None as "directive cannot be resolved right now," not as an error.
    """
    for entry in roster["entries"].values():
        if entry["name"] == name:
            return dict(entry)
    return None


def list_entries(roster):
    """
    Roster entries as a list, most-recently-encountered first - the
    natural order to present to the LLM (build_current_state_context in
    llm.py), and incidentally the same order eviction would remove them in
    reverse.
    """
    return sorted(
        (dict(entry) for entry in roster["entries"].values()),
        key=lambda entry: entry["last_encountered"],
        reverse=True,
    )
