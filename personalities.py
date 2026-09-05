"""
Personality-library loading. Reads personalities.json - the free-text
system_prompt plus initial_entity_sensitivities that define a Roomba's
starting behavior, per Requirements.md's "NPC Initialization" section.
"""

import json


def load_personality(filename, personality_id):
    with open(filename, 'r') as fileloader:
        personality_data = json.load(fileloader)
    for personality in personality_data['personalities']:
        if personality['id'] == personality_id:
            return personality
    raise ValueError(f"Personality '{personality_id}' not found in {filename}")
