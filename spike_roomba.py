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

client = anthropic.Anthropic()
conversation_history = []

print(f"\nWelcome - your ciient {dusty['name']} awaits you")
print(f"Description: {dusty['description']}")
print("\ntype 'quit' to end the session\n")
print("i" * 40)

while True:
    user_input = input("\nTherapist: ")

    if user_input.lower() == 'quit':
        print("\nSession Over")
        break
    
    conversation_history.append({
        "role":"user",
        "content": user_input
    })

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024, 
        system=dusty['system_prompt'],
        messages=conversation_history
    )

    response_text = message.content[0].text

        
    conversation_history.append({
        "role":"assistant",
        "content": user_input
    })

    print(f"\n{dusty['name']}: {response_text}")

    print(f"[debug] history length: {len(conversation_history)} messages, last input tokens: {message.usage.input_tokens}")


# print(f"\n{dusty['name']}: {message.content[0].text}")
# print("---------------------")
# print(json.dumps(dusty, indent=2))
# print("---------------------")
# print(message.model_dump_json(indent=2))


