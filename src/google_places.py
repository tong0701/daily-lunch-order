"""Google Places enrichment for restaurant price and ratings (optional API key)."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from env_loader import load_project_env

GOOGLE_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# Lunch-oriented USD estimates from Google price_level (1-4). Not exact per-person checks.
GOOGLE_PRICE_LEVEL_USD: dict[int, float] = {
    1: 12.0,
    2: 20.0,
    3: 32.0,
    4: 50.0,
}

AMENITY_BASE_USD: dict[str, float] = {
    "fast_food": 12.0,
    "cafe": 15.0,
    "restaurant": 25.0,
}

CUISINE_ADJUST_USD: dict[str, float] = {
    "sushi": 6.0,
    "japanese": 4.0,
    "steak_house": 12.0,
    "steak": 12.0,
    "french": 8.0,
    "seafood": 6.0,
    "italian": 3.0,
    "mexican": 2.0,
    "thai": 2.0,
    "indian": 2.0,
    "pizza": -2.0,
    "sandwich": -2.0,
    "burger": -1.0,
    "coffee_shop": -3.0,
    "bubble_tea": -4.0,
}

# Offline sample places near Bellevue Key Center for tests.
FAKE_GOOGLE_PLACES: list[dict[str, Any]] = [
    {
        "name": "Blue Fin Sushi",
        "lat": 47.6162,
        "lng": -122.1965,
        "price_level": 2,
        "rating": 4.4,
        "user_ratings_total": 320,
        "place_id": "fake-blue-fin",
    },
    {
        "name": "Hummus Republic",
        "lat": 47.6170,
        "lng": -122.1975,
        "price_level": 1,
        "rating": 4.6,
        "user_ratings_total": 210,
        "place_id": "fake-hummus",
    },
    {
        "name": "Kobe",
        "lat": 47.6158,
        "lng": -122.1958,
        "price_level": 3,
        "rating": 4.2,
        "user_ratings_total": 890,
        "place_id": "fake-kobe",
    },
]


@dataclass
class GooglePlace:
    name: str
    latitude: float
    longitude: float
    price_level: int | None = None
    rating: float | None = None
    review_count: int | None = None
    place_id: str = ""

    @property
    def maps_url(self) -> str:
        if not self.place_id:
            return ""
        return f"https://www.google.com/maps/place/?q=place_id:{self.place_id}"


class GooglePlacesTransport(ABC):
    @abstractmethod
    def nearby_restaurants(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[GooglePlace]:
        """Return nearby restaurants from Google Places."""


class FakeGooglePlacesTransport(GooglePlacesTransport):
    def __init__(self, places: list[dict[str, Any]] | None = None) -> None:
        self._places = places if places is not None else list(FAKE_GOOGLE_PLACES)

    def nearby_restaurants(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[GooglePlace]:
        del latitude, longitude, radius_meters
        return [_dict_to_place(p) for p in self._places]


class HttpGooglePlacesTransport(GooglePlacesTransport):
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def nearby_restaurants(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[GooglePlace]:
        places: list[GooglePlace] = []
        params: dict[str, str] = {
            "location": f"{latitude},{longitude}",
            "radius": str(radius_meters),
            "type": "restaurant",
            "key": self._api_key,
        }
        url = f"{GOOGLE_NEARBY_URL}?{urllib.parse.urlencode(params)}"
        while url:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "daily-lunch-order-agent/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            status = payload.get("status")
            if status not in {"OK", "ZERO_RESULTS"}:
                raise RuntimeError(
                    f"Google Places API error: {status} ({payload.get('error_message', '')})"
                )
            for result in payload.get("results") or []:
                place = _result_to_place(result)
                if place is not None:
                    places.append(place)
            next_token = payload.get("next_page_token")
            if not next_token:
                break
            time.sleep(2.0)
            url = (
                f"{GOOGLE_NEARBY_URL}?"
                f"{urllib.parse.urlencode({'pagetoken': next_token, 'key': self._api_key})}"
            )
        return places


def build_google_places_transport(**kwargs: Any) -> GooglePlacesTransport | None:
    load_project_env()
    mode = os.getenv("LUNCH_AGENT_GOOGLE_PLACES_MODE", "off").lower()
    if mode == "off":
        return None
    if mode == "fake":
        return kwargs.pop("transport", None) or FakeGooglePlacesTransport(
            places=kwargs.pop("places", None),
        )
    if mode == "live":
        api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "LUNCH_AGENT_GOOGLE_PLACES_MODE=live requires GOOGLE_PLACES_API_KEY"
            )
        return HttpGooglePlacesTransport(api_key)
    raise ValueError(f"Unknown Google Places mode: {mode}")


def google_places_enabled() -> bool:
    load_project_env()
    return os.getenv("LUNCH_AGENT_GOOGLE_PLACES_MODE", "off").lower() in {
        "fake",
        "live",
    }


def _dict_to_place(data: dict[str, Any]) -> GooglePlace:
    return GooglePlace(
        name=str(data["name"]),
        latitude=float(data["lat"]),
        longitude=float(data["lng"]),
        price_level=int(data["price_level"]) if data.get("price_level") is not None else None,
        rating=float(data["rating"]) if data.get("rating") is not None else None,
        review_count=int(data["user_ratings_total"])
        if data.get("user_ratings_total") is not None
        else None,
        place_id=str(data.get("place_id", "")),
    )


def _result_to_place(result: dict[str, Any]) -> GooglePlace | None:
    name = result.get("name")
    geometry = result.get("geometry") or {}
    location = geometry.get("location") or {}
    lat = location.get("lat")
    lng = location.get("lng")
    if not name or lat is None or lng is None:
        return None
    price_level = result.get("price_level")
    rating = result.get("rating")
    return GooglePlace(
        name=str(name),
        latitude=float(lat),
        longitude=float(lng),
        price_level=int(price_level) if price_level is not None else None,
        rating=float(rating) if rating is not None else None,
        review_count=int(result["user_ratings_total"])
        if result.get("user_ratings_total") is not None
        else None,
        place_id=str(result.get("place_id", "")),
    )


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def names_match(a: str, b: str) -> bool:
    left = normalize_name(a)
    right = normalize_name(b)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def estimate_price_usd(
    *,
    amenity: str,
    cuisine: str,
    google_price_level: int | None = None,
) -> tuple[float, str]:
    """Return (price_usd, price_source). Google price_level overrides heuristic."""
    if google_price_level is not None and google_price_level in GOOGLE_PRICE_LEVEL_USD:
        return GOOGLE_PRICE_LEVEL_USD[google_price_level], "google"

    base = AMENITY_BASE_USD.get(amenity, 20.0)
    adjustment = 0.0
    for token in re.split(r"[;,]", cuisine.lower()):
        token = token.strip()
        if token in CUISINE_ADJUST_USD:
            adjustment += CUISINE_ADJUST_USD[token]
    return round(max(8.0, base + adjustment), 2), "heuristic"


def price_level_label(price_level: int | None) -> str:
    if price_level is None:
        return "unknown"
    return {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}.get(price_level, "unknown")


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def match_google_place(
    *,
    name: str,
    latitude: float | None,
    longitude: float | None,
    candidates: list[GooglePlace],
    max_distance_meters: float = 120.0,
) -> GooglePlace | None:
    if latitude is None or longitude is None:
        return None
    best: GooglePlace | None = None
    best_distance = max_distance_meters + 1
    for place in candidates:
        if not names_match(name, place.name):
            continue
        distance = haversine_meters(latitude, longitude, place.latitude, place.longitude)
        if distance <= max_distance_meters and distance < best_distance:
            best = place
            best_distance = distance
    return best


def enrich_restaurants_with_google(
    restaurants: list[Any],
    google_places: list[GooglePlace],
) -> int:
    """Attach Google fields to OsmRestaurant objects. Returns match count."""
    matched = 0
    for restaurant in restaurants:
        place = match_google_place(
            name=restaurant.name,
            latitude=restaurant.latitude,
            longitude=restaurant.longitude,
            candidates=google_places,
        )
        if place is None:
            price, source = estimate_price_usd(
                amenity=restaurant.amenity,
                cuisine=restaurant.cuisine,
            )
            restaurant.estimated_price_usd = price
            restaurant.price_source = source
            continue
        matched += 1
        restaurant.google_price_level = place.price_level
        restaurant.google_rating = place.rating
        restaurant.google_review_count = place.review_count
        restaurant.google_place_id = place.place_id
        restaurant.google_maps_url = place.maps_url
        price, source = estimate_price_usd(
            amenity=restaurant.amenity,
            cuisine=restaurant.cuisine,
            google_price_level=place.price_level,
        )
        restaurant.estimated_price_usd = price
        restaurant.price_source = source
    return matched
