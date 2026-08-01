# Backlog

Deferred ideas and possible extensions, captured as they come up during development
so they don't get lost in chat history. Not prioritized or scheduled — just recorded.

## 1. `/session/state`: path param instead of query param

Currently `GET /session/state?session_id=...`. Consider `GET /session/state/{session_id}`
instead, which is more RESTful for a single-resource lookup.

Source: surfaced while testing `/session/state` (step 2 of the API extension work).

## 2. `/session/state`: optional `personality_id`, optional `session_id`

Allow querying state by `personality_id` instead of (or in addition to) `session_id`,
with both params optional. Use case not yet fully specified — presumably to find
sessions by which personality they're running, without knowing the session_id in advance.

Source: same as #1.

## 3. `/sessions/state` (plural): support listing all session states

Rename the path to `/sessions/state` and, when neither `session_id` nor `personality_id`
is supplied, return a list of all current session states rather than a single object.

**Design tension to resolve if this is picked up:** this makes the endpoint's response
shape conditional — a single `SessionStateResponse` object in some cases, a list of them
in others. That's a real API design decision (union response type, more complex OpenAPI
spec, client-side branching required) and shouldn't be treated as a trivial pluralization.
Worth deciding whether this should instead be a genuinely separate endpoint
(e.g. `GET /sessions` for the list, `GET /session/state/{id}` for the single case)
rather than one endpoint with two response shapes.

Source: same as #1.

**Status update:** `/arena/entity` is now marked `deprecated` in Swagger — its
capabilities were superseded by `/arena/event` + `entity_sensitivities` (see #7
below). Items #4-#6 are now low priority unless the endpoint gets revived for
a real purpose.

## 4. `/arena/entity`: dedup check on `action: "added"`

Currently `"added"` always appends to `known_entities`, even if that `entity_id`
is already present. If Unity sends a duplicate `added` (e.g. a retry after a
dropped response), the same entity ends up listed twice. Needs a decision on
dedup semantics: reject the duplicate, silently ignore it, or replace the
existing entry.

Source: surfaced while implementing `/arena/entity` (step 4).

## 5. `/arena/entity`: split into separate POST (add) and DELETE (remove)

Currently a single `POST /arena/entity` endpoint with an `action: [added, removed]`
field distinguishes the two operations. More RESTful would be a `POST` for adding
an entity and a `DELETE` for removing one, treating the entity as a resource
rather than routing on an action field.

Source: same as #4.

## 6. `GET /arena/entities?entity_id=<id>` — optional entity lookup/listing

A GET endpoint where supplying `entity_id` returns that one entity, and omitting
it returns the full `known_entities` list. Uncertain value — may overlap
significantly with what `/session/state` already exposes. Low priority /
possibly not worth building.

Source: same as #4.

## 7. Arena entity list: global vs. per-session "known" list — RESOLVED/SUPERSEDED

**This is resolved by the entity_sensitivities redesign.** `known_entities`
is now write-only (populated by the now-deprecated `/arena/entity`, but not
read by anything). The real per-session mechanism is `entity_sensitivities`,
aggregated by `entity_type` from Unity's `emotion_states` and the LLM's own
reported deltas — which sidesteps the global-vs-per-session question this
item raised, since it was never trying to track entity *instances* at all,
only type-level feelings. Keeping the original text below for the record.

`known_entities` is currently modeled as purely per-session state, populated by
`arena_manifest` at `/session/start` and mutated by `/arena/entity` calls scoped
to a single `session_id`. But entities in the Arena are actually a property of
the game/arena as a whole, not of any one Roomba's session — if a couch is added,
it exists for every Roomba in the game, not just the one whose session happened
to receive the `/arena/entity` call.

This introduces a real distinction between two different things that the current
model conflates into one list:
1. The **actual current set of entities in the arena** (global, session-independent)
2. **What a given Roomba/session has discovered or become aware of** (per-session,
   presumably a subset of #1, and potentially the more behaviorally relevant one —
   a Roomba shouldn't necessarily react to a couch it hasn't encountered yet)

