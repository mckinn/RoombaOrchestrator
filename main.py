import json
import anthropic 
from fastapi import FastAPI, HTTPException
from fastapi.params import Body
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

client = anthropic.Anthropic()

sessions = {}

def load_personality(filename, personality_id):
    with open(filename, 'r') as fileloader:
        personality_data = json.load(fileloader)
    for personality in personality_data['personalities']:
        if personality['id'] == personality_id:
            return personality
    raise ValueError(f"Personality '{personality_id}' not found in {filename}")

class StartSessionRequest( BaseModel ):
    personality_id:str

class StartSessionResponse( BaseModel ):
    session_id:str
    roomba_name:str
    roomba_description:str

class TherapyMessageRequest(BaseModel):
    session_id: str
    message: str

class TherapyMessageResponse(BaseModel):
    dialog: str
    mood: str

class EndSessionRequest(BaseModel):
    session_id: str

class EndSessionResponse(BaseModel):
    session_id: str
    message_count: int

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/debug/sessions")
def debug_sessions():
    return sessions

@app.post("/session/start", response_model=StartSessionResponse)
def start_session(request: StartSessionRequest):
    personality = load_personality('personalities.json', request.personality_id)
    session_id = f"session_{len(sessions) + 1}"
    sessions[session_id] = {
        "personality":personality, # the system field in the message.
        "conversation_history":[]
    }

    return StartSessionResponse(
        session_id = session_id, 
        roomba_name = personality['name'], 
        roomba_description = personality['description']

    )

@app.post("/therapy/message", response_model=TherapyMessageResponse)
def therapy_message(request: TherapyMessageRequest):
    session = sessions.get(request.session_id)
    
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found")
    
    session['conversation_history'].append({
        "role": "user",
        "content": request.message
    })

    print (f"--- session --- {session}")

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=session['personality']['system_prompt'],
        messages=session['conversation_history']
    )

    response_text = message.content[0].text
    # print(f"[debug] raw response: {repr(response_text)}")

    cleaned = response_text.strip().strip('`').strip()
    if cleaned.startswith('json'):
        cleaned = cleaned[4:]

    try:
        response_data = json.loads(cleaned)
        dialog = response_data['dialog']
        mood = response_data['mood']
    except json.JSONDecodeError:
        dialog = response_text
        mood = "calm"
        print(f"[debug] JSON parse failed, raw response: {repr(response_text)}")

    session['conversation_history'].append({
        "role": "assistant",
        "content": response_text
    })

    return TherapyMessageResponse(
        dialog=dialog,
        mood=mood
    )

@app.post("/session/end", response_model=EndSessionResponse)
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
