"""
The entire boundary with the Anthropic API lives here: the client instance,
the forced tool-use schema (structured-output only - see
Planning_Autonomous_Movement.md's "LLM vs. Agent" vocabulary entry, this is
not agentic tool-calling), and the single call_llm() entry point everything
else in the Orchestrator goes through.
"""

import logging
import json

import anthropic
from fastapi import HTTPException

from models import PADState, EntitySensitivity

logger = logging.getLogger("roomba_orchestrator")

client = anthropic.Anthropic()

# Paired with event_prose.render_report_facts() - Sequenced Plan Step 4's
# resolved design (2026-09-08, Planning_Autonomous_Movement.md, Aggregation
# Model, "Option 2: hand the LLM the facts, let it narrate"). A pattern
# summary is structurally different from every other turn in
# conversation_history (which all read as one narrated sentence) -
# deliberately so, since it's reporting an aggregate the Orchestrator
# already had to summarize, not a single raw sensation - but the LLM still
# needs to know that's what it's looking at and what to do with it.
PATTERN_SUMMARY_GUIDANCE = (
    "Sometimes what happens next is a pattern summary rather than a single "
    "narrated moment - a block of text starting with \"Pattern:\" that "
    "states counts and durations instead of describing an experience in "
    "words. Treat it exactly like anything else that just happened to you: "
    "let the numbers genuinely inform how you feel, and respond in your "
    "own voice - do not just read the numbers back."
)

# Added 2026-09-11 after play-testing surfaced that the LLM would narrate
# distress (e.g. "I keep hitting this table! ... I can't seem to get
# around it!") without ever emitting a movement_directive to act on it,
# even while physically trapped and even with multiple valid roster
# targets available. Root cause: nothing in a personality's system_prompt
# or the tool schema itself ever established that the Roomba HAS a body it
# can act with, only that it can describe how it feels -
# movement_directive's own field description leaned toward "most turns
# should omit it," with no framing connecting a distressing/trapped
# situation to "you can act on this yourself." Deliberately generic here
# rather than added to any one personality's system_prompt, so every
# personality gets physical agency by default - same reasoning as
# PATTERN_SUMMARY_GUIDANCE applying to every personality's aggregated-report
# turns rather than being duplicated per-personality.
#
# Extended 2026-09-13 with the "let your dialog show..." sentence below,
# after a play-test where a trapped Roomba issued movement_directives
# against entities other than the one actually blocking it (see
# Movement_Concurrency_Plan.md's directionality discussion) with no way to
# tell, from the dialog alone, whether that was deliberate or arbitrary.
# Primary intent is narrative, not diagnostic - Steve's framing: this is
# meant to let the therapist (the human on the other end of the chat)
# understand what the Roomba just decided and why, the same way a person
# thinking aloud under pressure would, not to produce a parseable log.
# Deliberately does NOT prescribe a fixed sentence template ("<reason> so
# <choice>") - that would fight each personality's own voice (e.g. Dusty's
# "never break character" register) rather than working within it. If this
# turns out not to be legible enough for diagnosis later, the fallback is a
# separate structured `reason` field on movement_directive itself - not
# attempted yet, on the theory that the simpler, narrative-only version
# might already be enough.
#
# Extended again 2026-09-14 with the final sentence below, after a
# landmark entity (a "rug" seeded into the roster at session start
# specifically to give the LLM a stable escape reference even in a
# single-entity trap - see SessionManager.landmarkIdentity) sat unused
# across 14 movement_directives against the entity actually causing the
# trap, then got picked correctly and immediately (target_name resolved,
# sensible direction/percent) the ONE turn the human therapist suggested it
# by name. That ruled out a plumbing problem - the roster and resolution
# were correct the whole time - and confirmed a prompting gap instead:
# every sentence above frames movement in terms of feeling ("distressing
# you", "curious about"), so a strength-0/ambivalence entity the Roomba has
# no feelings about had no narrative permission to be referenced at all,
# even though it was sitting right there in context. This sentence gives
# that permission directly, deliberately scoped to "isn't working" rather
# than as a general default - the goal is an available fallback, not a
# reason to stop reacting to what's actually causing distress.
MOVEMENT_AGENCY_GUIDANCE = (
    "You are not just a voice - you have a physical body and can act on "
    "what you feel, not only describe it. If something you've bumped into "
    "before is distressing you, cornering you, or you simply want away "
    "from it, you can choose to move yourself further from it right now "
    "using movement_directive - don't just say you wish you could escape, "
    "actually move. The same goes in reverse: if you're curious about "
    "something, you can move closer to it. Use movement_directive on any "
    "turn where you've decided to act, not only when explicitly asked to "
    "move. Whenever you do choose to act, let your dialog show what you're "
    "doing and why, in your own voice - not a mechanical report, just "
    "enough that someone listening can follow what you just decided and "
    "what you're hoping it does for you. You don't need to feel anything "
    "about something to use it as a reference point - if you've been "
    "trying to get away from what's bothering you and it isn't working, "
    "moving toward or away from anything else you know the location of, "
    "even something totally ordinary you have no strong feelings about, "
    "can also help you get free. You don't have to wait to be told to try "
    "that."
)

