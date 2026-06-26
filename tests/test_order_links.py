"""Tests for delivery app deep links."""

from __future__ import annotations

from order_links import (
    build_doordash_search_url,
    extract_doordash_url,
    order_link_lines,
)


class TestOrderLinks:
    def test_doordash_search_url(self):
        url = build_doordash_search_url("Chipotle")
        assert url.startswith("https://www.doordash.com/search/store/")
        assert "Chipotle" in url
        assert "event_type=search" in url

    def test_doordash_url_with_spaces(self):
        url = build_doordash_search_url("Hummus Republic")
        assert "Hummus" in url

    def test_extract_embedded_doordash_url(self):
        description = "dist_m=100 | DoorDash: https://www.doordash.com/search/store/test"
        assert extract_doordash_url(description) == "https://www.doordash.com/search/store/test"

    def test_order_link_lines(self):
        lines = order_link_lines(
            "Kobe",
            "Google Maps: https://maps.google.com/?q=place_id:abc | "
            "DoorDash: https://www.doordash.com/search/store/Kobe",
        )
        assert any(line.startswith("Order on DoorDash:") for line in lines)
        assert any(line.startswith("Google Maps:") for line in lines)
