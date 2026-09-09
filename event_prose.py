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


def render_report_facts(report):
    """
    Renders an event_aggregation Report as a neutral factual summary for
    the LLM to interpret and react to itself - Sequenced Plan Step 4's
    resolved design (2026-09-08, Planning_Autonomous_Movement.md,
    "Aggregation Model", Option 2: "hand the LLM the facts, let it
    narrate"). Replaces the earlier render_report_prose_placeholder, which
    was always meant to be replaced rather than refined in place.

    Deliberately NOT written in the Roomba's voice, unlike
    render_event_prose above. The reasoning that used to favor
    Orchestrator-authored narration for every turn predates the
    schema/tool-use setup and no longer holds: the LLM already synthesizes
    dialog/PAD from context on every other turn (therapist dialog,
    single-event prose), so handing it the Report's actual numbers instead
    of a pre-decided sentence isn't a new capability, just extending one
    already in use - and avoids an Orchestrator-side template needing to
    cover every combination of the three triggers, which risked flattening
    exactly the emotional variety the 2026-09-08 playtesting round was
    trying to increase (see llm.py's build_current_state_context changes
    from that same round). Only whichever fact lines correspond to the
    trigger(s) that actually fired are included. Deliberately never names
    the specific entity_id involved even when same_instance triggered
    (Aggregation Model's Open Item 2 - resolved here: a bare ID like
    "chair_07" carries no player-facing meaning without spatial/visual
    context to anchor it, so "the same {entity_type}" is as specific as
    this gets). Pairs with llm.py's PATTERN_SUMMARY_GUIDANCE, which tells
    the LLM how to treat a turn shaped like this one.
    """
    entity_type = report["entity_type"]
    triggered_by = report["triggered_by"]
    facts = []

    if triggered_by["rollup"]:
        rollup = report["rollup"]
        facts.append(
            f"- accumulated {rollup['emotion']} response: strength "
            f"{rollup['cumulative_strength']:.2f} total across "
            f"{rollup['event_count']} {entity_type} collisions"
        )

    if triggered_by["same_instance"]:
        max_instance = report["max_instance"]
        facts.append(
            f"- repeated contact with the same {entity_type}: "
            f"{max_instance['collision_count']} times within "
            f"{max_instance['elapsed_seconds']:.1f} seconds"
        )

    if triggered_by["all_instances"]:
        total_collisions = report["total_collisions"]
        facts.append(
            f"- {total_collisions['collision_count']} separate {entity_type} "
            f"collisions within {total_collisions['elapsed_seconds']:.1f} "
            f"seconds, spread across different ones"
        )

    return (
        f"Pattern: repeated physical contact involving {entity_type}.\n"
        + "\n".join(facts)
        + "\nThis is a real pattern, not a single passing bump - notice it "
        "and let it genuinely shape how you feel and what you say."
    )