Unresolved: whether `/arena/entity` should update a global arena-level store that
all sessions read from (with per-session "discovery" tracked separately), whether
each session needs its own independent copy, or whether the distinction between
"exists" and "discovered" even matters for gameplay. In-game impact and priority
unclear until there's more than one concurrent Roomba/session to observe the
effect with.

Source: surfaced during `/arena/entity` testing (step 4), multi-session
implications not yet explored since current testing is single-session.

## 8. `/arena/event` aggregation: simple replacement only

Aggregating multiple emotion_states into entity_sensitivities currently uses pure
overwrite semantics — the newest reported strength/emotion for a given entity_type
replaces whatever was there, no averaging, weighting, or decay. Acknowledged as too
simple to survive real gameplay. Revisit once there's a running game to observe
actual aggregation needs against (multiple simultaneous entities of the same type,
conflicting signals, etc.).

Source: entity_sensitivities refactor (post step-6 rework).

## 9. `arena_manifest` at `/session/start`: final purpose undecided

Currently used only to pre-seed entity_sensitivities entries at strength=0 for
entity types present at session start. Whether this is its real purpose long-term,
or whether it should do more (e.g. actually prime sensitivity values from
personality dysfunctions rather than blank zeros), is unresolved. Left in for now
because it's a reasonable place to "prime the pump," per discussion, but not
treated as finalized.

**Status update:** the "prime from dysfunctions" idea was implemented, but as
a *separate* mechanism — `personalities.json`'s new `initial_entity_sensitivities`
field, applied before `arena_manifest` at `/session/start`, taking precedence
for any entity_type it covers. `arena_manifest`'s own role is now narrower and
clearer: it only zero-seeds entity types that `initial_entity_sensitivities`
doesn't already cover. Still not fully "finalized" in the sense of being a
deliberate long-term design, but the ambiguity this item originally flagged
is mostly resolved.

Source: same as #8.

+## 10. `/arena/event`: empty `emotion_states` list is silently permitted — RESOLVED

`ArenaEventRequest.emotion_states` is validated as `List[EmotionState]` with no
minimum-length constraint, so an empty list (`[]`) is currently accepted. 
This is only realy valid for "enter" and"boundary_colision".  This
produces an empty-string `dialog` from `render_event_prose` rather than a clear
error. Every event type we've defined so far implies at least one triggering
entity, so an empty list arguably indicates a malformed request from Unity.
Consider adding a minimum-length validation (reject with 422) once real
gameplay traffic exists to confirm this assumption holds.

**Resolved:** `render_event_prose` now raises `ValueError` (surfaced as a 422)
when `emotion_states` is empty for `proximity_threshold` or `collision` —
event types where your own semantic model says an entity is required. `enter`
and `boundary_encountered` are allowed to have empty `emotion_states` (arena
entry with nobody around, or hitting a wall not near anything), and render a
sensible standalone sentence via the preamble/emotion-clause template split.

Source: step 7 (placeholder prose rendering).

## 11. No canonical `entity_type`/`emotion` vocabulary

Unity, the LLM, and `personalities.json` each independently choose free-form
strings for `entity_type` (e.g. "couch" vs "Couch" vs "sofa") and `emotion`.
`entity_sensitivities` aggregation is keyed on exact string match, so a casing
or synonym mismatch between Unity's report and the LLM's delta would silently
create a duplicate, disconnected entry instead of updating the intended one.
Not yet an issue with a single manual tester controlling both "sides," but
likely the first real bug once there's an actual Unity client generating its
own strings independently. Worth promoting ahead of #12-#14 below once Unity
integration starts.

Source: post-testing review, deferred pending Unity integration.

## 12. Endpoint-by-endpoint error handling review

