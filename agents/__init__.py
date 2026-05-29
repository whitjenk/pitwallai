"""PitWallAI race-weekend agents — the 3-agent ontology.

    PicksAgent     — Thursday context → Friday practice → Saturday quali picks.
                     Stage functions live in context_builder.py,
                     practice_analyst.py, quali_strategist.py for testability.
    RaceMonitor    — Sunday live race watching. Separate latency contract
                     (800ms decode target, long-lived loop).
    ScorerLearner  — Post-race scoring + eval harness. Separate concern,
                     drives calibration drift detection.

History: this used to be presented as five named agents. PicksAgent
unifies the three pre-lock stages into one named interface — stage
functions are still individually testable, but the abstraction surface
is now three agents, not five. PIPELINE_VERSION reflects the change.
"""
