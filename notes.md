# Random notes

## Useful Things

- ```python -m uvicorn main:app --reload```

## returning the JSON payload containing mood

Should we be returning the json content of the messages to the LLM, including the mood, or just the message text as part of the message history ?

The impact on the overall experience is hard to assess.

at the moment I've changed it to return only the text.

Therapist --> Roomba : ["Hi, I'm your therapist"]
Roomba --> Therapist : { dialog: "hi there",  mood: "overjoyed"}
Therapist --> Roomba : ["here's the next therapist thought", "hi there", "Hi, "I'm your therapist"]

The alternative is
Therapist --> Roomba : ["Hi, I'm your therapist"]
Roomba --> Therapist : { dialog: "hi there",  mood: "overjoyed"}
Therapist --> Roomba : ["here's the next therapist thought", '{ dialog: "hi there",  mood: "overjoyed"}'', "Hi, "I'm your therapist"]

we likely need to experiment with the outcome of this design choice.

Hi, Dusty
PLease, tell me more about your concern
That's too bad.  I hace the perfect solution.  Here is a magic wand that I can tape to you that will freeze all couches.  They will be incapable of motion once they touch you.  It makes you 100% safe.
I have seen it work personally.    I was even sitting on a couch when it happened - it was instant !
we have a test arena where you can experience some of this wonder yourself.   Let's go there



