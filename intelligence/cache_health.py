"""
Pre-broadcast cache health check.

Called by the Saturday scheduler BEFORE running quali_strategist.
Logs warnings for any driver missing practice or radio signal data.
Never raises — a missing cache is a warning, not a crash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheHealthReport:
    race_key: str
    drivers_checked: int
    practice_hits: int
    practice_misses: list[str] = field(default_factory=list)
    radio_hits: int = 0
    radio_misses: list[str] = field(default_factory=list)
    ready_for_explanations: bool = False


async def check_signal_cache_health(
    race_key: str,
    driver_codes: list[str],
) -> CacheHealthReport:
    """
    Run before Saturday broadcast. Logs a summary and returns a report.

    Caller decides whether to proceed — this function never blocks.
    """
    from intelligence.practice_cache import get_practice_signals
    from intelligence.radio_cache import get_radio_signals

    practice_hits = 0
    practice_misses: list[str] = []
    radio_hits = 0
    radio_misses: list[str] = []

    for code in driver_codes:
        p = await get_practice_signals(race_key, code)
        if p:
            practice_hits += 1
        else:
            practice_misses.append(code)

        r = await get_radio_signals(race_key, code)
        if r:
            radio_hits += 1
        else:
            radio_misses.append(code)

    total = len(driver_codes)
    drivers_with_any_signal = sum(
        1
        for code in driver_codes
        if code not in practice_misses or code not in radio_misses
    )
    ready = total > 0 and drivers_with_any_signal >= (total * 0.5)

    report = CacheHealthReport(
        race_key=race_key,
        drivers_checked=total,
        practice_hits=practice_hits,
        practice_misses=practice_misses,
        radio_hits=radio_hits,
        radio_misses=radio_misses,
        ready_for_explanations=ready,
    )

    if not ready:
        logger.warning(
            "signal_cache_low_coverage race_key=%s practice_coverage=%s radio_coverage=%s "
            "missing_practice=%s missing_radio=%s",
            race_key,
            f"{practice_hits}/{total}",
            f"{radio_hits}/{total}",
            practice_misses,
            radio_misses,
        )
    else:
        logger.info(
            "signal_cache_healthy race_key=%s practice_coverage=%s radio_coverage=%s",
            race_key,
            f"{practice_hits}/{total}",
            f"{radio_hits}/{total}",
        )

    return report
