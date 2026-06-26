"""Offline tests for lunch agent safety and failure behavior."""

from __future__ import annotations

import sys
import types
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent import (
    build_candidates,
    budget_ceiling,
    fallback_items,
    guard_exit,
    idempotency_key,
    run_agent,
    score_item,
)
from config import ConfigError, validate_preferences
from menu_matcher import keyword_match_allergens, llm_match_allergens
from provider import MOCK_MENU, MenuItem, MockProvider


def sample_prefs(**overrides):
    prefs = {
        "schedule": {
            "order_times": ["12:00"],
            "timezone": "America/New_York",
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "paused": False,
            "pause_until": None,
        },
        "ordering_platform": "mock",
        "budget": {"max_usd": 18.0, "approved_overage_usd": 3.0},
        "cuisine_ranking": ["japanese", "mediterranean", "thai", "american"],
        "allergens_hard": ["shellfish", "peanuts"],
        "no_go": ["liver"],
        "dislikes_soft": ["spicy", "fried"],
        "favorites": ["salmon poke bowl", "chicken shawarma plate"],
        "fallback_foods": ["turkey sandwich", "garden salad", "veggie wrap"],
        "confirmation": {
            "lead_time_min": 5,
            "reminder_interval_min": 10,
            "auto_order_on_no_response": True,
        },
    }
    prefs.update(overrides)
    return prefs


def empty_state():
    return {"days": {}, "ratings": {}, "do_not_show_again": []}


def monday_noon():
    return datetime(2026, 6, 22, 11, 55, 0, tzinfo=ZoneInfo("America/New_York"))


class TestConfigValidation:
    def test_valid_preferences_pass(self):
        validate_preferences(sample_prefs())

    def test_low_budget_raises_clear_error(self):
        prefs = sample_prefs(budget={"max_usd": 2.0, "approved_overage_usd": 0.0})
        with pytest.raises(ConfigError, match="below the minimum"):
            validate_preferences(prefs)

    def test_missing_field_raises(self):
        prefs = sample_prefs()
        del prefs["fallback_foods"]
        with pytest.raises(ConfigError, match="fallback_foods"):
            validate_preferences(prefs)


class TestHardFilters:
    def test_hard_allergen_items_never_selected(self):
        prefs = sample_prefs()
        state = empty_state()
        candidates = build_candidates(
            MOCK_MENU, prefs, state, keyword_match_allergens
        )
        names = {c.item.name for c in candidates}
        assert "Shrimp Tempura Bento" not in names
        assert "Pad Thai with Peanuts" not in names

    def test_unconfirmed_allergen_items_never_selected(self):
        prefs = sample_prefs()
        state = empty_state()
        candidates = build_candidates(
            MOCK_MENU, prefs, state, keyword_match_allergens
        )
        names = {c.item.name for c in candidates}
        assert "Mystery Chef Special" not in names

    def test_sides_and_drinks_never_selected(self):
        prefs = sample_prefs()
        state = empty_state()
        candidates = build_candidates(
            MOCK_MENU, prefs, state, keyword_match_allergens
        )
        assert all(c.item.item_type == "main" for c in candidates)
        names = {c.item.name for c in candidates}
        assert "Miso Soup" not in names
        assert "Fruit Cup" not in names
        assert "Iced Green Tea" not in names

    def test_price_never_exceeds_budget_ceiling(self):
        prefs = sample_prefs()
        state = empty_state()
        ceiling = budget_ceiling(prefs)
        candidates = build_candidates(
            MOCK_MENU, prefs, state, keyword_match_allergens
        )
        assert all(c.item.price_usd <= ceiling for c in candidates)


