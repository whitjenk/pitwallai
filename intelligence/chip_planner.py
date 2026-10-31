# shim: remove when whatsapp/ is retired
from core.chip_planner import *  # noqa: F401,F403
from core.chip_planner import ChipPlan


async def persist_chip_plan(phone, plan):
    """Persist a chip plan by share token (legacy WhatsApp path).

    The DB write stays out of core; the caller owns persistence.
    """
    from intelligence.repository import save_chip_plan

    await save_chip_plan(phone, plan.share_token, plan.model_dump(mode="json"))
    return plan


async def load_chip_plan(share_token):
    """Load a persisted chip plan by share token, or None (legacy WhatsApp path)."""
    from intelligence.repository import get_chip_plan_by_token

    row = await get_chip_plan_by_token(share_token)
    if row is None:
        return None
    return ChipPlan.model_validate(row.plan_json)
