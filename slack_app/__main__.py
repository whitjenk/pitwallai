"""``python -m slack_app`` — check tokens, then serve the app over Socket Mode.

With a missing ``SLACK_BOT_TOKEN`` or ``SLACK_APP_TOKEN`` it names what's unset
and exits non-zero, so a first-time setup fails loudly instead of hanging on a
socket that can't authenticate. See ``docs/slack_setup.md``.
"""

from __future__ import annotations

import asyncio
import sys

from slack_app.app import missing_tokens, run


def main() -> int:
    missing = missing_tokens()
    if missing:
        print(
            "Can't start the Slack app — these environment variables are not set: "
            + ", ".join(missing)
            + ".\nSee docs/slack_setup.md to create the app and get its tokens.",
            file=sys.stderr,
        )
        return 1
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
