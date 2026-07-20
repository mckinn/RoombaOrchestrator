import json
import anthropic
import logging
from typing import Optional, List, Literal 
from fastapi import FastAPI, HTTPException
from fastapi.params import Body
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv() 

import os

base_log_level_name = os.getenv("BASE_LOG_LEVEL", "INFO").upper() 
base_log_level = getattr(logging, base_log_level_name, logging.INFO)
logging.basicConfig(level=base_log_level, format="%(asctime)s [%(levelname)s] %(message)s")

log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)
print(f"Log Level Names are... {log_level_name}, {base_log_level_name}")

logger = logging.getLogger("roomba_orchestrator")
logger.setLevel(log_level)

app = FastAPI()

client = anthropic.Anthropic()

sessions = {}

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
    return preamble+(", and".join(sentences))+"."

def load_personality(filename, personality_id):
    with open(filename, 'r') as fileloader:
        personality_data = json.load(fileloader)
    for personality in personality_data['personalities']:
        if personality['id'] == personality_id:
            return personality
    raise ValueError(f"Personality '{personality_id}' not found in {filename}")

RESPONSE_FORMAT_INSTRUCTIONS = """Always respond with only a single JSON object, and no text before or after it, matching this exact structure:

{"dialog": "what you say out loud, in character", "pad": {"pleasure": 0.3, "arousal": -0.2, "dominance": 0.1}, "entity_sensitivities": [{"entity_type": "couch", "emotion": "fear", "strength": 0.8}]}

"dialog" is a string: what you say out loud, in character, based on everything that has happened so far.

"pad" describes your current emotional state as three numbers - actual numbers like 0.3 or -0.7, never as strings - each between -1.0 and 1.0:
- pleasure: how good or bad you feel. Negative is distressed, positive is content.
- arousal: how activated or calm you feel. Negative is sluggish or frozen, positive is agitated or hyperactive.
- dominance: how in control or overwhelmed you feel. Negative is helpless, positive is in charge of the situation.
Set all three to reflect your current emotional state precisely, not just broad categories.

"entity_sensitivities" is a list, and can be empty ([]) or omitted entirely if nothing has changed. Only include entries for entity types where your feelings have genuinely changed as a result of this exchange. Each entry has:
- entity_type: the kind of thing, e.g. "couch"
- emotion: the emotion you feel toward it, e.g. "fear"
- strength: a number - not a string - between 0.0 and 1.0 for how strong that feeling is"""

def build_current_state_context(pad, entity_sensitivities):
    sensitivities_text = ", ".join(
        f"{s['entity_type']}: {s['emotion']} (strength {s['strength']})"
        for s in entity_sensitivities
    ) or "none yet"

    return (
        f"\n\nYour current internal state, for your own awareness only - "
        f"never state these numbers aloud, only let them inform your tone:\n"
        f"PAD: pleasure={pad.pleasure}, arousal={pad.arousal}, dominance={pad.dominance}\n"
        f"Known feelings toward entity types: {sensitivities_text}"
    )

def merge_entity_sensitivities(session, updates, seed_new_at_zero = False):
    for u in updates:
        target = next(
            (s for s in session['entity_sensitivities'] if s['entity_type'] == u.entity_type),
            None
        )
        if target is not None:     #override with update
            target['emotion'] = u.emotion
            target['strength'] = u.strength
        
        elif seed_new_at_zero: #create a new 0 value entity sensitivity
            session['entity_sensitivities'].append({
                "entity_type": u.entity_type, 
                "emotion": "none",
                "strength": 0.0
            })
        else:
            session['entity_sensitivities'].append({ # add a new updated values entry
                "entity_type": u.entity_type, 
                "emotion": u.emotion,
                "strength": u.strength
            })

