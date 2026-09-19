"""
The narrative "story" log - a separable, human-readable journal of what
happened to the Roomba during a session, distinct from ordinary application
logging (see `logger = logging.getLogger("roomba_orchestrator")` elsewhere
in this codebase). Implements `Narrative_Log_Stream_Plan.md` in the Docs
repo.

Design mirrors event_aggregation.py and entity_roster.py's conventions:
rendering functions here are pure (state in, (new_state, line) out, or just
data in, line out) - nothing here reaches into session_state.sessions,
opens a session's file itself at the wrong time, or knows about FastAPI.
main.py owns calling open_session_log/close_session_log at the right
moments and writing whatever a render_*/record_* function returns via
write_line() - that split keeps the actual narration logic replayable and
testable without a running session, same reasoning as those two modules.

Phase 1 (this file, 2026-09-15): dialog (therapist and Roomba), enter/
boundary_encountered/dirt_progress (reusing event_prose's already-rendered
sentences rather than a second template set), collision/proximity with
first-contact + sequential-duplicate suppression, aggregation pattern
reports (naming the actual entity via the roster - deliberately richer than
event_prose.render_report_facts, which stays anonymous for the LLM's sake),
LLM movement directives, and LLM-directed pause AND resume (see
record_pause).

Updated 2026-09-18 (Pause_Redesign_Implementation_Plan.md): the old
should_pause boolean is gone, replaced by a nullable pause_directive
("pause" | "resume" | None) - see models.py and llm.py's ROOMBA_STATE_TOOL.
Resume is now a real, narratable LLM decision, not something with no
corresponding signal - record_pause below narrates both directions.
Managed Pause itself has also been redesigned (see the Docs repo's
Pause_Redesign_Implementation_Plan.md): there is no more auto-pause of any
kind in Unity, so the LLM directive and the Unity-local debug key are the
only two ways a pause can start or end. This module still only narrates
the LLM-directed one - the debug key is invisible to the Orchestrator by
construction and correctly stays that way.

Explicitly out of scope for v1, per Narrative_Log_Stream_Plan.md section 5:
WASD/manual-control narration and journey "stop"/resolved narration (the
latter is now permanent, not just a v1 scoping choice - see the pause
redesign notes above: a settled/abandoned Journey never itself triggers a
pause any more, so there's nothing pause-related to narrate at that
moment).

Phase 2 (not yet implemented): journey_started/journey_distance will need
Unity to report them on the collision event itself, extending EmotionState -
see Narrative_Log_Stream_Plan.md section 6. record_collision_or_proximity's
journey_* parameters already exist for this - Phase 1 callers just omit
them, so wiring Phase 2's data through later needs no signature change.
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("roomba_orchestrator")  # for reporting problems writing the story log itself - never the story content

STORY_LOG_DIR = os.getenv("STORY_LOG_DIR", "story_logs")


def new_story_state():
    """Per-session dedup/transition state - the starting state for a session with nothing narrated yet."""
    return {
        "last_collision_key": None,  # (event_type, entity_id) of the last collision/proximity line actually written
        "was_paused": False,          # tracks pause_directive's effective state so pause/resume each log once per transition, not every turn
    }


def open_session_log(session_id):
    """
    Opens a fresh, session-scoped log file for the story stream -
    Narrative_Log_Stream_Plan.md section 7: resets every session without
    destroying prior sessions' files. The timestamp suffix (not just
    session_id) is what actually guarantees that - session_id alone
    ("session_1", "session_2", ...) is only unique within one Orchestrator
    process's lifetime and would otherwise collide across restarts, since
    `sessions` is an in-memory dict that starts empty every time the process
    starts. Line-buffered (buffering=1) so a line is visible to anything
    tailing the file immediately, not only on close.
    """
    os.makedirs(STORY_LOG_DIR, exist_ok=True)
    # Microsecond resolution (not just seconds) is deliberate - two sessions
    # opened back-to-back in the same process (e.g. a quick restart during
    # testing) can easily land in the same second, which would otherwise
    # silently make the second session append to the first's file instead
    # of getting its own, defeating the "non-destructive across sessions"
    # requirement this function exists to satisfy.
    timestamp = datetime.now(timezone.utc).strftime("%Y.%m.%d-%H.%MZ")
    path = os.path.join(STORY_LOG_DIR, f"{timestamp}_{session_id}.log")
    return open(path, "a", buffering=1)


def close_session_log(log_file):
    if log_file is not None:
        log_file.close()


def write_line(log_file, line):
    """
    Writes one already-rendered narrative line, timestamped, to the given
    session's story log file. A None line (an empty Roomba dialog, a
    suppressed duplicate collision, a pause_directive that isn't a fresh
    transition, ...) is a no-op - callers pass through whatever a
    render_*/record_* function returned without their own None check first.
    """
    if line is None or log_file is None:
        return
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    try:
        log_file.write(f"[{timestamp}] {line}\n")
    except Exception:
        logger.warning("story_log: failed to write a line", exc_info=True)


# ---------------------------------------------------------------------------
# Rendering - pure functions, no I/O. Each returns a line (str) or None.
# ---------------------------------------------------------------------------

def render_session_start(roomba_name):
    return f"{roomba_name} enters the arena."


def render_therapist_dialog(message):
    return f'the therapist says "{message}"'


def render_roomba_dialog(roomba_name, dialog):
    if not dialog:
        # The "still accumulating, no LLM turn happened" ArenaEventResponse
        # shape (flushed=False) has dialog="" - nothing to narrate.
        return None
    return f'{roomba_name} says "{dialog}"'


def render_passthrough(prose):
    """
    For event types the arena_event handler already renders a narrated
    sentence for - enter, boundary_encountered (event_prose.render_event_prose)
    and dirt_progress (main.py's own inline sentences). No reason to
    maintain a second template set for content that's already prose.
    """
    return prose


def record_collision_or_proximity(
    state, event_type, roomba_name, entity_type, entity_id,
    journey_started=False, journey_emotion=None, journey_distance=None,
):
    """
    Renders a collision/proximity narrative line, applying
    Narrative_Log_Stream_Plan.md section 8's noise rule: the first
    occurrence of a given entity_id's event this session is always logged;
    an immediately-repeated hit on the SAME entity_id right after is
    suppressed. state["last_collision_key"] tracks only the single most
    recently logged key, not full history - a different entity in between,
    or the same entity again later (after something else was logged), is
    not treated as a duplicate and is logged again.

    journey_started/journey_emotion/journey_distance are Phase 2 fields,
    not yet populated by Unity - see module docstring. When journey_started
    is true, the richer "starts moving to a distance of..." wording is used
    instead of the plain "collides with" line; Phase 1 callers simply omit
    them and always get the plain line.

    Returns (new_state, line_or_None).
    """
    key = (event_type, entity_id)
    if state["last_collision_key"] == key:
        return state, None

    new_state = dict(state)
    new_state["last_collision_key"] = key

    verb = "collides with" if event_type == "collision" else "senses"
    article = "an" if entity_type[:1].lower() in "aeiou" else "a"

    if journey_started and journey_distance is not None:
        line = (
            f"{roomba_name} {verb} {article} {entity_type}, then starts moving "
            f"to a distance of {journey_distance:.1f} because {roomba_name} feels "
            f"{journey_emotion} about {entity_type}."
        )
    else:
        line = f"{roomba_name} {verb} {article} {entity_type}."

    return new_state, line


def render_pattern_report(roomba_name, report, roster):
    """
    Renders whichever of the Collector's triggered_by flags fired as their
    own line(s) - see event_aggregation.record_event's Report shape.
    Unlike event_prose.render_report_facts (deliberately anonymous, for the
    LLM's sake - see that function's docstring), this is an internal dev
    log, so the same_instance line names the actual entity via the roster,
    matching Narrative_Log_Stream_Plan.md's own example ("chair-01").
    Returns a list of lines (usually one; more than one only if multiple
    triggered_by flags fired on the same report, which the OR-trigger
    design in event_aggregation.py allows but doesn't guarantee).
    """
    entity_type = report["entity_type"]
    triggered_by = report["triggered_by"]
    lines = []

    if triggered_by["same_instance"]:
        max_instance = report["max_instance"]
        entry = roster["entries"].get(max_instance["entity_id"])
        name = entry["name"] if entry is not None else max_instance["entity_id"]
        lines.append(
            f"{roomba_name} collided with {name} {max_instance['collision_count']} "
            f"times and the LLM was informed."
        )

    if triggered_by["all_instances"]:
        total_collisions = report["total_collisions"]
        lines.append(
            f"{roomba_name} has collided with {total_collisions['collision_count']} "
            f"different {entity_type}s and the LLM was informed."
        )

    if triggered_by["rollup"]:
        rollup = report["rollup"]
        lines.append(
            f"{roomba_name}'s {rollup['emotion']} feelings about {entity_type} "
            f"have been building up and the LLM was informed."
        )

    return lines


def render_movement_directive(roomba_name, target_name, direction):
    towards_or_away = "towards" if direction == "closer" else "away from"
    return f"{roomba_name}-LLM directs the roomba to move {towards_or_away} {target_name}."


def record_pause(state, roomba_name, pause_directive):
    """
    Logs a pause or resume line only when pause_directive carries a real
    instruction this turn (not None) AND it actually represents a change
    from the tracked was_paused state - so a personality that keeps
    reasserting "pause" (or "resume") turn after turn doesn't produce a
    repeated line every time.

    Updated 2026-09-18 (Pause_Redesign_Implementation_Plan.md): resume is
    now a real, narratable LLM decision, unlike the old should_pause
    boolean this replaces, which had no corresponding signal for "the
    pause actually ended" at all. The debug key remains the one other way
    a pause can start or end (see module docstring) and is still not
    narrated here - it's Unity-local and the Orchestrator has no
    visibility into it.

    Returns (new_state, line_or_None).
    """
    if pause_directive == "pause" and not state["was_paused"]:
        new_state = dict(state)
        new_state["was_paused"] = True
        return new_state, f"{roomba_name} pauses."

    if pause_directive == "resume" and state["was_paused"]:
        new_state = dict(state)
        new_state["was_paused"] = False
        return new_state, f"{roomba_name} resumes."

    return state, None
