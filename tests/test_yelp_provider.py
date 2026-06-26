"""Offline tests for YelpDiscoveryProvider."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent import run_agent
from provider import MOCK_MENU, MockProvider
from yelp_provider import (
    FakeYelpTransport,
    YelpDiscoveryProvider,
    _names_match,
    build_yelp_provider,
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
        "ordering_platform": "yelp",
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


def monday_noon():
    return datetime(2026, 6, 22, 11, 55, 0, tzinfo=ZoneInfo("America/New_York"))


class TestNameMatching:
    def test_restaurant_name_match(self):
        assert _names_match("Blue Fin Sushi", "Blue Fin Sushi")
        assert _names_match("Olive Grove", "olive grove mediterranean")


class TestYelpDiscovery:
    def test_discover_returns_businesses(self):
        transport = FakeYelpTransport()
        provider = YelpDiscoveryProvider(transport=transport)
        businesses = provider.discover_businesses()
        assert len(businesses) >= 4
        assert transport.last_search is not None

    def test_search_menu_filters_to_discovered_restaurants(self):
        transport = FakeYelpTransport()
        provider = YelpDiscoveryProvider(transport=transport)
        menu = provider.search_menu()
        restaurants = {item.restaurant for item in menu}
        assert "Blue Fin Sushi" in restaurants
        assert "Homestyle Grill" not in restaurants
        assert all("Yelp:" in item.description for item in menu if item.restaurant == "Blue Fin Sushi")

    def test_fallback_when_no_overlap(self):
        transport = FakeYelpTransport(businesses=[{"name": "Unknown Place", "url": "https://yelp.com/x", "is_closed": False}])
        provider = YelpDiscoveryProvider(transport=transport)
        menu = provider.search_menu()
        assert provider.discovery_fallback is True
        assert len(menu) == len(MOCK_MENU)

    def test_place_order_delegates_to_mock(self):
        provider = YelpDiscoveryProvider(transport=FakeYelpTransport())
        result = provider.place_order("m4", "lunch-order-yelp-1")
        assert result.success is True
        assert result.order_id == "mock-lunch-order-yelp-1"

    def test_idempotency(self):
        provider = YelpDiscoveryProvider(transport=FakeYelpTransport())
        first = provider.place_order("m4", "lunch-order-yelp-idem")
        second = provider.place_order("m4", "lunch-order-yelp-idem")
        assert first.success and second.success
        assert first.order_id == second.order_id


class TestAgentIntegration:
    def test_full_agent_run_with_yelp_provider(self):
        provider = YelpDiscoveryProvider(transport=FakeYelpTransport())
        prefs = sample_prefs()
        state = {"days": {}, "ratings": {}, "do_not_show_again": []}
        outcome = run_agent(
            provider=provider,
            prefs=prefs,
            state=state,
            when=monday_noon(),
            simulated_response="order_it",
            skip_schedule_check=True,
        )
        assert outcome.status == "ordered"
        assert outcome.item_name is not None


class TestFactory:
    def test_build_yelp_provider_fake_mode(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_YELP_MODE", "fake")
        provider = build_yelp_provider()
        assert isinstance(provider, YelpDiscoveryProvider)
        assert provider.search_menu()

    def test_live_mode_requires_api_key(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_YELP_MODE", "live")
        monkeypatch.delenv("YELP_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="YELP_API_KEY"):
            build_yelp_provider()

    def test_get_provider_yelp_entry(self):
        from provider import get_provider

        provider = get_provider("yelp")
        assert isinstance(provider, YelpDiscoveryProvider)
