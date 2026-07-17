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
## 7. Arena entity list: global vs. per-session "known" list

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

Source: same as #8.

## 10. `/arena/event`: empty `emotion_states` list is silently permitted

`ArenaEventRequest.emotion_states` is validated as `List[EmotionState]` with no
minimum-length constraint, so an empty list (`[]`) is currently accepted. 
This is only realy valid for "enter" and"boundary_colision".  This
produces an empty-string `dialog` from `render_event_prose` rather than a clear
error. Every event type we've defined so far implies at least one triggering
entity, so an empty list arguably indicates a malformed request from Unity.
Consider adding a minimum-length validation (reject with 422) once real
gameplay traffic exists to confirm this assumption holds.

Source: step 7 (placeholder prose rendering).