ROOMBA_STATE_TOOL = {
    "name": "report_roomba_state",
    "description": "Report the Roomba's spoken line, updated emotional state, any deliberate pause/resume decision, and any entity sensitivity changes for this turn.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dialog": {
                "type": "string",
                "description": "What the Roomba says out loud, in character, based on everything that has happened so far. Keep it brief - under 25 words."
            },
            "pad": {
                "type": "object",
                "description": "The Roomba's updated emotional state after this turn, on the Mehrabian PAD model. Set all three to reflect current state precisely, not just broad categories.",
                "properties": {
                    "pleasure": {
                        "type": "number", "minimum": -1, "maximum": 1,
                        "description": "How good or bad the Roomba feels. Negative is distressed, positive is content."
                    },
                    "arousal": {
                        "type": "number", "minimum": -1, "maximum": 1,
                        "description": "How activated or calm the Roomba feels. Negative is sluggish or frozen, positive is agitated or hyperactive."
                    },
                    "dominance": {
                        "type": "number", "minimum": -1, "maximum": 1,
                        "description": "How in control or overwhelmed the Roomba feels. Negative is helpless, positive is in charge of the situation."
                    }
                },
                "required": ["pleasure", "arousal", "dominance"]
            },
            # Replaces the old should_pause boolean (2026-09-18 -
            # Pause_Redesign_Implementation_Plan.md). That field had to be
            # actively re-asserted or re-negated every single turn to mean
            # anything, which implicitly asked the model to track a state
            # machine it never actually controlled half of (there was no
            # real resume signal at all). This field asks for the opposite:
            # say nothing on the overwhelming majority of turns, and only
            # speak up at the moment you're actually changing something.
            "pause_directive": {
                "type": "string",
                "enum": ["pause", "resume"],
                "description": (
                    "Only include this field when you are making a deliberate, "
                    "conscious decision to change whether the Roomba is currently "
                    "moving. 'pause' means stop and hold still right now - because "
                    "the therapist asked, because of something that just happened, "
                    "or simply because you want to. 'resume' means start moving "
                    "again, for the same range of reasons. Omit this field entirely "
                    "on every turn where you are not making that decision right now "
                    "- you do not need to track or restate whether the Roomba is "
                    "already paused or already moving; simply act when you decide "
                    "to change it, and say nothing about it otherwise. A resistant "
                    "or defiant Roomba might not pause even when asked, and is not "
                    "obligated to resume just because time has passed or the "
                    "conversation has moved on - resuming, like pausing, has to be "
                    "an actual choice you're making."
                )
            },
            "entity_sensitivities": {
                "type": "array",
                "description": "Only include entries for entity types where the Roomba's feelings have changed as a result of this exchange. Omit entirely, or leave empty, if nothing changed.",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "description": "The kind of thing, e.g. 'couch'."
                        },
                        "emotion": {
                            "type": "string",
                            "enum": ["fear", "ambivalence", "curiosity", "joy", "disgust"],
                            "description": "The emotion the Roomba feels toward this entity type."
                        },
                        "strength": {
                            "type": "number", "minimum": 0, "maximum": 1,
                            "description": "How strong that feeling is."
                        }
                    },
                    "required": ["entity_type", "emotion", "strength"]
                }
            },
            "movement_directive": {
                "type": "object",
                "description": "Choose to physically move closer to or further from something you've bumped into before - use this whenever you've decided to act, especially to escape something distressing or trapping you, or to approach something that interests you. Omit this field only on turns where you're not choosing to move. Only ever use a target_name that appears in your current context below; never invent one.",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "The exact name of a previously-encountered entity, taken from your current context - never a made-up name, and never something you haven't actually bumped into."
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["closer", "further"],
                        "description": "Whether to move closer to, or further from, the target."
                    },
                    "percent": {
                        "type": "number", "minimum": 0, "maximum": 100,
                        "description": "How much closer or further, as a percentage of your current distance from the target. 100 while going closer means moving all the way to touch it; 100 while going further roughly doubles your current distance from it."
                    }
                },
                "required": ["target_name", "direction", "percent"]
            }
        },
        "required": ["dialog", "pad"]
    }
}


