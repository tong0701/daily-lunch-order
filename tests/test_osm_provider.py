"""Offline tests for OsmDiscoveryProvider."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent import run_agent
from osm_provider import (
    FakeOverpassTransport,
    OsmDiscoveryProvider,
    build_osm_provider,
    discover_restaurants,
    evaluate_open_status,
    extract_osm_url,
    restaurant_to_menu_item,
)
from osm_provider import OsmRestaurant


def sample_prefs(**overrides):
    prefs = {
        "schedule": {
            "order_times": ["12:00"],
            "timezone": "America/New_York",
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "paused": False,
            "pause_until": None,
        },
        "ordering_platform": "osm",
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


@pytest.fixture(autouse=True)
def _isolate_external_calls(monkeypatch):
    """Keep unit tests offline and deterministic regardless of .env contents."""
    monkeypatch.setenv("LUNCH_AGENT_GOOGLE_PLACES_MODE", "off")
    monkeypatch.setenv("LUNCH_AGENT_OSM_MODE", "fake")


class TestOpeningHours:
    def test_24_7(self):
        when = monday_noon()
        assert evaluate_open_status("24/7", when) == "open"

    def test_explicit_closed(self):
        when = monday_noon()
        assert evaluate_open_status("closed", when) == "closed"

    def test_weekday_hours_open(self):
        when = monday_noon()
        assert evaluate_open_status("Mo-Fr 11:30-22:00", when) == "open"

    def test_weekday_hours_closed_before_open(self):
        when = datetime(2026, 6, 22, 9, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert evaluate_open_status("Mo-Fr 11:30-22:00", when) == "closed"


class TestDiscovery:
    def test_three_step_discovery(self):
        transport = FakeOverpassTransport()
        result = discover_restaurants(transport, monday_noon())
        assert len(result.nearby) == 5
        assert any(r.name == "Corner Deli" for r in result.excluded_closed)
        assert all(r.name != "Corner Deli" for r in result.open_today)
        assert transport.last_query is not None

    def test_discovery_report_mentions_osm_limits(self):
        provider = OsmDiscoveryProvider(transport=FakeOverpassTransport())
        report = provider.discovery_report(monday_noon())
        assert "OpenStreetMap" in report
        assert "Yelp-style" in report

    def test_discord_discovery_report_is_user_facing(self):
        provider = OsmDiscoveryProvider(transport=FakeOverpassTransport())
        provider.run_discovery(monday_noon())
        report = provider.last_discovery_discord_report

        assert "Discovery complete" in report
        assert "viable now" in report
        assert "Sample open nearby" not in report
        assert "unknown" not in report
        assert "Corner Deli" not in report


class TestOsmProvider:
    def test_search_menu_from_open_restaurants(self):
        provider = OsmDiscoveryProvider(transport=FakeOverpassTransport())
        provider.run_discovery(monday_noon())
        menu = provider.search_menu()
        restaurants = {item.restaurant for item in menu}
        assert "Blue Fin Sushi" in restaurants
        assert "Corner Deli" not in restaurants
        assert all("OSM:" in item.description for item in menu)
        assert all("dist_m=" in item.description for item in menu)

    def test_michelin_stars_in_description(self):
        provider = OsmDiscoveryProvider(transport=FakeOverpassTransport())
        provider.run_discovery(monday_noon())
        menu = provider.search_menu()
        sushi = next(i for i in menu if i.restaurant == "Blue Fin Sushi")
        assert "Michelin stars: 1" in sushi.description

    def test_place_order_simulated(self):
        provider = OsmDiscoveryProvider(transport=FakeOverpassTransport())
        menu = provider.search_menu()
        item_id = menu[0].id
        result = provider.place_order(item_id, "lunch-order-osm-1")
        assert result.success is True
        assert result.order_id == "osm-mock-lunch-order-osm-1"

    def test_extract_osm_url(self):
        item = restaurant_to_menu_item(
            OsmRestaurant(
                osm_id="node/1001",
                name="Test",
                cuisine="thai",
                amenity="restaurant",
                opening_hours="",
                open_status="open",
                stars="",
                community_notes="",
            )
        )
        url = extract_osm_url(item.description)
        assert url == "https://www.openstreetmap.org/node/1001"


class TestAgentIntegration:
    def test_full_agent_run_with_osm_provider(self):
        provider = OsmDiscoveryProvider(transport=FakeOverpassTransport())
        prefs = sample_prefs()
        state = {"days": {}, "ratings": {}, "do_not_show_again": []}
        outcome = run_agent(
            provider=provider,
            prefs=prefs,
            state=state,
            when=monday_noon(),
            simulated_response="order_it",
            skip_schedule_check=True,
            verbose=True,
        )
        assert outcome.status == "ordered"
        assert outcome.item_name is not None
        assert provider.last_discovery_report


class TestFactory:
    def test_build_osm_provider_fake_mode(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_OSM_MODE", "fake")
        provider = build_osm_provider()
        assert isinstance(provider, OsmDiscoveryProvider)
        assert provider.search_menu()