The LLM-call-specific error handling (network/API failures in `call_llm`) is
done. What's not done: a deliberate pass across every endpoint considering its
actual failure modes, rather than whatever error handling fell out incidentally
while building each feature (some 404s, one 422). Deferred - large scope.

Source: post-testing review.

## 13. Automated tests for merge/aggregation logic

No automated tests exist; Swagger-only manual testing has been an explicit,
reasoned choice so far. Worth reconsidering now that the entity_sensitivities
merge logic has real branching complexity (seed-at-zero vs. actual-value,
Unity-then-LLM ordering, empty-list validation per event type) - exactly the
kind of logic that's easy to silently break with a future "small" change and
hard to catch by manual testing alone. Deferred - large scope.

Source: post-testing review.

## 14. Session persistence and concurrency

No database, no locking; sessions live in an in-memory dict for the lifetime
of the process. Known and previously accepted as out of scope (no multi-session
need yet, single manual tester). Deferred - large scope.

Source: post-testing review.

## 15. Verify `anthropic.APIError` actually covers real failure modes

`call_llm`'s `except anthropic.APIError as e:` is assumed to be the SDK's base
exception class covering connection failures, timeouts, rate limits, and bad
status responses - based on general understanding of the SDK's exception
hierarchy, not confirmed against the actually-installed package version.
Worth deliberately triggering a failure (e.g. a temporarily broken API key) to
confirm the 502 path actually fires as intended, rather than trusting it untested.

Source: step 11 (LLM call error handling).

## 16. `HTTPException` detail message inconsistency across endpoints

Quoting and capitalization of `session_id`/entity error details drifted across
endpoints during iteration (e.g. `"Session '{id}' not found"` vs.
`"Session {id} not found"` vs. `"session '{id}' not found"`). Cosmetic, not
functional, but worth a consistency pass before treating error responses as
a stable part of the contract.

Source: noticed during branch sync, iteration 2.

## 17. Document methods in main.py

Pick and use a template to use to document all methods and main components of main.py.
Cover summary, intent, parameters, results and any other key factors.

Source: noticed during PR

## 18. Extract `ROOMBA_STATE_TOOL` (and related LLM-response constants) into their own module

`ROOMBA_STATE_TOOL` (the tool-use schema replacing `RESPONSE_FORMAT_INSTRUCTIONS`,
introduced when `call_llm` moved to forced tool-use structured output) is a large
inline constant sitting in the middle of `main.py`'s logic. Left inline for now,
consistent with how `RESPONSE_FORMAT_INSTRUCTIONS` was already inline before it,
and because it's tightly coupled to `PADState`/`EntitySensitivity` and the parsing
code right below it - splitting it out in isolation risks the two drifting out of
sync across files without a compensating benefit.

Worth revisiting as part of a deliberate, broader reorganization of `main.py`
(e.g. splitting models into `models.py`, endpoints into `routes.py`, LLM-calling
logic including this tool schema into its own module) once the file has grown
enough that such a split is clearly justified on its own merits - not as a
one-off extraction of a single constant.

Source: raised while reviewing the tool-use structured-output patch.

## [19]. Roomba movement not disabled while chat input has focus

WASD input still drives the Roomba while the player is actively typing in the
therapist chat input field. `PlayerController2D` reads input unconditionally
every frame with no awareness of UI focus state. Likely fix: check
`TMP_InputField.isFocused` (or a shared "input is captured by UI" flag) and
gate movement reads accordingly.

Source: noted during Phase 3.5 testing (Unity/CollisionController work).

## [20]. Chat input field does not wrap long text

The `TMP_InputField` box itself (as opposed to the chat history bubbles,
which wrap correctly) does not wrap long typed text before submission -
likely a `Line Type` / text area sizing setting distinct from the bubble
wrapping work done in Phase 2.5a. Cosmetic, low priority.

Source: noted during Phase 3.5 testing (Unity/CollisionController work).