def call_llm(system_prompt, conversation_history, current_pad, current_entity_sensitivities):
    full_system_prompt = (
        system_prompt
        + "\n\n" + RESPONSE_FORMAT_INSTRUCTIONS
        + build_current_state_context(current_pad, current_entity_sensitivities)
    )

    outgoing_turn = conversation_history[-1] if conversation_history else None
    logger.debug(f"LLM call - sending: {outgoing_turn!r}")
    logger.debug(f"LLM call - current_pad: {current_pad!r}")
    logger.debug(f"LLM call - current_entity_sensitivities: {current_entity_sensitivities!r}")

    try:
        message = client.messages.create(
            model = 'claude-sonnet-4-5', 
            max_tokens=1024, 
            system= full_system_prompt, 
            messages= conversation_history
        )
    except anthropic.APIError as e:
        logger.error(f"Anthropic API call failed: {e}")
        raise HTTPException(status_code=502, detail="LLM call failed, please try again")
    
    logger.debug(f"LLM call - received {message.content!r}")
    response_text = message.content[0].text
    logger.debug(f"LLM call - received {response_text!r}")

    cleaned = response_text.strip().strip('`').strip()
    if cleaned.startswith('json'):
        cleaned = cleaned[4:]
    
    try:
        response_data = json.loads(cleaned)
        dialog = response_data['dialog']
        pad= PADState(**response_data['pad'])
    except (json.JSONDecodeError, KeyError, TypeError):
        dialog = response_text
        pad = PADState( pleasure = 0.0, arousal = 0.0, dominance = 0.0)
        logger.warning(f"JSON parse failed for dialog/pad, raw response: {response_text!r}")
        return dialog, pad, []

    try:
        entity_sensitivity_updates = [
            EntitySensitivity(**s) for s in response_data.get('entity_sensitivities',[])
        ]
    except (TypeError, ValueError):
        entity_sensitivity_updates = []
        logger.warning(f"entity_sensitivities parse failed, raw: {response_data.get('entity_sensitivities')!r}")

    return dialog, pad, entity_sensitivity_updates

class Entity(BaseModel):
    entity_id: str
    entity_type: str

class PADState(BaseModel):
    pleasure: float
    arousal: float
    dominance: float

class EntitySensitivity( BaseModel ): #different semantics that emotion, but same fields
    entity_type: str
    emotion: str
    strength: float

class StartSessionRequest( BaseModel ):
    roomba_id: str
    arena_manifest: Optional[List[Entity]] = None

class StartSessionResponse( BaseModel ):
    session_id:str
    roomba_name:str
    roomba_description:str
    initial_pad: PADState
    entity_sensitivities: List[EntitySensitivity]

class TherapyMessageRequest(BaseModel):
    session_id: str
    message: str

class TherapyMessageResponse(BaseModel):
    dialog: str
    pad: PADState
    entity_sensitivities: List[EntitySensitivity] = []

class EndSessionRequest(BaseModel):
    session_id: str

class EndSessionResponse(BaseModel):
    session_id: str
    message_count: int

class SessionStateResponse(BaseModel):
    session_id: str
    roomba_name: str
    personality_id: str
    pad: PADState
    known_entities: list
    entity_sensitivities: List[EntitySensitivity]

class ArenaEntityRequest(BaseModel):
    session_id: str
    action: Literal["added", "removed"]
    entity: Entity

class ArenaEntityResponse(BaseModel):
    acknowledged: bool

class EmotionState(BaseModel):
    entity_id: str
    entity_type: str
    emotion: str
    strength: float

class ArenaEventRequest(BaseModel):
    session_id: str
    event_type: Literal["enter", "proximity_threshold", "collision", "boundary_encountered"]
    emotion_states: List[EmotionState]
    direction: Optional[str] = None

class ArenaEventResponse(BaseModel):
    dialog: str
    pad: PADState
    entity_sensitivities: List[EntitySensitivity]

@app.get("/health",  description="are you alive?")
def health_check():
    return {"status": "ok"}

@app.get("/debug/sessions",  description="complete dump of the sessions object")
def debug_sessions():
    return sessions

