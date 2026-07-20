# RoombaOrchestrator
This is the python service that intermediates the Roomba Game implemented in Unity, and the LLM that controls the Roombas

# Required modules & their install commands

Uvicorn - pip install uvicorn
fastapi - pip install fastapi

# how to use

1. Uvicorn will run on http://127.0.0.1:8000 
1. `/docs` will publish the swagger endpoint
1. `/openapi.json` will publish the json OpenAPI schema
1. `/redoc` publishes an alternative to swagger


# how to run

1. make sure that you have Python 3.14.2 installed
1. install the dependencies that the code will need
```python -m pip install anthropic python-dotenv```
1. pull the working branch ```git pull origin spike/roomba-personality```
1. create a .env file that contains the line..
```ANTHROPIC_API_KEY=<the key I will send you via carrier pidgeon>```
1. Pull from ```https://github.com/mckinn/RoombaOrchestrator/tree/spike/roomba-personality```
1. from a terminal running in the directory containing the repo execute
```python -m uvicorn main:app --reload```

# how to git

1. git checkout main 
1. git pull origin main 
1. deletion and trimming
    1. branch -d initial-api 
    1. git remote prune origin 
1. git checkout -b <your-new-branch-name> 
1. git add .
1. git commit -m "message words"
1. git push -u origin <new-branch> 
    1. -u links local branch to the remote branch