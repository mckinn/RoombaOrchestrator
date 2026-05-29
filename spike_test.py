import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024, 
    messages=[
        {"role": "user", "content": "say hello in exactly five words"}
    ]
)

print(message.content[0].text)