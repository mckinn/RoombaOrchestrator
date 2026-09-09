"""
The entire boundary with the Anthropic API lives here: the client instance,
the forced tool-use schema (structured-output only - see
Planning_Autonomous_Movement.md's "LLM vs. Agent" vocabulary entry, this is
not agentic tool-calling), and the single call_llm() entry point everything
else in the Orchestrator goes through.
"""

import logging

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

ROOMBA_STATE_TOOL = {
    "name": "report_roomba_state",
    "description": "Report the Roomba's spoken line, updated emotional state, whether it should pause, and any entity sensitivity changes for this turn.",
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
            "should_pause": {
                "type": "boolean",
                "description": "Whether the Roomba should stop moving and hold still right now. This is a genuine decision the Roomba makes for itself, not a mechanical reflex - it can be true because the therapist asked it to stop, because of something that just happened (like a collision), or simply because the Roomba wants to, on its own. A resistant or defiant Roomba might not stop even when asked. Set false otherwise, including when the Roomba is refusing or resisting a request to stop."
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
            }
        },
        "required": ["dialog", "pad", "should_pause"]
    }
}


def build_current_state_context(pad, entity_sensitivities):
    sensitivities_text = ", ".join(
        f"{s['entity_type']}: {s['emotion']} (strength {s['strength']})"
        for s in entity_sensitivities
    ) or "none yet"

    return (
        f"Your current internal state, for your own awareness only - "
        f"never state these numbers aloud, only let them inform your tone:\n"
        f"PAD: pleasure={pad.pleasure}, arousal={pad.arousal}, dominance={pad.dominance}\n"
        f"Your recent feelings toward things that you might bump into: {sensitivities_text}."
        f"If the entity is new to you, we encourage curiosity towards it."
    )


def call_llm(system_prompt, conversation_history, current_pad, current_entity_sensitivities):
    full_system_prompt = (
        system_prompt
        + "\n\n" + "Use the report_roomba_state tool to respond."
        + "\n\n" + PATTERN_SUMMARY_GUIDANCE
        + "\n\n" + build_current_state_context(current_pad, current_entity_sensitivities)
    )

    outgoing_turn = conversation_history[-1] if conversation_history else None
    logger.debug(f"LLM call - sending: {outgoing_turn!r}")
    logger.debug(f"LLM call - sending current_pad: {current_pad!r}")
    logger.debug(f"LLM call - sending current_entity_sensitivities: {current_entity_sensitivities!r}")

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
        return dialog, pad, [], False

    response_data = tool_use_block.input
    logger.debug(f"LLM call - received tool input {response_data!r}")

    try:
        dialog = response_data['dialog']
        pad = PADState(**response_data['pad'])
    except (KeyError, TypeError) as e:
        logger.warning(f"Tool input missing dialog/pad despite schema, raw: {response_data!r} ({e})")
        dialog = "..."
        pad = PADState(pleasure=0.0, arousal=0.0, dominance=0.0)
        return dialog, pad, [], False

    should_pause = response_data.get('should_pause', False)

    try:
        entity_sensitivity_updates = [
            EntitySensitivity(**s) for s in response_data.get('entity_sensitivities', [])
        ]
        logger.debug(f"entity_sensitivities parse succeeded, raw: {response_data.get('entity_sensitivities')!r}, cooked: {entity_sensitivity_updates} ")
    except (TypeError, ValueError):
        entity_sensitivity_updates = []
        logger.warning(f"entity_sensitivities parse failed, raw: {response_data.get('entity_sensitivities')!r}")

    return dialog, pad, entity_sensitivity_updates, should_pause
