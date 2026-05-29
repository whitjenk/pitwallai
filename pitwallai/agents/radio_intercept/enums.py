"""Enumerations for radio intercept decoding."""

from __future__ import annotations

from enum import Enum


class RadioIntent(str, Enum):
    """Primary tactical intent inferred from a team radio transmission."""

    PIT_CALL = "PIT_CALL"
    TIRE_COMPLAINT = "TIRE_COMPLAINT"
    PUSH_MODE = "PUSH_MODE"
    CONSERVE_MODE = "CONSERVE_MODE"
    ENGINE_MODE_CHANGE = "ENGINE_MODE_CHANGE"
    SAFETY_CAR_RESPONSE = "SAFETY_CAR_RESPONSE"
    WEATHER_QUERY = "WEATHER_QUERY"
    MECHANICAL_ISSUE = "MECHANICAL_ISSUE"
    GAP_UPDATE_REQUEST = "GAP_UPDATE_REQUEST"
    DRIVER_FRUSTRATION = "DRIVER_FRUSTRATION"
    FUEL_MANAGEMENT = "FUEL_MANAGEMENT"
    DRS_ISSUE = "DRS_ISSUE"
    UNKNOWN = "UNKNOWN"


class StrategicSignal(str, Enum):
    """Higher-level strategic implication derived from radio context."""

    IMMINENT_PIT_WINDOW = "IMMINENT_PIT_WINDOW"
    UNDERCUT_OPPORTUNITY = "UNDERCUT_OPPORTUNITY"
    OVERCUT_ATTEMPT = "OVERCUT_ATTEMPT"
    TIRE_DEGRADATION_HIGH = "TIRE_DEGRADATION_HIGH"
    PACE_MODE_SHIFT = "PACE_MODE_SHIFT"
    SAFETY_CAR_STRATEGY = "SAFETY_CAR_STRATEGY"
    RELIABILITY_RISK = "RELIABILITY_RISK"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class UrgencyLevel(str, Enum):
    """Priority weight for pit-wall escalation."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    LOW_PRIORITY: int = 1
    MEDIUM_PRIORITY: int = 2
    HIGH_PRIORITY: int = 3
    CRITICAL_PRIORITY: int = 4

    @property
    def priority(self) -> int:
        """
        Return the numeric priority weight for this urgency level.

        Returns:
            Integer priority in the range 1–4.
        """
        match self:
            case UrgencyLevel.LOW:
                return self.LOW_PRIORITY
            case UrgencyLevel.MEDIUM:
                return self.MEDIUM_PRIORITY
            case UrgencyLevel.HIGH:
                return self.HIGH_PRIORITY
            case UrgencyLevel.CRITICAL:
                return self.CRITICAL_PRIORITY

    @classmethod
    def from_intent(cls, intent: RadioIntent) -> UrgencyLevel:
        """
        Map a decoded radio intent to a default urgency level.

        Args:
            intent: The inferred primary radio intent.

        Returns:
            A sensible default urgency level for pit-wall triage.
        """
        match intent:
            case RadioIntent.MECHANICAL_ISSUE | RadioIntent.DRS_ISSUE:
                return cls.CRITICAL
            case (
                RadioIntent.PIT_CALL
                | RadioIntent.TIRE_COMPLAINT
                | RadioIntent.SAFETY_CAR_RESPONSE
                | RadioIntent.PUSH_MODE
            ):
                return cls.HIGH
            case (
                RadioIntent.ENGINE_MODE_CHANGE
                | RadioIntent.WEATHER_QUERY
                | RadioIntent.FUEL_MANAGEMENT
                | RadioIntent.DRIVER_FRUSTRATION
                | RadioIntent.CONSERVE_MODE
            ):
                return cls.MEDIUM
            case RadioIntent.GAP_UPDATE_REQUEST:
                return cls.LOW
            case _:
                return cls.LOW


class StreamEventType(str, Enum):
    """WebSocket event types for dashboard streaming."""

    TRANSMISSION_DECODED = "TRANSMISSION_DECODED"
    COMPETITOR_INTEL_UNVERIFIED = "COMPETITOR_INTEL_UNVERIFIED"
    REHEARSAL_COMPLETE = "REHEARSAL_COMPLETE"
    SYSTEM_STATUS = "SYSTEM_STATUS"
