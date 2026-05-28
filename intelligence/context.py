"""Orchestrator context loaded at application startup."""

from __future__ import annotations

from dataclasses import dataclass, field

from circuits.profiles import CircuitProfile, load_circuit_profiles


@dataclass
class OrchestratorContext:
    """
    Shared race-weekend context injected into agents.

    Circuit profiles are loaded once at startup — agents must not fetch them
    at runtime.
    """

    circuits: dict[str, CircuitProfile] = field(default_factory=dict)

    def get_circuit(self, circuit_key: str) -> CircuitProfile | None:
        """Resolve circuit profile by key or OpenF1 name."""
        key = circuit_key.strip().lower()
        if key in self.circuits:
            return self.circuits[key]
        for profile in self.circuits.values():
            if profile.openf1_circuit_name.lower() == key:
                return profile
        return None


_CONTEXT: OrchestratorContext | None = None


def init_orchestrator_context() -> OrchestratorContext:
    """
    Load circuit profiles and store global orchestrator context.

    Returns:
        Initialized OrchestratorContext.
    """
    global _CONTEXT
    _CONTEXT = OrchestratorContext(circuits=load_circuit_profiles())
    return _CONTEXT


def get_orchestrator_context() -> OrchestratorContext:
    """
    Return the startup-loaded orchestrator context.

    Returns:
        OrchestratorContext singleton.

    Raises:
        RuntimeError: If init_orchestrator_context() was not called.
    """
    if _CONTEXT is None:
        raise RuntimeError("Orchestrator context not initialized — call init_orchestrator_context()")
    return _CONTEXT