class TestDailyIdempotency:
    def test_never_more_than_one_order_per_day(self):
        prefs = sample_prefs()
        state = empty_state()
        when = monday_noon()
        provider = MockProvider()

        first = run_agent(
            provider=provider,
            prefs=prefs,
            state=state,
            when=when,
            simulated_response="order_it",
            skip_schedule_check=True,
        )
        assert first.status == "ordered"

        second = run_agent(
            provider=provider,
            prefs=prefs,
            state=state,
            when=when,
            simulated_response="order_it",
            skip_schedule_check=True,
        )
        assert second.status == "skipped"
        assert "already handled" in second.message.lower()
        assert len(provider.place_order_calls) == 1


class TestFailureLadder:
    def test_fallback_used_when_no_ranked_candidates(self):
        # Block every regular main. Do not use broad terms like "turkey" or
        # "garden" that would also block fallback_foods by substring match.
        block_regular_mains = [
            "salmon poke",
            "spicy tuna",
            "shrimp",
            "tempura",
            "shawarma",
            "falafel",
            "pad thai",
            "green curry",
            "chicken tikka",
            "mystery",
            "liver",
            "wagyu",
            "garden salad",
            "veggie wrap",
        ]
        prefs = sample_prefs(
            no_go=block_regular_mains,
            favorites=[],
            fallback_foods=["turkey sandwich", "garden salad", "veggie wrap"],
        )
        state = empty_state()
        when = monday_noon()

        candidates = build_candidates(
            MOCK_MENU, prefs, state, keyword_match_allergens
        )
        assert candidates == []

        fallbacks = fallback_items(
            MOCK_MENU, prefs, state, keyword_match_allergens
        )
        assert len(fallbacks) == 1
        assert fallbacks[0].name == "Turkey Sandwich"

        outcome = run_agent(
            provider=MockProvider(),
            prefs=prefs,
            state=state,
            when=when,
            simulated_response="order_it",
            skip_schedule_check=True,
        )
        assert outcome.status == "ordered"
        assert outcome.item_name == "Turkey Sandwich"
        assert outcome.user_response == "fallback"

    def test_notifies_when_no_valid_option_and_fallback_fails(self):
        turkey = next(i for i in MOCK_MENU if i.id == "m8")
        provider = MockProvider(menu=[turkey], fail_item_ids={"m8"})
        prefs = sample_prefs(
            allergens_hard=["shellfish", "peanuts", "fish", "gluten", "dairy", "soy", "sesame"],
            no_go=["liver"],
            favorites=[],
            fallback_foods=["turkey sandwich"],
        )
        state = empty_state()
        when = monday_noon()
        outcome = run_agent(
            provider=provider,
            prefs=prefs,
            state=state,
            when=when,
            simulated_response="order_it",
            skip_schedule_check=True,
        )
        assert outcome.status == "failed"
        assert "manually" in outcome.message.lower()

    def test_unknown_status_does_not_reorder(self):
        turkey = MenuItem(
            id="m8",
            name="Turkey Sandwich",
            restaurant="Corner Deli",
            cuisine="american",
            price_usd=11.00,
            item_type="main",
            allergens=("gluten",),
            tags=("sandwich",),
            description="Roasted turkey on whole wheat with lettuce.",
        )
        provider = MockProvider(menu=[turkey], unknown_status_item_ids={"m8"})
        prefs = sample_prefs(
            allergens_hard=[],
            no_go=[],
            favorites=["turkey sandwich"],
            fallback_foods=["garden salad", "veggie wrap", "falafel wrap"],
        )
        state = empty_state()
        when = monday_noon()
        day = when.date().isoformat()

        outcome = run_agent(
            provider=provider,
            prefs=prefs,
            state=state,
            when=when,
            simulated_response="order_it",
            skip_schedule_check=True,
        )

        assert outcome.status == "needs-verification"
        assert len(provider.place_order_calls) == 1
        assert provider.place_order_calls[0] == ("m8", idempotency_key(day))
        assert state["days"][day]["status"] == "needs-verification"


