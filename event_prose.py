"""
Renders a raw Arena event into the narrative "prose" sentence that gets
appended to the LLM's conversation history as a user turn.

This is the sensory-filter-layer rendering boundary named in
Planning_Autonomous_Movement.md's Sequenced Plan Step 4 - as that work
grows (Orchestrator-side synthesis of aggregated/batched reports, not just
one-event-at-a-time prose), it grows here.
"""

EVENT_PROSE_PREAMBLE_TEMPLATES = {
    "enter": "{roomba_name} rolls into the arena",
    "proximity_threshold": "{roomba_name} senses something",
    "collision": "{roomba_name} bumps into something",
    "boundary_encountered": "{roomba_name} runs into a wall"
}

EVENT_PROSE_EMOTION_TEMPLATES = {
    "enter": " already aware of the {entity_type}, feeling {emotion}",
    "proximity_threshold": " intuiting the {entity_type} after getting closer and feeling {emotion}",
    "collision": " hitting the {entity_type} and reacting with {emotion}",
    "boundary_encountered": " near the {entity_type}, feeling {emotion}"
}

EVENT_TYPES_REQUIRING_ENTITY = {"proximity_threshold", "collision"}


def render_event_prose(event_type, roomba_name, emotion_states):
    if not emotion_states and event_type in EVENT_TYPES_REQUIRING_ENTITY:
        raise ValueError(f"emotion_states cannot be empty for event type '{event_type}'")

    preamble_template = EVENT_PROSE_PREAMBLE_TEMPLATES[event_type]
    preamble = preamble_template.format(roomba_name=roomba_name)
    template = EVENT_PROSE_EMOTION_TEMPLATES[event_type]
    sentences = [
        template.format(entity_type=es.entity_type, emotion=es.emotion)
        for es in emotion_states
    ]
    return preamble + (", and".join(sentences)) + "."
