import logging

"""
Owns the in-memory session store and the logic for merging entity_sensitivity
updates into a session. See the JIRA backlog for the known/accepted gaps
here - no persistence/locking, and merge being a pure overwrite.
"""

logger = logging.getLogger("roomba_orchestrator")

sessions = {}


def merge_entity_sensitivities(session, updates, seed_new_at_zero=False):
    logger.debug(f"merge_entity_sensitivities: updates - {updates}")
    for u in updates:
        target = next(
            (s for s in session['entity_sensitivities'] if s['entity_type'] == u.entity_type),
            None
        )
        if target is not None:  # override with update
            target['emotion'] = u.emotion
            target['strength'] = u.strength

        elif seed_new_at_zero:  # create a new 0 value entity sensitivity
            session['entity_sensitivities'].append({
                "entity_type": u.entity_type,
                "emotion": "none",
                "strength": 0.0
            })
        else:
            session['entity_sensitivities'].append({  # add a new updated values entry
                "entity_type": u.entity_type,
                "emotion": u.emotion,
                "strength": u.strength
            })
    logger.debug(f"merge_entity_sensitivities: session[entity_sensitivities] - {session['entity_sensitivities']}")
