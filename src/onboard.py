"""Interactive setup that writes user_preferences.yaml."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import yaml

from config import validate_preferences

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "user_preferences.yaml"
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
FALLBACK_MIN = 3
FALLBACK_MAX = 5


def ask(prompt: str, default: str | None = None) -> str:
    tag = f" [{default}]" if default not in (None, "") else ""
    answer = input(f"{prompt}{tag}\n> ").strip()
    return answer or (default or "")


def ask_list(prompt: str, default_list: list[str] | None = None) -> list[str]:
    default_str = ", ".join(default_list) if default_list else ""
    raw = ask(prompt + " (comma separated)", default_str)
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def parse_hhmm(value: str) -> str:
    parsed = datetime.strptime(value.strip(), "%H:%M")
    return parsed.strftime("%H:%M")


def ask_lunch_time(default: str = "12:00") -> str:
    while True:
        raw = ask("What time is lunch? (HH:MM, 24-hour)", default)
        try:
            return parse_hhmm(raw)
        except ValueError:
            print("  Use HH:MM format, for example 12:00 or 13:30.")


def confirm_overwrite() -> bool:
    if not CONFIG_PATH.exists():
        return True
    print(f"\nFound existing {CONFIG_PATH.name}.")
    answer = ask("Overwrite it? (yes/no)", "no").lower()
    return answer in {"yes", "y"}


def collect_fallback() -> list[str]:
    fallback = ask_list(
        "3 to 5 main meals you trust as backups when nothing else fits",
        ["turkey sandwich", "garden salad", "veggie wrap"],
    )
    while len(fallback) < FALLBACK_MIN:
        print(f"  Need at least {FALLBACK_MIN} meals (you gave {len(fallback)}).")
        fallback += ask_list("Add more backup meals")
    if len(fallback) > FALLBACK_MAX:
        print(f"  Keeping the first {FALLBACK_MAX} items.")
        fallback = fallback[:FALLBACK_MAX]
    return fallback


def main() -> None:
    print("\nLunch agent setup")
    print("Press Enter to accept the value in [brackets].\n")

    if not confirm_overwrite():
        print("\nSetup cancelled. Existing preferences were not changed.\n")
        return

    days_raw = ask("Which days should I order lunch?", "weekdays")
    if days_raw.lower() in ("weekdays", "weekday", ""):
        days = WEEKDAYS
    else:
        days = [d.strip().lower() for d in days_raw.split(",") if d.strip()]

    lunch_time = ask_lunch_time("12:00")
    lead = ask("How many minutes before lunch should I check in?", "5")
    lead = lead if lead.isdigit() else "5"
    timezone = ask("Timezone?", "America/New_York")

    print()
    budget_max = ask("Max price per lunch (USD)?", "18")
    budget_max = budget_max if is_number(budget_max) else "18"
    if float(budget_max) < 8:
        print("  Note: a low budget may limit available options.")
    overage = ask("Approved overage if nothing fits under max (USD)?", "3")
    overage = overage if is_number(overage) else "3"

    print()
    allergens = ask_list(
        "Allergies to never order (most important)",
        ["shellfish"],
    )

    no_go = ask_list("Foods you will not eat?", ["liver"])

    print()
    cuisines = ask_list(
        "Favorite cuisines, best first",
        ["japanese", "mediterranean", "thai", "american"],
    )
    dislikes = ask_list(
        "Soft dislikes (avoid when possible)",
        ["spicy", "fried"],
    )
    favorites = ask_list(
        "Favorite main dishes",
        ["salmon poke bowl", "chicken shawarma plate"],
    )

    print()
    fallback = collect_fallback()

    print("\nSafety check. Confirm these allergies are correct:")
    while True:
        shown = ", ".join(allergens) if allergens else "none listed"
        print(f"  Never order items containing: {shown}")
        if ask("  Correct? (yes/no)", "yes").lower() in ("yes", "y"):
            break
        allergens = ask_list("  List allergies again")

    prefs = {
        "schedule": {
            "order_times": [lunch_time],
            "timezone": timezone,
            "days": days,
            "paused": False,
            "pause_until": None,
        },
        "ordering_platform": "mock",
        "budget": {
            "max_usd": round(float(budget_max), 2),
            "approved_overage_usd": round(float(overage), 2),
        },
        "cuisine_ranking": cuisines,
        "allergens_hard": allergens,
        "no_go": no_go,
        "dislikes_soft": dislikes,
        "favorites": favorites,
        "fallback_foods": fallback,
        "confirmation": {
            "lead_time_min": int(lead),
            "reminder_interval_min": 10,
            "auto_order_on_no_response": True,
        },
    }

    validate_preferences(prefs)

    with CONFIG_PATH.open("w") as f:
        yaml.dump(prefs, f, sort_keys=False, default_flow_style=False, allow_unicode=True)

    print(f"\nSaved to {CONFIG_PATH.name}.")
    print(
        f"I will check in about {lead} minutes before {lunch_time} "
        f"({timezone}) on your selected days."
    )
    print("Run setup again anytime to update preferences.\n")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.\n")
        sys.exit(0)
