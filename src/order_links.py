"""Deep links to delivery apps for manual checkout after agent confirmation."""

from __future__ import annotations

import urllib.parse


def build_doordash_search_url(restaurant: str) -> str:
    """DoorDash store search for a restaurant name.

    DoorDash only renders the search results page when the ``event_type=search``
    query parameter is present; without it the path does not resolve to a search.
    Results are still delivery-address dependent on DoorDash's side.
    """
    name = restaurant.strip()
    segment = urllib.parse.quote(name, safe="")
    return f"https://www.doordash.com/search/store/{segment}?event_type=search"


def build_ubereats_search_url(restaurant: str) -> str:
    """Uber Eats search fallback."""
    query = urllib.parse.quote(restaurant.strip())
    return f"https://www.ubereats.com/search?q={query}"


def order_link_lines(restaurant: str, description: str = "") -> list[str]:
    """User-facing order links for confirmation and outcome messages."""
    doordash = extract_doordash_url(description) or build_doordash_search_url(restaurant)
    lines = [f"Order on DoorDash: {doordash}"]
    maps = extract_google_maps_url(description)
    if maps:
        lines.append(f"Google Maps: {maps}")
    return lines


def extract_doordash_url(description: str) -> str:
    return _extract_prefixed_url(description, "DoorDash:")


def extract_google_maps_url(description: str) -> str:
    return _extract_prefixed_url(description, "Google Maps:")


def _extract_prefixed_url(description: str, prefix: str) -> str:
    for part in description.split("|"):
        part = part.strip()
        if part.startswith(prefix):
            return part.split(prefix, 1)[1].strip()
    return ""
