"""Schedule daily lunch agent runs at configured times."""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from config import validate_preferences

ROOT = Path(__file__).resolve().parent.parent
PREFS_PATH = ROOT / "user_preferences.yaml"
AGENT_SCRIPT = ROOT / "src" / "agent.py"

WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def load_preferences() -> dict:
    with PREFS_PATH.open() as f:
        return validate_preferences(yaml.safe_load(f))


def parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def should_run_now(prefs: dict, now: datetime) -> bool:
    schedule = prefs["schedule"]
    if schedule.get("paused"):
        return False

    pause_until = schedule.get("pause_until")
    if pause_until:
        try:
            from datetime import date

            if now.date() <= date.fromisoformat(str(pause_until)):
                return False
        except ValueError:
            pass

    day_name = WEEKDAY_NAMES[now.weekday()]
    if day_name not in [d.lower() for d in schedule["days"]]:
        return False

    for order_time in schedule.get("order_times", []):
        hour, minute = parse_hhmm(order_time)
        lead = int(prefs["confirmation"]["lead_time_min"])
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # Trigger at lead_time before order_time
        trigger = target.timestamp() - (lead * 60)
        window_start = trigger
        window_end = trigger + 60
        ts = now.timestamp()
        if window_start <= ts < window_end:
            return True
    return False


def run_agent_once() -> int:
    result = subprocess.run(
        [sys.executable, str(AGENT_SCRIPT)],
        cwd=str(ROOT),
        check=False,
    )
    return result.returncode


def run_scheduler(poll_seconds: int = 30) -> None:
    """Poll clock and invoke agent at configured confirmation lead times."""
    prefs = load_preferences()
    tz_name = prefs["schedule"]["timezone"]
    print(f"Lunch scheduler started (timezone={tz_name}, poll={poll_seconds}s)")
    last_run_minute: str | None = None

    while True:
        now = datetime.now(ZoneInfo(tz_name))
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if should_run_now(prefs, now) and minute_key != last_run_minute:
            print(f"Triggering agent at {now.isoformat()}")
            run_agent_once()
            last_run_minute = minute_key
        time.sleep(poll_seconds)


if __name__ == "__main__":
    run_scheduler()