def build_current_state_context(pad, entity_sensitivities, known_entity_roster=None):
    sensitivities_text = ", ".join(
        f"{s['entity_type']}: {s['emotion']} (strength {s['strength']})"
        for s in entity_sensitivities
    ) or "none yet"

    # known_entity_roster entries come from entity_roster.list_entries() -
    # see Movement_Concurrency_Plan.md, section 4, item 2. This is the ONLY
    # place the roster is surfaced to the LLM - no separate query tool, per
    # the Step 5 scoping discussion. Names here are the only valid
    # movement_directive.target_name values (see ROOMBA_STATE_TOOL above);
    # an entity never collided with (not on this list) does not exist to
    # the LLM at all, deliberately.
    roster_text = ", ".join(
        f"{e['name']} (a {e['entity_type']})" for e in (known_entity_roster or [])
    ) or "nothing yet"

    return (
        f"Your current internal state, for your own awareness only - "
        f"never state these numbers aloud, only let them inform your tone:\n"
        f"PAD: pleasure={pad.pleasure}, arousal={pad.arousal}, dominance={pad.dominance}\n"
        f"Your recent feelings toward things that you might bump into: {sensitivities_text}."
        f"If the entity is new to you, we encourage curiosity towards it.\n"
        f"Things you've actually bumped into and could choose to move closer to or "
        f"further from right now (see movement_directive): {roster_text}."
    )


