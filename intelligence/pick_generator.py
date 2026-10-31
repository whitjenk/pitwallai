# shim: remove when whatsapp/ is retired
from core.pick_generator import *  # noqa: F401,F403
from core.pick_generator import (  # noqa: F401 — private helpers used by legacy callers/tests
    _aggregate_signals,
    _best_constructor_swap,
    _constructor_drivers,
    _driver_score,
    _projected_race_points,
)


async def generate_and_log_picks(ctx, *, phone=None):
    """Generate picks and append them to the audit log (legacy WhatsApp path).

    The DB write stays out of core: ``core.pick_generator.generate_picks`` is
    pure and the caller owns the logging.
    """
    from intelligence.repository import append_picks

    output = generate_picks(ctx)
    await append_picks(ctx.race_key, output, phone=phone, circuit_key=ctx.circuit.circuit_key)
    return output