class TestGuard:
    def test_paused_skips_without_order(self):
        prefs = sample_prefs()
        prefs["schedule"]["paused"] = True
        state = empty_state()
        reason = guard_exit(prefs, state, monday_noon())
        assert reason is not None
        assert "paused" in reason.lower()


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch, llm_text: str) -> None:
    def fake_create(**kwargs):
        message = types.SimpleNamespace(content=llm_text)

        class _Resp:
            choices = [types.SimpleNamespace(message=message)]

        return _Resp()

    fake_openai = types.ModuleType("openai")

    class OpenAI:
        def __init__(self, api_key: str) -> None:
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=fake_create)
            )

    fake_openai.OpenAI = OpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


class TestLlmAllergenMatching:
    def test_llm_cannot_override_keyword_unsafe(self, monkeypatch):
        shrimp = next(i for i in MOCK_MENU if i.id == "m3")
        _install_fake_openai(monkeypatch, "SAFE: no allergens detected")

        safe, reason = llm_match_allergens(shrimp, ["shellfish"])
        assert safe is False
        assert "shellfish" in reason

        prefs = sample_prefs()
        candidates = build_candidates(
            [shrimp], prefs, empty_state(), llm_match_allergens
        )
        assert candidates == []

    def test_llm_can_tighten_keyword_safe(self, monkeypatch):
        turkey = next(i for i in MOCK_MENU if i.id == "m8")
        _install_fake_openai(monkeypatch, "UNSAFE: may contain traces of shellfish")

        safe, reason = llm_match_allergens(turkey, ["shellfish"])
        assert safe is False
        assert reason == "llm marked unsafe"

        prefs = sample_prefs()
        candidates = build_candidates(
            [turkey], prefs, empty_state(), llm_match_allergens
        )
        assert candidates == []


class TestRankingSignals:
    def test_distance_and_hours_bonus(self):
        item = MenuItem(
            id="rank-1",
            name="Lunch at Nearby Spot",
            restaurant="Nearby Spot",
            cuisine="thai",
            price_usd=15.0,
            description="dist_m=180 | hours_listed=yes",
        )
        candidate = score_item(item, sample_prefs(), empty_state())
        assert "distance <=200m +20" in candidate.reasons
        assert "hours listed +5" in candidate.reasons

    def test_recent_restaurant_penalty(self):
        state = empty_state()
        state["days"]["2026-06-25"] = {
            "status": "ordered",
            "restaurant": "Kobe",
            "cuisine": "japanese",
            "item_name": "Lunch at Kobe",
        }
        item = MenuItem(
            id="rank-2",
            name="Lunch at Kobe",
            restaurant="Kobe",
            cuisine="japanese",
            price_usd=15.0,
            description="dist_m=300",
        )
        candidate = score_item(item, sample_prefs(), state)
        assert "recent restaurant -20" in candidate.reasons
        assert "recent cuisine -8" in candidate.reasons

    def test_personal_thumbs_up_bonus(self):
        state = empty_state()
        state["ratings"]["Lunch at Kobe"] = [{"rating": "up"}]
        item = MenuItem(
            id="rank-3",
            name="Lunch at Kobe",
            restaurant="Kobe",
            cuisine="japanese",
            price_usd=15.0,
        )
        candidate = score_item(item, sample_prefs(), state)
        assert "personal thumbs up +25" in candidate.reasons


class TestConfirmationLoop:
    def test_repeated_show_another_keeps_re_picking(self, monkeypatch):
        responses = iter(["show_another", "show_another", "order_it"])
        calls = []

        def fake_confirmation(pick, prefs, verbose, user_output, simulated_response, discovery_report=""):
            calls.append(pick.item.id)
            return next(responses)

        monkeypatch.setattr("agent.run_confirmation", fake_confirmation)

        provider = MockProvider()
        state = empty_state()
        outcome = run_agent(
            provider=provider,
            prefs=sample_prefs(),
            state=state,
            when=monday_noon(),
            simulated_response=None,
            skip_schedule_check=True,
        )

        assert outcome.status == "ordered"
        assert len(calls) == 3
        assert len(set(calls)) == 3
