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

def render_event_prose(event_type, roomba_name, emotion_states):
    preamble_template = EVENT_PROSE_PREAMBLE_TEMPLATES[event_type]
    preamble = preamble_template.format(roomba_name=roomba_name)
    template = EVENT_PROSE_EMOTION_TEMPLATES[event_type]
    sentences = [
        template.format(entity_type=es.entity_type, emotion=es.emotion)
        for es in emotion_states
    ]
    return preamble+(", and".join(sentences))+"."