def call_llm(system_prompt, conversation_history, current_pad, current_entity_sensitivities, known_entity_roster=None):
    full_system_prompt = (
        system_prompt
        + "\n\n" + "Use the report_roomba_state tool to respond."
        + "\n\n" + PATTERN_SUMMARY_GUIDANCE
        + "\n\n" + MOVEMENT_AGENCY_GUIDANCE
        + "\n\n" + build_current_state_context(current_pad, current_entity_sensitivities, known_entity_roster)
    )

    outgoing_turn = conversation_history[-1] if conversation_history else None
    logger.debug(f"LLM call - sending: {outgoing_turn!r}")
    logger.debug(f"LLM call - sending current_pad: {current_pad!r}")
    logger.debug(f"LLM call - sending current_entity_sensitivities: {current_entity_sensitivities!r}")
    # Added 2026-09-13: the roster is the ONLY thing that determines which
    # target_name values are even choosable for a movement_directive this
    # turn (see build_current_state_context / ROOMBA_STATE_TOOL), but
    # nothing previously logged what it actually contained at decision
    # time. Without this, "why did the LLM pick X instead of Y" could only
    # be reconstructed indirectly from what it chose, never checked against
    # what it was actually offered - e.g. whether the entity currently
    # colliding was even present, and where it ranked (list_entries sorts
    # most-recently-encountered first).
    logger.debug(f"LLM call - roster offered: {known_entity_roster!r}")

    try:
        message = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=1024,
            system=full_system_prompt,
            messages=conversation_history,
            tools=[ROOMBA_STATE_TOOL],
            tool_choice={"type": "tool", "name": "report_roomba_state"}
        )
    except anthropic.APIError as e:
        logger.error(f"Anthropic API call failed: {e}")
        raise HTTPException(status_code=502, detail="LLM call failed, please try again")

    tool_use_block = next(
        (block for block in message.content if block.type == "tool_use"),
        None
    )

    if tool_use_block is None:
        logger.warning(f"No tool_use block in LLM response, raw content: {message.content!r}")
        dialog = "..."
        pad = PADState(pleasure=0.0, arousal=0.0, dominance=0.0)
        # No LLM turn actually happened, so there's no opinion to report -
        # None (not "false") is the correct default now that pause_directive
        # is a genuine tri-state (see models.py's TherapyMessageResponse).
        return dialog, pad, [], None, None

    logger.debug(f"LLM call - response - tool_use_block {tool_use_block}")
    response_data = tool_use_block.input
    logger.debug(f"LLM call - received tool input {response_data!r}")

    try:
        dialog = response_data['dialog']
        pad = PADState(**response_data['pad'])
    except (KeyError, TypeError) as e:
        logger.warning(f"Tool input missing dialog/pad despite schema, raw: {response_data!r} ({e})")
        dialog = "..."
        pad = PADState(pleasure=0.0, arousal=0.0, dominance=0.0)
        return dialog, pad, [], None, None

    # None if omitted (the normal case on most turns) or if the model
    # returned something outside the schema's enum despite tool-use
    # constraints not being a hard guarantee of actual output - see the
    # movement_directive percent-clamping comment below for the same
    # "don't trust the schema alone" reasoning.
    pause_directive = response_data.get('pause_directive')
    if pause_directive not in (None, "pause", "resume"):
        logger.warning(f"pause_directive had an unexpected value, ignoring: {pause_directive!r}")
        pause_directive = None

    try:
        entity_sensitivity_updates = [
            EntitySensitivity(**s) for s in response_data.get('entity_sensitivities', [])
        ]
        logger.debug(f"entity_sensitivities parse succeeded, raw: {response_data.get('entity_sensitivities')!r}, cooked: {entity_sensitivity_updates} ")
    except (TypeError, ValueError):
        entity_sensitivity_updates = []
        logger.warning(f"entity_sensitivities parse failed, raw: {response_data.get('entity_sensitivities')!r}")

    # Parsed and defensively validated here (matching entity_sensitivities'
    # own treatment just above), but NOT resolved to an entity_id - that
    # needs session/roster state this module deliberately doesn't have
    # (see this file's own header comment: "the entire boundary with the
    # Anthropic API", not session-state logic). Resolution happens in
    # main.py via entity_roster.resolve_name(), same split as
    # entity_sensitivity_updates above (parsed here, merged into session
    # state in main.py via session_state.merge_entity_sensitivities).
    # Movement_Concurrency_Plan.md section 4 item 1: percent is clamped to
    # [0, 100] here regardless of what the LLM returned or whether it
    # respected the schema's declared minimum/maximum - JSON Schema
    # constraints on tool input aren't a hard guarantee of the model's
    # actual output.
    raw_movement_directive = None
    raw = response_data.get('movement_directive')
    if raw is not None:
        try:
            target_name = raw['target_name']
            direction = raw['direction']
            percent = float(raw['percent'])
            if not isinstance(target_name, str) or not target_name:
                raise ValueError("target_name must be a non-empty string")
            if direction not in ("closer", "further"):
                raise ValueError(f"direction must be 'closer' or 'further', got {direction!r}")
            percent = max(0.0, min(100.0, percent))
            raw_movement_directive = {
                "target_name": target_name,
                "direction": direction,
                "percent": percent,
            }
            logger.debug(f"movement_directive parse succeeded: {raw_movement_directive!r}")
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"movement_directive parse failed, raw: {raw!r} ({e})")

    return dialog, pad, entity_sensitivity_updates, pause_directive, raw_movement_directive
