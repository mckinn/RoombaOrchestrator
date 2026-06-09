import json
import anthropic 
from fastapi import FastAPI
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

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/session/start", response_model=StartSessionResponse)
def start_session(request: StartSessionRequest):
    personality = load_personality('personalities.json', request.personality_id)
    session_id = f"session_{len(sessions) + 1}"
    sessions[session_id] = {
        "personality":"personality",
        "conversation_history":[]
    }

    return StartSessionResponse(
        session_id = session_id, 
        roomba_name = personality['name'], 
        roomba_description = personality['description']

    )
