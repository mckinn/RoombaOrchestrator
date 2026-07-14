# MSC of the APIs between the players

This is a capture of the interactions between the therapist, the Roomba, the Orchestrator, and the Game that underlies the fundamental game play.

There appear to be two basic patterns at play - either the therapist says something, or something changes in the game arena.   Either of these could cause an interaction with the LLM.   Both flows are similar, but easier to view as seperate flows.

### triggered by therapist dialog

```mermaid
    sequenceDiagram
        actor t as Therapist
        participant r@{ "type" : "entity" } as Roomba
        participant g as Game
        participant o as Orchestrator
        participant l as LLM
        %% basic interaction
        t -> g : text statement
        g -> o : text statement
        o -> l : text statement, [state vector?]
        l -> o : response [text,{mood}]
        o -> g : [text, action]
        g -> g : state changes
        g -> r : move, do things
        g -> t : text in UI
```

### triggered by state change in the arena

```mermaid
    sequenceDiagram
        actor t as Therapist
        participant r@{ "type" : "entity" } as Roomba
        participant g as Game
        participant o as Orchestrator
        participant l as LLM
        %% event could be timed / autonomous, or user created
        opt might be therapist (or not)
            t -> g : environment change
        end 
        g -> o : environment change
        o -> l : [state vector]
        l -> o : response [text,{mood vector}]
        o -> g : [text, action]
        g -> g : state changes
        g -> r : move, do things
        g -> t : text in UI
```
