"""Tests for Google Places enrichment and price estimation."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from google_places import (
    FakeGooglePlacesTransport,
    build_google_places_transport,
    enrich_restaurants_with_google,
    estimate_price_usd,
    match_google_place,
    names_match,
    price_level_label,
)
from osm_provider import OsmDiscoveryProvider, OsmRestaurant, restaurant_to_menu_item
from osm_provider import FakeOverpassTransport


def sample_restaurant(**overrides) -> OsmRestaurant:
    base = OsmRestaurant(
        osm_id="node/1",
        name="Kobe",
        cuisine="japanese",
        amenity="restaurant",
        opening_hours="Mo-Su 11:00-21:00",
        open_status="open",
        stars="",
        community_notes="",
        latitude=47.6158,
        longitude=-122.1958,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class TestPriceEstimation:
    def test_heuristic_fast_food(self):
        price, source = estimate_price_usd(amenity="fast_food", cuisine="burger")
        assert price == 11.0
        assert source == "heuristic"

    def test_google_price_level_overrides(self):
        price, source = estimate_price_usd(
            amenity="restaurant",
            cuisine="japanese",
            google_price_level=3,
        )
        assert price == 32.0
        assert source == "google"

    def test_price_level_label(self):
        assert price_level_label(2) == "$$"


class TestMatching:
    def test_names_match(self):
        assert names_match("Kobe", "Kobe Steakhouse")
        assert not names_match("Kobe", "McDonald's")

    def test_match_by_name_and_distance(self):
        transport = FakeGooglePlacesTransport()
        places = transport.nearby_restaurants(
            latitude=47.6160, longitude=-122.1968, radius_meters=600
        )
        matched = match_google_place(
            name="Kobe",
            latitude=47.6158,
            longitude=-122.1958,
            candidates=places,
        )
        assert matched is not None
        assert matched.price_level == 3
        assert matched.rating == 4.2


class TestEnrichment:
    def test_enrich_sets_google_fields(self):
        restaurant = sample_restaurant()
        transport = FakeGooglePlacesTransport()
        places = transport.nearby_restaurants(
            latitude=47.6160, longitude=-122.1968, radius_meters=600
        )
        matched = enrich_restaurants_with_google([restaurant], places)
        assert matched == 1
        assert restaurant.google_rating == 4.2
        assert restaurant.price_source == "google"
        assert restaurant.estimated_price_usd == 32.0

    def test_menu_item_includes_price_metadata(self):
        restaurant = sample_restaurant(
            estimated_price_usd=32.0,
            price_source="google",
            google_rating=4.2,
            google_review_count=890,
            google_price_level=3,
            google_maps_url="https://www.google.com/maps/place/?q=place_id:fake-kobe",
        )
        item = restaurant_to_menu_item(restaurant)
        assert item.price_usd == 32.0
        assert "price_source=google" in item.description
        assert "google_rating=4.2" in item.description


class TestFactory:
    def test_build_fake_transport(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_GOOGLE_PLACES_MODE", "fake")
        transport = build_google_places_transport()
        assert transport is not None
        assert transport.nearby_restaurants(
            latitude=47.6160, longitude=-122.1968, radius_meters=600
        )

    def test_live_requires_api_key(self, monkeypatch):
        monkeypatch.setattr("google_places.load_project_env", lambda *a, **k: None)
        monkeypatch.setenv("LUNCH_AGENT_GOOGLE_PLACES_MODE", "live")
        monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
        with pytest.raises(RuntimeError):
            build_google_places_transport()


class TestOsmIntegration:
    def test_discovery_with_google_fake_mode(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_GOOGLE_PLACES_MODE", "fake")
        provider = OsmDiscoveryProvider(transport=FakeOverpassTransport())
        provider.run_discovery(
            datetime(2026, 6, 22, 11, 55, 0, tzinfo=ZoneInfo("America/New_York"))
        )
        menu = provider.search_menu()
        kobe = next(item for item in menu if item.restaurant == "Blue Fin Sushi")
        assert "price_est=" in kobe.description
        assert kobe.price_usd != 15.0 or "price_source=google" in kobe.description
