"""Run lunch agent on Inference Ghost (scheduler + Discord confirmation)."""

from __future__ import annotations

import os

from env_loader import load_project_env
from scheduler import run_scheduler


def main() -> None:
    load_project_env()
    os.environ.setdefault("LUNCH_AGENT_CONFIRMATION", "discord")
    os.environ.setdefault("LUNCH_AGENT_DISCORD_MODE", "live")
    os.environ.setdefault("LUNCH_AGENT_UBER_MODE", "fake")
    print("Ghost lunch service starting (Discord confirmation, scheduler loop)")
    print("Set DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in the environment.")
    run_scheduler()


if __name__ == "__main__":
    main()
