# Phase 1 — Environment & Spike (this chat's focus)

1. Confirm repo structure and local Python environment
1. Install dependencies (FastAPI, uvicorn, anthropic SDK)
1. Create personality template library — one JSON file, one Roomba (Dusty the couchaphobe)
1. Write the standalone spike script — a simple Python REPL loop that: loads Dusty's personality, opens a session, accepts your typed therapy messages, and prints Dusty's responses in character
1. Validate the spike works end to end with a real API call

# Phase 2 — Evolve Spike into Orchestrator Skeleton

1. Convert the spike logic into the FastAPI service structure from the architecture doc Session Manager, Prompt Builder, Anthropic Client, Mode Resolver
1. Stub the API endpoints (/session/start, /therapy/message, /practice/event, etc.)
1. Validate endpoints respond correctly (even with mocked LLM responses where useful)

# Phase 3 — Handoff Readiness

1. Define the exact JSON contracts between Unity and the Python service (mode command structure is already drafted in the architecture doc — confirm or revise)
1. Document what your son needs to build in the Unity skeleton to consume those contracts