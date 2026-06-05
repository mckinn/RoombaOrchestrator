#
# name - spike_roomba
# a python script to manage a therapy  dialog with one or mor psychologically 
# damaged roombas 
#
#  being used to explore that possibiliites, and learn some python
#

import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

#
# loads the file containing all of the personality prompts 
# for the collection of the Roombas that may undergo therapy
#
# for this spike we are talking about a list of one, but trying
# to get the architecture right for multiple Roombas
#

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

# the entire history of the conversaion between the user (therapist) 
# and the assistant (roomba).  note that the history is an aggregate
# context that is transmitted every time

conversation_history = []

print(f"\nWelcome - your ciient {dusty['name']} awaits you")
print(f"Description: {dusty['description']}")
print("\ntype 'quit' to end the session\n")
print("i" * 40)

#
# this while loop reprents one therapy session, continuing until 
# the therapist says "quit"
#

while True:
    user_input = input("\nTherapist: ")

    if not user_input.strip():
        continue

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

    mood = "calm"
    dialog = response_text

    # the system prompt for each user  controls the roomba behavior, and also demands
    # that they append a mood string to the end of all meaningful exchanges, for later
    # use in the game

    if "\nMOOD:" in response_text:
        parts = response_text.rsplit("\nMOOD:", 1)
        dialog = parts[0].strip()
        mood = parts[1].strip()

    conversation_history.append({
        "role": "assistant",
        "content": response_text
    })

    print(f"\n{dusty['name']}: {dialog}")
    print(f"[mood: {mood}]")

    print(f"[debug] history length: {len(conversation_history)} messages, last input tokens: {message.usage.input_tokens}")


# print(f"\n{dusty['name']}: {message.content[0].text}")
# print("---------------------")
# print(json.dumps(dusty, indent=2))
# print("---------------------")
# print(message.model_dump_json(indent=2))


