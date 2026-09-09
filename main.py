from dotenv import load_dotenv

load_dotenv()

import os
import logging

base_log_level_name = os.getenv("BASE_LOG_LEVEL", "INFO").upper()
base_log_level = getattr(logging, base_log_level_name, logging.INFO)
logging.basicConfig(level=base_log_level, format="%(asctime)s [%(levelname)s] %(message)s")

log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)
print(f"Log Level Names are... {log_level_name}, {base_log_level_name}")

logger = logging.getLogger("roomba_orchestrator")
logger.setLevel(log_level)

import time

from fastapi import FastAPI, HTTPException

from models import (
    PADState,
    EntitySensitivity,
    StartSessionRequest,
    StartSessionResponse,
    TherapyMessageRequest,
    TherapyMessageResponse,
    EndSessionRequest,
    EndSessionResponse,
    SessionStateResponse,
    ArenaEntityRequest,
    ArenaEntityResponse,
    ArenaEventRequest,
    ArenaEventResponse,
)
from personalities import load_personality
from event_prose import render_event_prose, render_report_facts
from llm import call_llm
from session_state import sessions, merge_entity_sensitivities
import event_aggregation

# Event types that always carry populated emotion_states and are routed
# through the Collector instead of being reported to the LLM unconditionally
# - see Planning_Autonomous_Movement.md, Aggregation Model, "Scope".
AGGREGATED_EVENT_TYPES = {"collision", "proximity_threshold"}

app = FastAPI()


@app.get("/health", description="are you alive?")
def health_check():
    return {"status": "ok"}


@app.get("/debug/sessions", description="complete dump of the sessions object")
def debug_sessions():
    return sessions


@app.post("/session/start", response_model=StartSessionResponse, description="Create a new session linked to static personality data")
def start_session(request: StartSessionRequest):
    personality = load_personality('personalities.json', request.roomba_id)
    session_id = f"session_{len(sessions) + 1}"
    initial_pad = PADState(pleasure=0.0, arousal=0.0, dominance=0.0)

    entity_sensitivities = [dict(s) for s in personality.get('initial_entity_sensitivities', [])]
    seen_types = {s['entity_type'] for s in entity_sensitivities}
    for e in (request.arena_manifest or []):
        if e.entity_type not in seen_types:
            seen_types.add(e.entity_type)
            entity_sensitivities.append({"entity_type": e.entity_type, "emotion": "none", "strength": 0.0})

    sessions[session_id] = {
        "personality": personality,  # the system field in the message.
        "conversation_history": [],
        "pad": initial_pad,
        "known_entities": [dict(e) for e in request.arena_manifest] if request.arena_manifest else [],
        "entity_sensitivities": entity_sensitivities,
        "collector": event_aggregation.new_collector(),
    }

    return StartSessionResponse(
        session_id=session_id,
        roomba_name=personality['name'],
        roomba_description=personality['description'],
        initial_pad=initial_pad,
        entity_sensitivities=[EntitySensitivity(**s) for s in entity_sensitivities],
        known_entities=sessions[session_id]["known_entities"]
    )


