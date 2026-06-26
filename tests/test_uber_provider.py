"""Offline tests for UberEatsProvider (fake transport, no network)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent import run_agent
from provider import OrderResult
from uber_provider import (
    FakeUberTransport,
    UberEatsProvider,
    build_uber_provider,
    _map_uber_item,
)


def sample_prefs(**overrides):
    prefs = {
        "schedule": {
            "order_times": ["12:00"],
            "timezone": "America/New_York",
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "paused": False,
            "pause_until": None,
        },
        "ordering_platform": "uber",
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


def make_provider(**kwargs) -> UberEatsProvider:
    transport = FakeUberTransport(**kwargs)
    return UberEatsProvider(transport=transport, access_token="test-linked-token")


class TestSearchMenu:
    def test_search_menu_returns_mapped_menu_items(self):
        provider = make_provider()
        menu = provider.search_menu()
        assert len(menu) >= 5
        poke = next(i for i in menu if i.name == "Salmon Poke Bowl")
        assert poke.id == "ue-m1"
        assert poke.restaurant == "Blue Fin Sushi"
        assert poke.cuisine == "japanese"
        assert poke.price_usd == 16.50
        assert poke.item_type == "main"
        assert poke.allergens == ("fish",)
        assert poke.allergen_confirmed is True

    def test_missing_allergen_data_sets_allergen_confirmed_false(self):
        provider = make_provider()
        menu = provider.search_menu()
        mystery = next(i for i in menu if i.name == "Mystery Chef Special")
        assert mystery.allergen_confirmed is False

    def test_map_uber_item_placeholder_shape(self):
        raw = {
            "item_id": "ue-x1",
            "title": "Test Bowl",
            "merchant_name": "Test Kitchen",
            "cuisine_type": "thai",
            "price": {"amount": 999, "currency": "USD"},
            "item_category": "ENTREE",
            "allergens": {"confirmed": False, "tags": []},
            "dietary_tags": ["spicy"],
            "description": "Sample item.",
        }
        item = _map_uber_item(raw)
        assert item.id == "ue-x1"
        assert item.price_usd == 9.99
        assert item.allergen_confirmed is False


class TestPlaceOrder:
    def test_place_order_success_returns_order_id(self):
        provider = make_provider()
        result = provider.place_order("ue-m4", "lunch-order-2026-06-22")
        assert result.success is True
        assert result.order_id == "uber-lunch-order-2026-06-22"
        assert result.status == "confirmed"
        assert result.item is not None
        assert result.item.name == "Chicken Shawarma Plate"

    def test_simulated_placement_failure(self):
        provider = make_provider(fail_item_ids={"ue-m8"})
        result = provider.place_order("ue-m8", "lunch-order-fail-1")
        assert result.success is False
        assert result.status == "failed"

    def test_unknown_status_reported_as_unknown(self):
        provider = make_provider(unknown_status_item_ids={"ue-m8"})
        result = provider.place_order("ue-m8", "lunch-order-unknown-1")
        assert result.success is True
        assert provider.get_order_status(result.order_id) == "unknown"

    def test_idempotency_submits_only_once(self):
        transport = FakeUberTransport()
        provider = UberEatsProvider(transport=transport, access_token="test-linked-token")
        key = "lunch-order-idem-1"

        first = provider.place_order("ue-m8", key)
        second = provider.place_order("ue-m8", key)

        assert first.success is True
        assert second.success is True
        assert first.order_id == second.order_id
        assert len(transport.submit_calls) == 1
        assert len(provider.place_order_calls) == 2


class TestAgentIntegration:
    def test_full_agent_run_with_uber_provider(self):
        provider = make_provider()
        prefs = sample_prefs()
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

        assert outcome.status == "ordered"
        assert outcome.item_name is not None
        assert outcome.price_usd is not None
        assert len(provider.place_order_calls) == 1


class TestFactory:
    def test_build_uber_provider_fake_mode(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_UBER_MODE", "fake")
        provider = build_uber_provider()
        assert isinstance(provider, UberEatsProvider)
        assert provider.search_menu()

    def test_live_mode_raises_not_implemented(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_UBER_MODE", "live")
        with pytest.raises(NotImplementedError, match="early-access"):
            build_uber_provider()

    def test_get_provider_uber_entry(self):
        from provider import get_provider

        provider = get_provider("uber")
        assert isinstance(provider, UberEatsProvider)
