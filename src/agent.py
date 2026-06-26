"""Deterministic daily lunch ordering workflow."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import yaml

from config import ConfigError, validate_preferences
from env_loader import load_project_env
from menu_matcher import get_allergen_checker, keyword_match_no_go
from provider import MenuItem, Provider, get_provider

ROOT = Path(__file__).resolve().parent.parent
PREFS_PATH = ROOT / "user_preferences.yaml"
STATE_PATH = ROOT / "data" / "state.json"

WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


@dataclass
class Candidate:
    item: MenuItem
    score: float
    reasons: list[str]


@dataclass
class DayOutcome:
    status: str
    item_name: str | None = None
    price_usd: float | None = None
    user_response: str | None = None
    order_id: str | None = None
    message: str = ""
    restaurant: str | None = None
    cuisine: str | None = None


def load_preferences(path: Path = PREFS_PATH) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing preferences file: {path}")
    with path.open() as f:
        raw = yaml.safe_load(f)
    return validate_preferences(raw)


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"days": {}, "ratings": {}, "do_not_show_again": []}
    with path.open() as f:
        return json.load(f)


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def is_scheduled_day(prefs: dict[str, Any], when: datetime) -> bool:
    day_name = WEEKDAY_NAMES[when.weekday()]
    return day_name in [d.lower() for d in prefs["schedule"]["days"]]


def is_paused(prefs: dict[str, Any], when: datetime) -> bool:
    schedule = prefs["schedule"]
    if schedule.get("paused"):
        return True
    pause_until = schedule.get("pause_until")
    if pause_until:
        try:
            return when.date() <= date.fromisoformat(str(pause_until))
        except ValueError:
            return False
    return False


def day_record(state: dict[str, Any], day: str) -> dict[str, Any] | None:
    return state.get("days", {}).get(day)


def guard_exit(
    prefs: dict[str, Any],
    state: dict[str, Any],
    when: datetime,
    *,
    skip_schedule_check: bool = False,
) -> str | None:
    day = when.date().isoformat()

    if is_paused(prefs, when):
        return f"Lunch ordering is paused for {day}."

    if not skip_schedule_check and not is_scheduled_day(prefs, when):
        return f"{day} is not a scheduled ordering day."

    record = day_record(state, day)
    if record and record.get("status") in {"ordered", "skipped", "failed", "needs-verification"}:
        return f"Today is already handled ({record['status']})."

    return None


def budget_ceiling(prefs: dict[str, Any]) -> float:
    budget = prefs["budget"]
    return float(budget["max_usd"]) + float(budget.get("approved_overage_usd", 0))


def hard_filter_item(
    item: MenuItem,
    prefs: dict[str, Any],
    state: dict[str, Any],
    allergen_checker: Callable[[MenuItem, list[str]], tuple[bool, str]],
    *,
    main_only: bool = True,
) -> tuple[bool, str]:
    if main_only and item.item_type != "main":
        return False, "not a main meal"

    ceiling = budget_ceiling(prefs)
    if item.price_usd > ceiling:
        return False, f"over budget ({item.price_usd:.2f} > {ceiling:.2f})"

    safe, reason = allergen_checker(item, prefs.get("allergens_hard", []))
    if not safe:
        return False, reason

    no_go = list(prefs.get("no_go", []))
    no_go.extend(state_no_go(state))
    if keyword_match_no_go(item, no_go):
        return False, "matches no_go list"

    if not item.allergen_confirmed:
        return False, "allergen status not confirmed"

    return True, "passed hard filter"


def recent_item_names(state: dict[str, Any], lookback_days: int = 5) -> set[str]:
    cutoff = date.today() - timedelta(days=lookback_days)
    recent: set[str] = set()
    for day_str, record in sorted(state.get("days", {}).items(), reverse=True):
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        if day < cutoff:
            break
        if record.get("status") == "ordered" and record.get("item_name"):
            recent.add(record["item_name"].lower())
    return recent


def _record_restaurant_name(record: dict[str, Any]) -> str | None:
    if record.get("restaurant"):
        return str(record["restaurant"]).lower()
    item_name = str(record.get("item_name", ""))
    prefix = "lunch at "
    if item_name.lower().startswith(prefix):
        return item_name[len(prefix) :].lower()
    return None


def recent_restaurant_names(state: dict[str, Any], lookback_days: int = 3) -> set[str]:
    cutoff = date.today() - timedelta(days=lookback_days)
    recent: set[str] = set()
    for day_str, record in sorted(state.get("days", {}).items(), reverse=True):
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        if day < cutoff:
            break
        if record.get("status") != "ordered":
            continue
        name = _record_restaurant_name(record)
        if name:
            recent.add(name)
    return recent


def recent_cuisines(state: dict[str, Any], lookback_days: int = 3) -> set[str]:
    cutoff = date.today() - timedelta(days=lookback_days)
    recent: set[str] = set()
    for day_str, record in sorted(state.get("days", {}).items(), reverse=True):
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        if day < cutoff:
            break
        if record.get("status") == "ordered" and record.get("cuisine"):
            recent.add(str(record["cuisine"]).lower())
    return recent


def parse_item_metadata(description: str) -> dict[str, str]:
    """Parse key=value metadata embedded in menu item descriptions."""
    meta: dict[str, str] = {}
    for part in description.split("|"):
        part = part.strip()
        if "=" not in part or part.startswith("http") or part.startswith("OSM:"):
            continue
        key, value = part.split("=", 1)
        meta[key.strip()] = value.strip()
    return meta


def distance_score(distance_meters: float | None) -> tuple[float, str | None]:
    if distance_meters is None:
        return 0.0, None
    if distance_meters <= 200:
        return 20.0, "distance <=200m +20"
    if distance_meters <= 400:
        return 12.0, "distance <=400m +12"
    if distance_meters <= 600:
        return 6.0, "distance <=600m +6"
    return 0.0, None


def personal_history_score(
    item: MenuItem, state: dict[str, Any]
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    restaurant = item.restaurant.lower()
    name_lower = item.name.lower()

    for rated_item, entries in state.get("ratings", {}).items():
        rated_lower = rated_item.lower()
        matches = (
            rated_lower == name_lower
            or restaurant in rated_lower
            or rated_lower in restaurant
        )
        if not matches or not entries:
            continue
        ups = sum(1 for entry in entries if entry.get("rating") == "up")
        downs = sum(1 for entry in entries if entry.get("rating") == "down")
        if ups > downs:
            score += 25
            reasons.append("personal thumbs up +25")
        elif downs > 0 and entries[-1].get("rating") == "down":
            score -= 30
            reasons.append("personal thumbs down -30")

    return score, reasons


def source_quality_score(description: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    meta = parse_item_metadata(description)

    if meta.get("hours_listed") == "yes":
        score += 5
        reasons.append("hours listed +5")

    rating_raw = meta.get("google_rating")
    if rating_raw:
        try:
            rating = float(rating_raw)
        except ValueError:
            rating = 0.0
        if rating >= 4.5:
            score += 10
            reasons.append("google rating >=4.5 +10")
        elif rating >= 4.0:
            score += 5
            reasons.append("google rating >=4.0 +5")

    michelin = meta.get("michelin", "")
    if michelin:
        try:
            stars = int(float(michelin))
        except ValueError:
            stars = 0
        if stars > 0:
            bonus = 15 * stars
            score += bonus
            reasons.append(f"michelin stars +{bonus}")

    return score, reasons


def state_no_go(state: dict[str, Any]) -> list[str]:
    return list(state.get("do_not_show_again", []))


def score_item(item: MenuItem, prefs: dict[str, Any], state: dict[str, Any]) -> Candidate:
    reasons: list[str] = []
    score = 0.0

    cuisine_rank = [c.lower() for c in prefs.get("cuisine_ranking", [])]
    if item.cuisine.lower() in cuisine_rank:
        rank_score = len(cuisine_rank) - cuisine_rank.index(item.cuisine.lower())
        # Soft tie-breaker only — distance, rating, and budget matter more.
        bonus = min(12, rank_score * 2)
        score += bonus
        reasons.append(f"cuisine rank +{bonus}")

    favorites = [f.lower() for f in prefs.get("favorites", [])]
    name_lower = item.name.lower()
    for fav in favorites:
        if fav in name_lower or name_lower in fav:
            score += 25
            reasons.append("favorite match +25")
            break

    dislikes = [d.lower() for d in prefs.get("dislikes_soft", [])]
    haystack = " ".join([item.name.lower(), item.description.lower(), " ".join(item.tags)])
    for dislike in dislikes:
        if dislike in haystack:
            score -= 8
            reasons.append(f"soft dislike -8 ({dislike})")

    recent = recent_item_names(state)
    if name_lower in recent:
        score -= 20
        reasons.append("recent item -20")

    restaurant_lower = item.restaurant.lower()
    if restaurant_lower in recent_restaurant_names(state):
        score -= 20
        reasons.append("recent restaurant -20")

    if item.cuisine.lower() in recent_cuisines(state):
        score -= 8
        reasons.append("recent cuisine -8")

    meta = parse_item_metadata(item.description)
    dist_raw = meta.get("dist_m")
    distance_meters: float | None = None
    if dist_raw and dist_raw != "unknown":
        try:
            distance_meters = float(dist_raw)
        except ValueError:
            distance_meters = None
    dist_bonus, dist_reason = distance_score(distance_meters)
    if dist_reason:
        score += dist_bonus
        reasons.append(dist_reason)

    quality_bonus, quality_reasons = source_quality_score(item.description)
    score += quality_bonus
    reasons.extend(quality_reasons)

    history_bonus, history_reasons = personal_history_score(item, state)
    score += history_bonus
    reasons.extend(history_reasons)

    budget_max = float(prefs["budget"]["max_usd"])
    if item.price_usd <= budget_max:
        score += 3
        reasons.append("under base budget +3")

    return Candidate(item=item, score=score, reasons=reasons)


def build_candidates(
    menu: list[MenuItem],
    prefs: dict[str, Any],
    state: dict[str, Any],
    allergen_checker: Callable[[MenuItem, list[str]], tuple[bool, str]],
    verbose: bool = False,
) -> list[Candidate]:
    survivors: list[Candidate] = []
    fallback_names = [f.lower() for f in prefs.get("fallback_foods", [])]
    for item in menu:
        ok, reason = hard_filter_item(item, prefs, state, allergen_checker)
        if ok and any(name in item.name.lower() for name in fallback_names):
            ok = False
            reason = "reserved for fallback ladder"
        if verbose:
            status = "KEEP" if ok else "DROP"
            print(f"  [{status}] {item.name} ({item.price_usd:.2f}): {reason}")
        if ok:
            survivors.append(score_item(item, prefs, state))

    survivors.sort(key=lambda c: c.score, reverse=True)
    return survivors


def pick_option(
    candidates: list[Candidate], exclude_ids: set[str] | None = None
) -> Candidate | None:
    exclude_ids = exclude_ids or set()
    pool = [c for c in candidates if c.item.id not in exclude_ids]
    if not pool:
        return None
    top_n = min(3, len(pool))
    weights = [max(1.0, pool[i].score) for i in range(top_n)]
    return random.choices(pool[:top_n], weights=weights, k=1)[0]


def fallback_items(
    menu: list[MenuItem],
    prefs: dict[str, Any],
    state: dict[str, Any],
    allergen_checker: Callable[[MenuItem, list[str]], tuple[bool, str]],
) -> list[MenuItem]:
    names = [f.lower() for f in prefs.get("fallback_foods", [])]
    matches: list[MenuItem] = []
    for item in menu:
        if item.item_type != "main":
            continue
        if any(name in item.name.lower() for name in names):
            ok, _ = hard_filter_item(item, prefs, state, allergen_checker)
            if ok:
                matches.append(item)
    return matches


def idempotency_key(day: str) -> str:
    return f"lunch-order-{day}"


def notify_user(message: str) -> None:
    print(message)


def write_day_outcome(state: dict[str, Any], day: str, outcome: DayOutcome) -> None:
    record: dict[str, Any] = {
        "status": outcome.status,
        "item_name": outcome.item_name,
        "price_usd": outcome.price_usd,
        "user_response": outcome.user_response,
        "order_id": outcome.order_id,
        "message": outcome.message,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if outcome.restaurant:
        record["restaurant"] = outcome.restaurant
    if outcome.cuisine:
        record["cuisine"] = outcome.cuisine
    state.setdefault("days", {})[day] = record
    save_state(state)


def format_confirmation_card(
    pick: Candidate,
    prefs: dict[str, Any],
    discovery_report: str = "",
) -> str:
    from discord_confirm import format_lunch_message

    lead = int(prefs["confirmation"]["lead_time_min"])
    return format_lunch_message(
        pick.item.name,
        pick.item.restaurant,
        pick.item.price_usd,
        lead,
        place_url=extract_place_url(pick.item.description),
        recommendation_details=recommendation_details(pick),
        discovery_preamble=discovery_report,
    )


def print_suggestion(
    pick: Candidate,
    prefs: dict[str, Any],
    discovery_report: str = "",
) -> None:
    print(f"\n{format_confirmation_card(pick, prefs, discovery_report)}")


def print_user_outcome(outcome: DayOutcome) -> None:
    if outcome.status == "ordered":
        price = f"${outcome.price_usd:.2f}" if outcome.price_usd is not None else ""
        print(f"\nSelected: {outcome.item_name}  {price}".rstrip())
    elif outcome.status == "skipped":
        print("\nNo order placed for today.")
    elif outcome.status == "needs-verification":
        print(f"\n{outcome.message}")
    elif outcome.status == "failed":
        print(f"\n{outcome.message}")

    if confirmation_backend() == "discord":
        from discord_confirm import notify_discord

        if outcome.status == "ordered":
            target = outcome.restaurant or outcome.item_name
            notify_discord(f"✅ Locked in **{target}** — DoorDash link above 👆")
        elif outcome.status == "skipped":
            notify_discord("⏭️ Skipped for today.")
        elif outcome.status == "needs-verification":
            notify_discord(outcome.message or "Please verify your order in the delivery app.")
        elif outcome.status == "failed":
            notify_discord(outcome.message or "Could not place lunch order today.")


@dataclass
class OrderResultWrapper:
    result: Any
    status: str


def try_place_order(
    provider: Provider,
    item: MenuItem,
    day: str,
    verbose: bool,
) -> OrderResultWrapper:
    key = idempotency_key(day)
    if verbose:
        print(f"  Placing order for {item.name} (key={key})")
    result = provider.place_order(item.id, key)
    status = provider.get_order_status(result.order_id) if result.order_id else "unknown"
    return OrderResultWrapper(result=result, status=status)


def confirmation_backend() -> str:
    """Return confirmation backend: simulate (default) or discord."""
    return os.getenv("LUNCH_AGENT_CONFIRMATION", "simulate").lower()


def simulated_response_for_run(explicit: str | None) -> str | None:
    """Choose simulated_response for run_agent based on env and CLI."""
    if explicit is not None:
        return explicit
    if confirmation_backend() == "discord":
        return None
    return "order_it"


def extract_place_url(description: str) -> str:
    """Google Maps, OSM, or Yelp link embedded in menu item description."""
    try:
        from osm_provider import extract_google_maps_url, extract_osm_url

        url = extract_google_maps_url(description)
        if url:
            return url
        url = extract_osm_url(description)
        if url:
            return url
    except ImportError:
        pass
    try:
        from yelp_provider import extract_yelp_url

        return extract_yelp_url(description)
    except ImportError:
        return ""


def _humanize_reasons(reasons: list[str]) -> list[str]:
    """Turn internal score reasons into short user-friendly phrases."""
    friendly: list[str] = []
    for reason in reasons:
        if reason.startswith("favorite match"):
            friendly.append("one of your favorites")
        elif reason.startswith("cuisine rank"):
            friendly.append("cuisine you like")
        elif reason.startswith("distance <=200"):
            friendly.append("very close")
        elif reason.startswith("distance <=400"):
            friendly.append("close by")
        elif reason.startswith("distance <=600"):
            friendly.append("nearby")
        elif reason.startswith("google rating >=4.5"):
            friendly.append("highly rated")
        elif reason.startswith("google rating >=4.0"):
            friendly.append("well rated")
        elif reason.startswith("under base budget"):
            friendly.append("within budget")
        elif reason.startswith("michelin"):
            friendly.append("Michelin pick")
    seen: set[str] = set()
    ordered: list[str] = []
    for phrase in friendly:
        if phrase not in seen:
            seen.add(phrase)
            ordered.append(phrase)
    return ordered[:3]


def recommendation_details(pick: Candidate) -> list[str]:
    """Clean, scannable recommendation card lines (facts, then links)."""
    item = pick.item
    meta = parse_item_metadata(item.description)
    lines: list[str] = []

    facts: list[str] = []
    dist = meta.get("dist_m")
    if dist and dist != "unknown":
        try:
            meters = int(float(dist))
            facts.append(f"{meters / 1000:.1f} km" if meters >= 1000 else f"{meters} m")
        except ValueError:
            pass

    rating = meta.get("google_rating")
    reviews = meta.get("google_reviews")
    if rating:
        review_text = f" ({reviews})" if reviews else ""
        facts.append(f"\u2b50 {rating}{review_text}")
    if facts:
        lines.append("\U0001f4cd " + "   \u00b7   ".join(facts))

    price_text = f"~${item.price_usd:.0f}/person"
    price_source = meta.get("price_source", "estimated")
    if price_source == "google" or meta.get("google_price_level"):
        lines.append(f"\U0001f4b5 {price_text}")
    else:
        lines.append(f"\U0001f4b5 {price_text} (est.)")

    why = _humanize_reasons(pick.reasons)
    if why:
        lines.append("\u2728 " + " \u00b7 ".join(why))

    from order_links import build_doordash_search_url, extract_doordash_url, extract_google_maps_url

    lines.append("")
    doordash = extract_doordash_url(item.description) or build_doordash_search_url(
        item.restaurant
    )
    lines.append(f"\U0001f6d2 **Order on DoorDash:** {doordash}")
    maps = extract_google_maps_url(item.description)
    if maps:
        lines.append(f"\U0001f5fa\ufe0f Map: {maps}")
    return lines


def run_confirmation(
    pick: Candidate,
    prefs: dict[str, Any],
    verbose: bool,
    user_output: bool,
    simulated_response: str | None = "order_it",
    discovery_report: str = "",
) -> str:
    lead = prefs["confirmation"]["lead_time_min"]
    reminder = prefs["confirmation"]["reminder_interval_min"]
    auto = prefs["confirmation"]["auto_order_on_no_response"]

    use_discord = confirmation_backend() == "discord" and simulated_response is None

    if user_output and not use_discord:
        print_suggestion(pick, prefs, discovery_report)

    if verbose:
        print(
            f"CONFIRMATION: Lunch in ~{lead} min: {pick.item.name} "
            f"(${pick.item.price_usd:.2f})"
        )

    if simulated_response is not None:
        if simulated_response == "no_response" and auto:
            if user_output:
                print(f"\nNo reply after {reminder} minutes. Placing order automatically.")
            if verbose:
                print(f"  No response. Reminder after {reminder} min.")
                print("  Still no response. Auto-ordering.")
            return "order_it"
        if verbose:
            print(f"  Simulated user response: {simulated_response}")
        return simulated_response

    if confirmation_backend() == "discord":
        from discord_confirm import wait_for_discord_response

        return wait_for_discord_response(
            pick.item.name,
            pick.item.restaurant,
            pick.item.price_usd,
            prefs,
            verbose=verbose,
            user_output=user_output,
            place_url=extract_place_url(pick.item.description),
            discovery_report=discovery_report,
            recommendation_details=recommendation_details(pick),
        )

    return "order_it"


def run_agent(
    provider: Provider | None = None,
    prefs: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    when: datetime | None = None,
    verbose: bool = False,
    user_output: bool = False,
    simulated_response: str | None = "order_it",
    skip_schedule_check: bool = False,
) -> DayOutcome:
    prefs = prefs or load_preferences()
    state = state or load_state()
    tz_name = prefs["schedule"]["timezone"]
    when = when or datetime.now(ZoneInfo(tz_name))
    day = when.date().isoformat()

    reason = guard_exit(prefs, state, when, skip_schedule_check=skip_schedule_check)
    if reason:
        if verbose:
            print(f"GUARD: {reason}")
        return DayOutcome(status="skipped", message=reason)

    if verbose:
        print(f"RUN: lunch agent for {day}")

    provider = provider or get_provider(prefs.get("ordering_platform", "mock"))
    allergen_checker = get_allergen_checker()
    if hasattr(provider, "run_discovery"):
        provider.run_discovery(when)
    discovery_report = getattr(provider, "last_discovery_report", "")
    discovery_discord = (
        getattr(provider, "last_discovery_discord_report", None) or discovery_report
    )
    if verbose and discovery_report:
        print(discovery_report)
        print()
    elif user_output and discovery_discord and confirmation_backend() != "discord":
        print(discovery_discord)
        print()
    menu = provider.search_menu()

    if verbose:
        print("CANDIDATES (hard filter + rank):")
    candidates = build_candidates(menu, prefs, state, allergen_checker, verbose=verbose)

    if verbose:
        print("RANKED SURVIVORS:")
        for i, c in enumerate(candidates[:8], 1):
            print(
                f"  {i}. {c.item.name} score={c.score:.1f} "
                f"({', '.join(c.reasons) or 'no bonuses'})"
            )

    tried_ids: set[str] = set()
    pick = pick_option(candidates, tried_ids)
    if pick is None:
        outcome = handle_no_valid_option(
            provider, menu, prefs, state, day, allergen_checker, verbose
        )
        if user_output:
            print_user_outcome(outcome)
        return outcome

    if verbose:
        print(
            f"PICK: {pick.item.name} from {pick.item.restaurant} "
            f"(${pick.item.price_usd:.2f})"
        )

    action = run_confirmation(
        pick, prefs, verbose, user_output, simulated_response, discovery_discord
    )
    if action == "not_today":
        outcome = DayOutcome(
            status="skipped",
            item_name=pick.item.name,
            price_usd=pick.item.price_usd,
            user_response="not_today",
            message="User skipped today",
        )
        write_day_outcome(state, day, outcome)
        if verbose:
            print("OUTCOME: skipped (not_today)")
        if user_output:
            print_user_outcome(outcome)
        return outcome

    while True:
        if action == "show_another":
            tried_ids.add(pick.item.id)
            pick = pick_option(candidates, tried_ids)
            if pick is None:
                outcome = handle_no_valid_option(
                    provider, menu, prefs, state, day, allergen_checker, verbose
                )
                if user_output:
                    print_user_outcome(outcome)
                return outcome
            if verbose:
                print(f"RE-PICK: {pick.item.name}")
            if user_output:
                print("\nAnother option:")
            action = run_confirmation(
                pick, prefs, verbose, user_output, simulated_response
            )
            if action == "not_today":
                outcome = DayOutcome(
                    status="skipped",
                    item_name=pick.item.name,
                    price_usd=pick.item.price_usd,
                    user_response="not_today",
                    message="User skipped today",
                )
                write_day_outcome(state, day, outcome)
                if user_output:
                    print_user_outcome(outcome)
                return outcome
            if action == "show_another":
                continue

        if action in {"order_it", "no_response"}:
            outcome = place_with_failure_ladder(
                provider,
                pick,
                candidates,
                menu,
                prefs,
                state,
                day,
                allergen_checker,
                verbose,
                user_response=action,
            )
            if user_output:
                print_user_outcome(outcome)
            return outcome

        break

    outcome = DayOutcome(status="failed", message="Unexpected confirmation state")
    if user_output:
        print_user_outcome(outcome)
    return outcome


def place_with_failure_ladder(
    provider: Provider,
    pick: Candidate,
    candidates: list[Candidate],
    menu: list[MenuItem],
    prefs: dict[str, Any],
    state: dict[str, Any],
    day: str,
    allergen_checker: Callable[[MenuItem, list[str]], tuple[bool, str]],
    verbose: bool,
    user_response: str,
) -> DayOutcome:
    order_queue = [pick.item]
    for c in candidates:
        if c.item.id != pick.item.id:
            order_queue.append(c.item)

    fallbacks = fallback_items(menu, prefs, state, allergen_checker)
    for item in fallbacks:
        if item.id not in {i.id for i in order_queue}:
            order_queue.append(item)

    for item in order_queue:
        wrapped = try_place_order(provider, item, day, verbose)
        if wrapped.result.success:
            if wrapped.status == "unknown":
                msg = (
                    f"Order placed but status is unknown for {item.name}. "
                    "Please check your delivery app. Do not place another order."
                )
                notify_user(msg)
                outcome = DayOutcome(
                    status="needs-verification",
                    item_name=item.name,
                    price_usd=item.price_usd,
                    user_response=user_response,
                    order_id=wrapped.result.order_id,
                    message=msg,
                    restaurant=item.restaurant,
                    cuisine=item.cuisine,
                )
                write_day_outcome(state, day, outcome)
                if verbose:
                    print("OUTCOME: needs-verification (no double-charge)")
                return outcome

            outcome = DayOutcome(
                status="ordered",
                item_name=item.name,
                price_usd=item.price_usd,
                user_response=user_response,
                order_id=wrapped.result.order_id,
                message=wrapped.result.message,
                restaurant=item.restaurant,
                cuisine=item.cuisine,
            )
            write_day_outcome(state, day, outcome)
            if verbose:
                print(f"OUTCOME: ordered {item.name} (order_id={wrapped.result.order_id})")
            return outcome

        if verbose:
            print(f"  Placement failed for {item.name}: {wrapped.result.message}")

    msg = (
        "Could not place lunch after trying alternatives and fallbacks. "
        "Please order manually before lunch."
    )
    notify_user(msg)
    outcome = DayOutcome(
        status="failed",
        item_name=pick.item.name,
        price_usd=pick.item.price_usd,
        user_response=user_response,
        message=msg,
    )
    write_day_outcome(state, day, outcome)
    if verbose:
        print("OUTCOME: failed (user notified early)")
    return outcome


def handle_no_valid_option(
    provider: Provider,
    menu: list[MenuItem],
    prefs: dict[str, Any],
    state: dict[str, Any],
    day: str,
    allergen_checker: Callable[[MenuItem, list[str]], tuple[bool, str]],
    verbose: bool,
) -> DayOutcome:
    if verbose:
        print("NO VALID OPTION: trying fallback_foods")
    fallbacks = fallback_items(menu, prefs, state, allergen_checker)
    for item in fallbacks:
        wrapped = try_place_order(provider, item, day, verbose)
        if wrapped.result.success and wrapped.status != "unknown":
            outcome = DayOutcome(
                status="ordered",
                item_name=item.name,
                price_usd=item.price_usd,
                user_response="fallback",
                order_id=wrapped.result.order_id,
                message=f"Fallback order: {wrapped.result.message}",
            )
            write_day_outcome(state, day, outcome)
            if verbose:
                print(f"OUTCOME: ordered fallback {item.name}")
            return outcome

    msg = (
        "No safe lunch option found under your limits, and fallbacks failed. "
        "Please order manually before lunch."
    )
    notify_user(msg)
    outcome = DayOutcome(status="failed", message=msg)
    write_day_outcome(state, day, outcome)
    if verbose:
        print("OUTCOME: failed (no valid option)")
    return outcome


def record_rating(
    item_name: str,
    rating: str,
    state: dict[str, Any] | None = None,
) -> None:
    if rating not in {"up", "down"}:
        raise ValueError("rating must be 'up' or 'down'")
    state = state or load_state()
    state.setdefault("ratings", {}).setdefault(item_name, []).append(
        {"rating": rating, "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    )
    save_state(state)


def mark_do_not_show_again(
    item_name: str,
    prefs_path: Path = PREFS_PATH,
    state: dict[str, Any] | None = None,
) -> None:
    state = state or load_state()
    dns = state.setdefault("do_not_show_again", [])
    if item_name not in dns:
        dns.append(item_name)
    save_state(state)

    prefs = load_preferences(prefs_path)
    no_go = prefs.setdefault("no_go", [])
    if item_name.lower() not in [n.lower() for n in no_go]:
        no_go.append(item_name)
    with prefs_path.open("w") as f:
        yaml.safe_dump(prefs, f, sort_keys=False)


def weekly_summary(state: dict[str, Any] | None = None, days: int = 7) -> str:
    state = state or load_state()
    cutoff = date.today() - timedelta(days=days)
    ordered: list[dict[str, Any]] = []
    skipped = 0
    failed = 0

    for day_str, record in state.get("days", {}).items():
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        if day < cutoff:
            continue
        status = record.get("status")
        if status == "ordered":
            ordered.append(record)
        elif status == "skipped":
            skipped += 1
        elif status in {"failed", "needs-verification"}:
            failed += 1

    rating_scores: dict[str, list[str]] = {}
    for item, entries in state.get("ratings", {}).items():
        rating_scores[item] = [e["rating"] for e in entries]

    highest: list[str] = []
    for item, ratings in rating_scores.items():
        if ratings.count("up") >= 2 and "down" not in ratings[-3:]:
            highest.append(item)

    dns = state.get("do_not_show_again", [])
    lines = [
        f"Weekly lunch summary (last {days} days)",
        f"Ordered: {len(ordered)}",
        f"Skipped: {skipped}",
        f"Failed or needs verification: {failed}",
        "",
        "Items ordered:",
    ]
    for record in ordered:
        name = record.get("item_name", "unknown")
        price = record.get("price_usd")
        price_text = f"${price:.2f}" if price is not None else "n/a"
        lines.append(f"  - {name} ({price_text})")

    lines.append("")
    lines.append("Highest rated:")
    if highest:
        for item in highest:
            lines.append(f"  - {item}")
    else:
        lines.append("  - (none yet)")

    lines.append("")
    lines.append("Do not show again:")
    if dns:
        for item in dns:
            lines.append(f"  - {item}")
    else:
        lines.append("  - (none)")

    return "\n".join(lines)


def main() -> None:
    load_project_env()
    parser = argparse.ArgumentParser(description="Daily lunch ordering agent")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one simulated day with user-facing output",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run one live demo now (Discord, skip schedule/time guards)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show filter, ranking, and placement details",
    )
    parser.add_argument(
        "--onboard",
        action="store_true",
        help="Run interactive setup (writes user_preferences.yaml)",
    )
    parser.add_argument(
        "--response",
        choices=["order_it", "show_another", "not_today", "no_response"],
        default="order_it",
        help="Simulated confirmation response (with --once)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print weekly summary and exit",
    )
    parser.add_argument(
        "--rate",
        nargs=2,
        metavar=("ITEM", "RATING"),
        help="Record thumbs up/down: --rate 'Salmon Poke Bowl' up",
    )
    parser.add_argument(
        "--block",
        metavar="ITEM",
        help="Mark item do-not-show-again",
    )
    args = parser.parse_args()

    if args.onboard:
        from onboard import main as onboard_main

        onboard_main()
        return

    if args.summary:
        print(weekly_summary())
        return

    if args.rate:
        record_rating(args.rate[0], args.rate[1])
        print(f"Recorded {args.rate[1]} for {args.rate[0]}")
        return

    if args.block:
        mark_do_not_show_again(args.block)
        print(f"Blocked: {args.block}")
        return

    try:
        if args.demo:
            prefs = load_preferences()
            state = load_state()
            tz = ZoneInfo(prefs["schedule"]["timezone"])
            when = datetime.now(tz)
            day = when.date().isoformat()
            state.get("days", {}).pop(day, None)
            save_state(state)
            print(f"Demo run for {day} ({tz.key}) — reply in Discord: 1=order, 2=another, 3=skip")
            run_agent(
                when=when,
                verbose=args.verbose,
                user_output=True,
                simulated_response=None,
                skip_schedule_check=True,
            )
            return

        if args.once:
            prefs = load_preferences()
            state = load_state()
            tz = ZoneInfo(prefs["schedule"]["timezone"])
            demo_when = datetime.now(tz)
            while not is_scheduled_day(prefs, demo_when):
                demo_when += timedelta(days=1)
            demo_day = demo_when.date().isoformat()
            state.get("days", {}).pop(demo_day, None)
            save_state(state)
            random.seed(42)
            run_agent(
                when=demo_when,
                verbose=args.verbose,
                user_output=True,
                simulated_response=args.response,
                skip_schedule_check=True,
            )
            return

        outcome = run_agent(
            verbose=args.verbose,
            user_output=confirmation_backend() == "discord",
            simulated_response=simulated_response_for_run(None),
        )
        if outcome.message:
            print(outcome.message)
        else:
            print(outcome.status)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
