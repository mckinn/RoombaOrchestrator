import json
import anthropic
from typing import Optional, List, Literal 
from fastapi import FastAPI, HTTPException
from fastapi.params import Body
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

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

    entity_sensitivities = []
    seen_types =  set()
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
        initial_pad = initial_pad
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

    # print (f"--- session --- {session}")

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=session['personality']['system_prompt'],
        messages=session['conversation_history']
    )

    response_text = message.content[0].text
    print(f"[debug] raw response: {repr(response_text)}")

    cleaned = response_text.strip().strip('`').strip()
    if cleaned.startswith('json'):
        cleaned = cleaned[4:]

    try:
        response_data = json.loads(cleaned)
        dialog = response_data['dialog']
        pad = PADState(**response_data['pad'])
    except (json.JSONDecodeError, KeyError, TypeError):
        dialog = response_text
        pad = PADState(pleasure=0.0, arousal=0.0, dominance=0.0)
        print(f"[debug] JSON parse failed, raw response: {repr(response_text)}")

    session['conversation_history'].append({
        "role": "assistant",
        "content": dialog
    })

    session['pad']=pad

    return TherapyMessageResponse(
        dialog=dialog,
        pad=pad,
        entity_sensitivities = [EntitySensitivity(**s) for s in session['entity_sensitivities']]
    )

@app.get("/session/state", response_model=SessionStateResponse,  description="synchronous retrieval of important session state details.")
def session_state(session_id:str):
    print (f"--- session_id --- {session_id}")
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
        new_entity['emotion'] = "neutral"
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

    for es in request.emotion_states:
        target = next (
            (s for s in session['entity_sensitivities'] if s['entity_type'] == es.entity_type), None
        )
        if target is not None:
            target['emotion'] = es.emotion
            target['strength'] = es.strength
        else:
            session['entity_sensitivities'].append({
                "entity_type" : es.entity_type,
                "emotion": es.emotion,
                "strength": 0.0
            })
    
    # Stub: LLM call not yet implemented (step 8). PAD stays hardcoded at zero
    # until then - only the dialog is real (placeholder-template) prose now.
    try:
        dialog = render_event_prose(
            request.event_type, 
            session['personality']['name'],
            request.emotion_states
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return ArenaEventResponse(
        dialog=dialog,
        pad = PADState( pleasure= 0.0, arousal= 0.0, dominance= 0.0),
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