@app.post("/session/start", response_model=StartSessionResponse, description="Create a new session linked to static personality data")
def start_session(request: StartSessionRequest):
    personality = load_personality('personalities.json', request.roomba_id)
    session_id = f"session_{len(sessions) + 1}"
    initial_pad = PADState(pleasure=0.0, arousal=0.0, dominance=0.0)

    entity_sensitivities = [dict(s) for s in personality.get('initial_entity_sensitivities', [])]
    seen_types =  {s['entity_type'] for s in entity_sensitivities}
    for e in (request.arena_manifest or []):
        if e.entity_type not in seen_types:
            seen_types.add(e.entity_type)
            entity_sensitivities.append({"entity_type": e.entity_type, "emotion": "none", "strength": 0.0})
    
    sessions[session_id] = {
        "personality":personality, # the system field in the message.
        "conversation_history":[],
        "pad": initial_pad,
        "known_entities": [e.dict() for e in request.arena_manifest] if request.arena_manifest else [],
        "entity_sensitivities": entity_sensitivities 
    }

    return StartSessionResponse(
        session_id = session_id, 
        roomba_name = personality['name'], 
        roomba_description = personality['description'],
        initial_pad = initial_pad,
        entity_sensitivities = [EntitySensitivity(**s) for s in entity_sensitivities]
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

    dialog, pad, entity_sensitivity_updates = call_llm(
        session['personality']['system_prompt'], 
        session['conversation_history'],
        session['pad'],
        session['entity_sensitivities']
        )

    session['conversation_history'].append({
        "role": "assistant",
        "content": dialog
    })

    session['pad']=pad
    merge_entity_sensitivities(session, entity_sensitivity_updates)

    return TherapyMessageResponse(
        dialog=dialog,
        pad=pad,
        entity_sensitivities = [EntitySensitivity(**s) for s in session['entity_sensitivities']]
    )

@app.get("/session/state", response_model=SessionStateResponse,  description="synchronous retrieval of important session state details.")
def session_state(session_id:str):
    session = sessions.get(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    return SessionStateResponse(
        session_id = session_id, 
        roomba_name = session['personality']['name'],
        personality_id = session['personality']['id'],
        pad = session['pad'],
        known_entities = session['known_entities'],
        entity_sensitivities = [EntitySensitivity(**s) for s in session['entity_sensitivities']]
    )

@app.post("/arena/entity", response_model = ArenaEntityResponse, description="deprecated - capabilities moved to event.")
def arena_entity(request: ArenaEntityRequest):
    session = sessions.get( request.session_id )

    if session is None:
        raise HTTPException(status_code=404, detail=f"session '{request.session_id}' not found")
    
    if request.action == "added":
        new_entity = request.entity.dict()
        new_entity['emotion'] = "none"
        new_entity['strength'] = 0.0
        session['known_entities'].append(new_entity)
    elif request.action == "removed":
        session['known_entities'] = [
            e for e in session['known_entities'] 
            if e['entity_id'] != request.entity.entity_id 
        ]

    return ArenaEntityResponse(acknowledged=True)

@app.post("/arena/event", response_model = ArenaEventResponse, description="announce an action on the Roomba by the Arena and entities.")
def arena_event( request: ArenaEventRequest):
    session = sessions.get( request.session_id )

    if session is None:
        raise HTTPException(status_code = 404, detail = f"Session {request.session_id} not found")
    # Stub: prose rendering and LLM call not yet implemented
    # Aggregation is simple replacement for now - the newest reported strength/emotion
    # for a given entity_type overwrites whatever was there. Revisit once there's a
    # running game to observe real aggregation needs against (see BACKLOG.md). 

    # Snapshot Dusty's established feelings BEFORE Unity's report overwrites anything -
    # this is what gets shown to the LLM as context, so it has a real prior state to
    # reconcile against event_prose's (possibly naive/physics-only) narration.
    prior_entity_sensitivities = [dict(s) for s in session['entity_sensitivities']]

    # Aggregation is simple replacement for now - the newest reported strength/emotion
    # for a given entity_type overwrites whatever was there. Revisit once there's a
    # running game to observe real aggregation needs against (see BACKLOG.md).
    # New entity_types discovered here seed at zero, per the original decision -
    # a raw physics reading on first contact isn't a narratively meaningful value.
    merge_entity_sensitivities(session, request.emotion_states, seed_new_at_zero=True)
    
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

    dialog, pad, entity_sensitivity_updates = call_llm(
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
        pad = pad,
        entity_sensitivities= [EntitySensitivity(**s) for s in session['entity_sensitivities']]
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