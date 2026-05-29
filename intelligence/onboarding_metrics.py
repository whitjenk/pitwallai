"""Onboarding funnel telemetry.

Three-step funnel: SUBSCRIBE → team set → first picks received. Computes
the funnel and emits a structured warning when the completion rate dips
below a configurable threshold so operators can route an alert via their
existing log pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import func, select

from db.models import FantasyTeam, Subscriber
from db.session import get_session


_DEFAULT_THRESHOLD = 0.50
_DEFAULT_MIN_SAMPLE = 10


@dataclass(frozen=True, slots=True)
class OnboardingFunnel:
    """Snapshot of the three-step onboarding funnel."""

    active_subscribers: int
    team_set: int
    first_picks_received: int
    completion_rate: float
    below_threshold: bool
    threshold: float
    min_sample_size: int


def _threshold() -> float:
    raw = os.getenv("PITWALL_ONBOARDING_THRESHOLD", "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_THRESHOLD
    except ValueError:
        value = _DEFAULT_THRESHOLD
    return max(0.0, min(1.0, value))


def _min_sample_size() -> int:
    raw = os.getenv("PITWALL_ONBOARDING_MIN_SAMPLE", "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MIN_SAMPLE
    except ValueError:
        value = _DEFAULT_MIN_SAMPLE
    return max(1, value)


async def compute_onboarding_funnel() -> OnboardingFunnel:
    """Query the three-step funnel and assess against the alert threshold.

    "Team set" means the subscriber has a fantasy_teams row with all five
    driver slots and both constructor slots populated, plus a non-null
    remaining_budget — i.e. they completed the team flow (not just the
    SUBSCRIBE confirmation).

    "First picks received" reads from subscribers.races_received, which
    the picks dispatch increments after a successful send. >= 1 means the
    subscriber has been through at least one full pipeline cycle.

    Completion rate is first_picks / active_subscribers. The threshold is
    only meaningful once active_subscribers >= min_sample_size — until
    then we treat the funnel as warming up and `below_threshold` is False.
    """
    async with get_session() as session:
        active_q = await session.execute(
            select(func.count())
            .select_from(Subscriber)
            .where(Subscriber.active.is_(True))
        )
        active = int(active_q.scalar_one() or 0)

        team_q = await session.execute(
            select(func.count())
            .select_from(FantasyTeam)
            .join(Subscriber, Subscriber.phone == FantasyTeam.phone)
            .where(Subscriber.active.is_(True))
            .where(FantasyTeam.driver_1.is_not(None))
            .where(FantasyTeam.driver_2.is_not(None))
            .where(FantasyTeam.driver_3.is_not(None))
            .where(FantasyTeam.driver_4.is_not(None))
            .where(FantasyTeam.driver_5.is_not(None))
            .where(FantasyTeam.constructor_1.is_not(None))
            .where(FantasyTeam.constructor_2.is_not(None))
            .where(FantasyTeam.remaining_budget.is_not(None))
        )
        team_set = int(team_q.scalar_one() or 0)

        picks_q = await session.execute(
            select(func.count())
            .select_from(Subscriber)
            .where(Subscriber.active.is_(True))
            .where(Subscriber.races_received >= 1)
        )
        first_picks = int(picks_q.scalar_one() or 0)

    threshold = _threshold()
    min_sample = _min_sample_size()
    completion = (first_picks / active) if active > 0 else 0.0
    below = active >= min_sample and completion < threshold

    return OnboardingFunnel(
        active_subscribers=active,
        team_set=team_set,
        first_picks_received=first_picks,
        completion_rate=round(completion, 4),
        below_threshold=below,
        threshold=threshold,
        min_sample_size=min_sample,
    )


async def check_and_alert_onboarding_funnel() -> OnboardingFunnel:
    """Run the funnel check and emit a logged warning when below threshold.

    Operator-facing: any log routing (PagerDuty, Slack, Sentry) will pick
    up the `onboarding_alert` event because we bind it with the relevant
    counters. Returns the funnel snapshot for the caller to surface.
    """
    funnel = await compute_onboarding_funnel()
    if funnel.below_threshold:
        logger.bind(
            event="onboarding_alert",
            active_subscribers=funnel.active_subscribers,
            team_set=funnel.team_set,
            first_picks_received=funnel.first_picks_received,
            completion_rate=funnel.completion_rate,
            threshold=funnel.threshold,
        ).warning(
            "Onboarding completion rate {pct:.0%} below threshold {th:.0%} "
            "across {n} active subscribers",
            pct=funnel.completion_rate,
            th=funnel.threshold,
            n=funnel.active_subscribers,
        )
    return funnel
