"""Validate user_preferences.yaml on load."""

from __future__ import annotations

from typing import Any

MIN_BUDGET_USD = 5.0

REQUIRED_TOP_LEVEL = (
    "schedule",
    "ordering_platform",
    "budget",
    "cuisine_ranking",
    "allergens_hard",
    "no_go",
    "dislikes_soft",
    "favorites",
    "fallback_foods",
    "confirmation",
)

REQUIRED_SCHEDULE = ("order_times", "timezone", "days")
REQUIRED_BUDGET = ("max_usd", "approved_overage_usd")
REQUIRED_CONFIRMATION = (
    "lead_time_min",
    "reminder_interval_min",
    "auto_order_on_no_response",
)


class ConfigError(ValueError):
    """Raised when user_preferences.yaml is missing or invalid."""


def validate_preferences(prefs: dict[str, Any] | None) -> dict[str, Any]:
    if not prefs or not isinstance(prefs, dict):
        raise ConfigError("user_preferences.yaml is empty or not a mapping.")

    for key in REQUIRED_TOP_LEVEL:
        if key not in prefs:
            raise ConfigError(f"Missing required field: {key}")

    schedule = prefs["schedule"]
    if not isinstance(schedule, dict):
        raise ConfigError("schedule must be a mapping.")
    for key in REQUIRED_SCHEDULE:
        if key not in schedule:
            raise ConfigError(f"Missing required field: schedule.{key}")

    order_times = schedule["order_times"]
    if not isinstance(order_times, list) or not order_times:
        raise ConfigError("schedule.order_times must be a non-empty list.")

    days = schedule["days"]
    if not isinstance(days, list) or not days:
        raise ConfigError("schedule.days must be a non-empty list.")

    budget = prefs["budget"]
    if not isinstance(budget, dict):
        raise ConfigError("budget must be a mapping.")
    for key in REQUIRED_BUDGET:
        if key not in budget:
            raise ConfigError(f"Missing required field: budget.{key}")

    try:
        max_usd = float(budget["max_usd"])
        overage = float(budget["approved_overage_usd"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("budget.max_usd and budget.approved_overage_usd must be numbers.") from exc

    if max_usd < MIN_BUDGET_USD:
        raise ConfigError(
            f"budget.max_usd is {max_usd:.2f}, which is below the minimum ({MIN_BUDGET_USD:.2f}). "
            "Raise the budget or check for a typo."
        )
    if overage < 0:
        raise ConfigError("budget.approved_overage_usd cannot be negative.")

    confirmation = prefs["confirmation"]
    if not isinstance(confirmation, dict):
        raise ConfigError("confirmation must be a mapping.")
    for key in REQUIRED_CONFIRMATION:
        if key not in confirmation:
            raise ConfigError(f"Missing required field: confirmation.{key}")

    fallback = prefs["fallback_foods"]
    if not isinstance(fallback, list) or len(fallback) < 3:
        raise ConfigError("fallback_foods must list at least 3 items.")

    for list_field in ("cuisine_ranking", "allergens_hard", "no_go", "dislikes_soft", "favorites"):
        if not isinstance(prefs[list_field], list):
            raise ConfigError(f"{list_field} must be a list.")

    return prefs
