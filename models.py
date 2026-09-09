"""
Pydantic request/response models and the small data-shape classes used
throughout the Orchestrator. Pure data shapes only - no behavior lives here.

This is the closest thing in code to Roomba_Orchestrator_Interface_Contract_v0_4.md -
if you're checking what a request or response looks like on the wire, it's here.
"""

from typing import Optional, List, Literal
from pydantic import BaseModel


class Entity(BaseModel):
    entity_id: str
    entity_type: str


class PADState(BaseModel):
    pleasure: float
    arousal: float
    dominance: float


class EntitySensitivity(BaseModel):  # different semantics than emotion, but same fields
    entity_type: str
    emotion: str
    strength: float


class StartSessionRequest(BaseModel):
    roomba_id: str
    arena_manifest: Optional[List[Entity]] = None


class StartSessionResponse(BaseModel):
    session_id: str
    roomba_name: str
    roomba_description: str
    initial_pad: PADState
    entity_sensitivities: List[EntitySensitivity]
    known_entities: list


class TherapyMessageRequest(BaseModel):
    session_id: str
    message: str


class TherapyMessageResponse(BaseModel):
    dialog: str
    pad: PADState
    entity_sensitivities: List[EntitySensitivity] = []
    should_pause: bool = False


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
    event_type: Literal["enter", "proximity_threshold", "collision", "boundary_encountered", "dirt_progress"]
    emotion_states: List[EmotionState] = []
    direction: Optional[str] = None
    percent_complete: Optional[float] = None  # dirt_progress only
    is_complete: Optional[bool] = None        # dirt_progress only


class ArenaEventResponse(BaseModel):
    dialog: str
    pad: PADState
    entity_sensitivities: List[EntitySensitivity]
    should_pause: bool = False
    # True for every event type except a collision/proximity_threshold that
    # only updated the aggregation Collector without crossing a threshold -
    # in that case dialog is "" and pad/entity_sensitivities are simply the
    # session's unchanged current values, since no LLM turn happened. See
    # Planning_Autonomous_Movement.md, Parking Lot: "/arena/event response
    # payload needs a lightweight 'still accumulating' shape." This is the
    # additive, same-shape version of that - not the fuller distinct-shape
    # design that was also discussed, which would need a corresponding
    # Unity-side change to SessionManager.cs's OrchestratorResponse handling.
    flushed: bool = True