@app.post("/therapy/message", response_model=TherapyMessageResponse, description="The therapist speaks. The response updates the Roomba's state")
def therapy_message(request: TherapyMessageRequest):
    session = sessions.get(request.session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found")

    session['conversation_history'].append({
        "role": "user",
        "content": request.message
    })

    dialog, pad, entity_sensitivity_updates, should_pause = call_llm(
        session['personality']['system_prompt'],
        session['conversation_history'],
        session['pad'],
        session['entity_sensitivities']
    )

    session['conversation_history'].append({
        "role": "assistant",
        "content": dialog
    })

    session['pad'] = pad
    merge_entity_sensitivities(session, entity_sensitivity_updates)

    return TherapyMessageResponse(
        dialog=dialog,
        pad=pad,
        entity_sensitivities=[EntitySensitivity(**s) for s in session['entity_sensitivities']],
        should_pause=should_pause
    )


@app.get("/session/state", response_model=SessionStateResponse, description="synchronous retrieval of important session state details.")
def session_state(session_id: str):
    session = sessions.get(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionStateResponse(
        session_id=session_id,
        roomba_name=session['personality']['name'],
        personality_id=session['personality']['id'],
        pad=session['pad'],
        known_entities=session['known_entities'],
        entity_sensitivities=[EntitySensitivity(**s) for s in session['entity_sensitivities']]
    )


@app.post("/arena/entity", response_model=ArenaEntityResponse, description="deprecated - capabilities moved to event.")
def arena_entity(request: ArenaEntityRequest):
    session = sessions.get(request.session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"session '{request.session_id}' not found")

    if request.action == "added":
        new_entity = request.entity.model_dump()  # model_dump is a dict replacement
        new_entity['emotion'] = "none"
        new_entity['strength'] = 0.0
        session['known_entities'].append(new_entity)
    elif request.action == "removed":
        session['known_entities'] = [
            e for e in session['known_entities']
            if e['entity_id'] != request.entity.entity_id
        ]

    return ArenaEntityResponse(acknowledged=True)


@app.post("/arena/event", response_model=ArenaEventResponse, description="announce an action on the Roomba by the Arena and entities.")
def arena_event(request: ArenaEventRequest):
    session = sessions.get(request.session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {request.session_id} not found")

    if request.event_type == "dirt_progress":
        # Distinct shape from every other event type - no entity_sensitivities
        # involved at all, purely an aggregate progress announcement. Bypasses
        # render_event_prose (built around the entity+emotion template, which
        # doesn't fit this) and the pre-LLM merge_entity_sensitivities call
        # (nothing reported by Unity to merge). The LLM's own read, applied
        # after the call below, can still shift entity_sensitivities if it
        # chooses to - same as every other event type.
        if request.percent_complete is None:
            raise HTTPException(status_code=422, detail="percent_complete is required for event_type 'dirt_progress'")

        roomba_name = session['personality']['name']
        if request.is_complete:
            event_prose = (
                f"{roomba_name} finishes a final sweep of the room - "
                f"about {request.percent_complete:.0f}% of the reachable dirt has been collected."
            )
        else:
            event_prose = (
                f"{roomba_name} pauses mid-clean, having collected "
                f"about {request.percent_complete:.0f}% of the reachable dirt so far."
            )

        prior_entity_sensitivities = [dict(s) for s in session['entity_sensitivities']]

        session['conversation_history'].append({
            "role": "user",
            "content": event_prose
        })

        dialog, pad, entity_sensitivity_updates, should_pause = call_llm(
            session['personality']['system_prompt'],
            session['conversation_history'],
            session['pad'],
            prior_entity_sensitivities
        )

        session['conversation_history'].append({
            "role": "assistant",
            "content": dialog
        })

        session['pad'] = pad
        merge_entity_sensitivities(session, entity_sensitivity_updates)

        return ArenaEventResponse(
            dialog=dialog,
            pad=pad,
            entity_sensitivities=[EntitySensitivity(**s) for s in session['entity_sensitivities']],
            should_pause=should_pause
        )

    # entity_sensitivities bookkeeping happens unconditionally for every
    # event type here, regardless of whether it goes on to cross an
    # aggregation threshold below - that's a separate concern (see
    # Planning_Autonomous_Movement.md, Aggregation Model). Aggregation here
    # is simple replacement - the newest reported strength/emotion for a
    # given entity_type overwrites whatever was there (see BACKLOG.md #8).
    #
    # I believe the comment below to be incorrect - the initial sensitivity is
    # seeded by the game as 'ambivalence' - this part needs deeper thought.
    # for now it is turned off.
    #
    # New entity_types discovered here seed at zero, per the original
    # decision - a raw physics reading on first contact isn't a
    # narratively meaningful value.
    merge_entity_sensitivities(session, request.emotion_states, seed_new_at_zero=False)

    if request.event_type in AGGREGATED_EVENT_TYPES:
        # Every event here feeds the Collector; only a threshold crossing
        # produces a report and an LLM turn. See Planning_Autonomous_Movement.md,
        # Aggregation Model - this replaces the old unconditional
        # render_event_prose + call_llm for these two event types.
        if not request.emotion_states:
            raise HTTPException(
                status_code=422,
                detail=f"emotion_states cannot be empty for event type '{request.event_type}'"
            )

        now = time.time()
        report = None
        for es in request.emotion_states:
            session['collector'], es_report = event_aggregation.record_event(
                session['collector'], es.entity_type, es.entity_id, es.emotion, es.strength, now
            )
            if es_report is not None:
                # Unity sends exactly one EmotionState per event today (see
                # Planning_Autonomous_Movement.md's Unity-source
                # investigation); if that ever changes and more than one
                # entry triggers a report, the most recent one wins here -
                # revisit if that ever actually happens.
                report = es_report

        if report is None:
            # Accumulated without crossing a threshold this time - no LLM
            # turn, no new dialog or PAD. See Planning_Autonomous_Movement.md,
            # Parking Lot: "response payload needs a lightweight 'still
            # accumulating' shape."
            return ArenaEventResponse(
                dialog="",
                pad=session['pad'],
                entity_sensitivities=[EntitySensitivity(**s) for s in session['entity_sensitivities']],
                should_pause=False,
                flushed=False,
            )

        # Snapshot BEFORE the LLM call - this is the prior state shown to
        # the LLM as context, matching every other call_llm call site.
        prior_entity_sensitivities = [dict(s) for s in session['entity_sensitivities']]
        event_prose = render_report_facts(report)

        logger.debug(f"LLM call - sending event prose: {event_prose!r}")

    else:
        # enter / boundary_encountered are out of the Collector's scope -
        # they can have empty emotion_states (BACKLOG.md #10) and aren't
        # the noisy/repetitive event types this aggregation work targets -
        # so they're still reported to the LLM unconditionally, unchanged
        # from before this change.
        prior_entity_sensitivities = [dict(s) for s in session['entity_sensitivities']]
        try:
            event_prose = render_event_prose(
                request.event_type,
                session['personality']['name'],
                request.emotion_states
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    session['conversation_history'].append({
        "role": "user",
        "content": event_prose
    })

    dialog, pad, entity_sensitivity_updates, should_pause = call_llm(
        session['personality']['system_prompt'],
        session['conversation_history'],
        session['pad'],
        prior_entity_sensitivities
    )

    session['conversation_history'].append({
        "role": "assistant",
        "content": dialog
    })

    session['pad'] = pad
    # LLM's read is applied after Unity's - the LLM has final say per entity_type
    # when it chooses to weigh in, since it has context Unity's physics loop doesn't.
    # New types the LLM introduces (not seen in Unity's report at all) keep their
    # actual stated value - a deliberate narrative report, unlike Unity's raw contact.
    merge_entity_sensitivities(session, entity_sensitivity_updates)

    return ArenaEventResponse(
        dialog=dialog,
        pad=pad,
        entity_sensitivities=[EntitySensitivity(**s) for s in session['entity_sensitivities']],
        should_pause=should_pause
    )


@app.post("/session/end", response_model=EndSessionResponse, description="end a specific session")
def end_session(request: EndSessionRequest):
    session = sessions.get(request.session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found")

    message_count = len(session['conversation_history'])
    del sessions[request.session_id]

    return EndSessionResponse(
        session_id=request.session_id,
        message_count=message_count
    )
