# RoombaOrchestrator
This is the python service that intermediates the Roomba Game implemented in Unity, and the LLM that controls the Roombas

# how to run

1. make sure that you have Python 3.14.2 installed
1. install the dependencies that the code will need
```python -m pip install anthropic python-dotenv```
1. pull the working branch ```git pull origin spike/roomba-personality```
1. create a .env file that contains the line..
```ANTHROPIC_API_KEY=<the key I will send you via carrier pidgeon>```
1. Pull from ```https://github.com/mckinn/RoombaOrchestrator/tree/spike/roomba-personality```
1. from a terminal running in the directory containing the repo execute
```python spike_roomba.py```

