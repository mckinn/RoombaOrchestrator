import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

def load_personality(filename, personality_id):
    with open(filename, 'r') as fileloader:
        personality_data = json.load(fileloader)
    for personality in personality_data['personalities']:
        if personality['id'] == personality_id:
            return personality
    raise ValueError(f"Personality '{personality_id}' not found in {filename}")

dusty = load_personality('personalities.json', 'couchaphobe_01')

print(f"Loaded personality: {dusty['name']}")
print(f"Description: {dusty['description']}")

client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024, 
    system=dusty['system_prompt'],
    messages=[
        {"role": "user", "content": "Hello Dusty, I'm your therapist. How are you feeling today?"}
    ]
)


print(f"\n{dusty['name']}: {message.content[0].text}")
print("---------------------")
print(dusty)
print("---------------------")
print(message)
