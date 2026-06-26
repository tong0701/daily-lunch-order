"""OpenStreetMap / Overpass restaurant discovery (no API key required)."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from env_loader import load_project_env
from order_links import build_doordash_search_url
from provider import MenuItem, MockProvider, OrderResult, Provider

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

WEEKDAY_CODES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

# Offline sample data near Bellevue Key Center (47.6160, -122.1968).
FAKE_OSM_ELEMENTS: list[dict[str, Any]] = [
    {
        "type": "node",
        "id": 1001,
        "lat": 47.6162,
        "lon": -122.1965,
        "tags": {
            "amenity": "restaurant",
            "name": "Blue Fin Sushi",
            "cuisine": "japanese",
            "opening_hours": "Mo-Fr 11:30-22:00; Sa-Su 12:00-23:00",
            "stars": "1",
            "description": "Popular omakase spot.",
        },
    },
    {
        "type": "node",
        "id": 1002,
        "lat": 47.6175,
        "lon": -122.1980,
        "tags": {
            "amenity": "restaurant",
            "name": "Olive Grove",
            "cuisine": "mediterranean",
            "opening_hours": "Mo-Su 11:00-21:00",
        },
    },
    {
        "type": "node",
        "id": 1003,
        "lat": 47.6148,
        "lon": -122.1945,
        "tags": {
            "amenity": "fast_food",
            "name": "Bangkok Kitchen",
            "cuisine": "thai",
            "opening_hours": "24/7",
        },
    },
    {
        "type": "node",
        "id": 1004,
        "lat": 47.6190,
        "lon": -122.2010,
        "tags": {
            "amenity": "cafe",
            "name": "Corner Deli",
            "cuisine": "sandwich",
            "opening_hours": "closed",
        },
    },
    {
        "type": "node",
        "id": 1005,
        "lat": 47.6135,
        "lon": -122.1920,
        "tags": {
            "amenity": "restaurant",
            "name": "Spice Route",
            "cuisine": "indian",
        },
    },
]


@dataclass
class OsmRestaurant:
    """Parsed restaurant from OSM tags."""

    osm_id: str
    name: str
    cuisine: str
    amenity: str
    opening_hours: str
    open_status: str  # open | closed | unknown
    stars: str
    community_notes: str
    latitude: float | None = None
    longitude: float | None = None
    distance_meters: float | None = None
    estimated_price_usd: float | None = None
    price_source: str = "heuristic"
    google_price_level: int | None = None
    google_rating: float | None = None
    google_review_count: int | None = None
    google_place_id: str = ""
    google_maps_url: str = ""

    @property
    def osm_url(self) -> str:
        osm_type, osm_num = self.osm_id.split("/", 1)
        return f"https://www.openstreetmap.org/{osm_type}/{osm_num}"

    @property
    def rating_label(self) -> str:
        if self.google_rating is not None:
            reviews = self.google_review_count or 0
            level = ""
            if self.google_price_level is not None:
                from google_places import price_level_label

                level = f", Google {price_level_label(self.google_price_level)}"
            return f"Google rating: {self.google_rating:.1f} ({reviews} reviews{level})"
        if self.stars:
            return f"Michelin stars: {self.stars}"
        return "Ratings: not available (OSM has no Yelp-style user reviews)"


@dataclass
class DiscoveryResult:
    """Three-step discovery output."""

    nearby: list[OsmRestaurant] = field(default_factory=list)
    open_today: list[OsmRestaurant] = field(default_factory=list)
    excluded_closed: list[OsmRestaurant] = field(default_factory=list)

    def format_report(self) -> str:
        lines = ["RESTAURANT DISCOVERY (OpenStreetMap / Overpass)", ""]
        lines.append(f"1) Nearby restaurants found: {len(self.nearby)}")
        for r in self.nearby:
            lines.append(
                f"   - {r.name} ({r.cuisine or r.amenity}) "
                f"[{r.open_status}] {r.rating_label}"
            )
        lines.append("")
        lines.append(f"2) Open today (or hours unknown): {len(self.open_today)}")
        for r in self.open_today:
            hours = r.opening_hours or "hours not listed"
            lines.append(f"   - {r.name}: {hours}")
        lines.append("")
        lines.append(f"3) Excluded as closed: {len(self.excluded_closed)}")
        for r in self.excluded_closed:
            lines.append(f"   - {r.name}: {r.opening_hours}")
        lines.append("")
        lines.append(
            "Note: OSM provides name, cuisine, opening_hours, and sometimes "
            "Michelin stars. It does not provide Yelp-style user review counts."
        )
        return "\n".join(lines)

    def format_discord_report(self, preview: int = 10) -> str:
        """Short user-facing discovery summary for Discord."""
        total = len(self.nearby)
        viable = len(self.open_today)
        closed = len(self.excluded_closed)
        lines = [
            "🔎 **Discovery complete**",
            f"Checked **{total}** nearby places · **{viable}** viable now · filtered **{closed}** closed",
            "Next: ranking by distance, price, rating, and your preferences.",
        ]
        return "\n".join(lines)


class OverpassTransport(ABC):
    """HTTP seam for Overpass API queries."""

    @abstractmethod
    def query_restaurants(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[dict[str, Any]]:
        """Return raw Overpass elements."""


class FakeOverpassTransport(OverpassTransport):
    """Offline canned Overpass results."""

    def __init__(self, elements: list[dict[str, Any]] | None = None) -> None:
        self._elements = list(elements) if elements is not None else list(FAKE_OSM_ELEMENTS)
        self.last_query: dict[str, Any] | None = None

    def query_restaurants(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[dict[str, Any]]:
        self.last_query = {
            "latitude": latitude,
            "longitude": longitude,
            "radius_meters": radius_meters,
        }
        return list(self._elements)


class HttpOverpassTransport(OverpassTransport):
    """Live Overpass API (no API key)."""

    def query_restaurants(
        self,
        *,
        latitude: float,
        longitude: float,
        radius_meters: int,
    ) -> list[dict[str, Any]]:
        query = f"""
[out:json][timeout:25];
(
  nwr["amenity"~"restaurant|fast_food|cafe"](around:{radius_meters},{latitude},{longitude});
);
out center tags;
"""
        data = urllib.parse.urlencode({"data": query}).encode("utf-8")
        req = urllib.request.Request(
            OVERPASS_URL,
            data=data,
            method="POST",
            headers={"User-Agent": "daily-lunch-order-agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("elements") or []


def build_overpass_transport(**kwargs: Any) -> OverpassTransport:
    load_project_env()
    mode = os.getenv("LUNCH_AGENT_OSM_MODE", "fake").lower()
    if mode == "live":
        return HttpOverpassTransport()
    return kwargs.pop("transport", None) or FakeOverpassTransport(
        elements=kwargs.pop("elements", None),
    )


def _parse_coordinates() -> tuple[float, float]:
    lat = os.getenv("OSM_LATITUDE", os.getenv("YELP_LATITUDE", "40.7580"))
    lng = os.getenv("OSM_LONGITUDE", os.getenv("YELP_LONGITUDE", "-73.9855"))
    return float(lat), float(lng)


def _parse_radius() -> int:
    return int(os.getenv("OSM_RADIUS_METERS", "1500"))


def _weekday_code(when: datetime) -> str:
    return WEEKDAY_CODES[when.weekday()]


def evaluate_open_status(opening_hours: str | None, when: datetime) -> str:
    """Best-effort open check from OSM opening_hours tag."""
    if not opening_hours or not opening_hours.strip():
        return "unknown"

    raw = opening_hours.strip()
    lowered = raw.lower()
    if lowered in {"24/7", "24/7 open"}:
        return "open"
    if lowered == "closed":
        return "closed"

    day = _weekday_code(when)
    if re.search(rf"\b{day}\b", raw, flags=re.IGNORECASE) is None:
        if re.search(r"Mo\s*-\s*Fr", raw, flags=re.IGNORECASE) and when.weekday() < 5:
            pass
        elif re.search(r"Mo\s*-\s*Su", raw, flags=re.IGNORECASE):
            pass
        elif re.search(r"Sa\s*-\s*Su", raw, flags=re.IGNORECASE) and when.weekday() >= 5:
            pass
        else:
            return "unknown"

    time_match = re.search(r"(\d{1,2}):?(\d{2})?\s*-\s*(\d{1,2}):?(\d{2})?", raw)
    if not time_match:
        return "unknown"

    start_h = int(time_match.group(1))
    start_m = int(time_match.group(2) or 0)
    end_h = int(time_match.group(3))
    end_m = int(time_match.group(4) or 0)
    now_minutes = when.hour * 60 + when.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    if start_minutes <= now_minutes <= end_minutes:
        return "open"
    return "closed"


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two coordinates."""
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _attach_distances(restaurants: list[OsmRestaurant], lat: float, lng: float) -> None:
    for restaurant in restaurants:
        if restaurant.latitude is None or restaurant.longitude is None:
            restaurant.distance_meters = None
            continue
        restaurant.distance_meters = haversine_meters(
            lat, lng, restaurant.latitude, restaurant.longitude
        )


def _element_to_restaurant(element: dict[str, Any], when: datetime) -> OsmRestaurant | None:
    tags = element.get("tags") or {}
    name = tags.get("name")
    if not name:
        return None

    opening_hours = str(tags.get("opening_hours", ""))
    osm_type = element.get("type", "node")
    osm_num = element.get("id")
    lat = element.get("lat")
    lon = element.get("lon")
    if lat is None and "center" in element:
        lat = element["center"].get("lat")
        lon = element["center"].get("lon")

    return OsmRestaurant(
        osm_id=f"{osm_type}/{osm_num}",
        name=str(name),
        cuisine=str(tags.get("cuisine", tags.get("amenity", "restaurant"))).lower(),
        amenity=str(tags.get("amenity", "restaurant")),
        opening_hours=opening_hours,
        open_status=evaluate_open_status(opening_hours, when),
        stars=str(tags.get("stars", "")),
        community_notes=str(tags.get("description", "")),
        latitude=float(lat) if lat is not None else None,
        longitude=float(lon) if lon is not None else None,
    )


def discover_restaurants(
    transport: OverpassTransport,
    when: datetime,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_meters: int | None = None,
) -> DiscoveryResult:
    """Run the 3-step discovery flow on OSM data."""
    default_lat, default_lng = _parse_coordinates()
    lat = latitude if latitude is not None else default_lat
    lng = longitude if longitude is not None else default_lng
    radius = radius_meters or _parse_radius()
    elements = transport.query_restaurants(
        latitude=lat, longitude=lng, radius_meters=radius
    )

    nearby: list[OsmRestaurant] = []
    for element in elements:
        parsed = _element_to_restaurant(element, when)
        if parsed is not None:
            nearby.append(parsed)

    _attach_distances(nearby, lat, lng)

    from google_places import (
        build_google_places_transport,
        enrich_restaurants_with_google,
        estimate_price_usd,
    )

    google_transport = build_google_places_transport()
    if google_transport is not None:
        google_places = google_transport.nearby_restaurants(
            latitude=lat, longitude=lng, radius_meters=radius
        )
        enrich_restaurants_with_google(nearby, google_places)
    else:
        for restaurant in nearby:
            price, source = estimate_price_usd(
                amenity=restaurant.amenity,
                cuisine=restaurant.cuisine,
            )
            restaurant.estimated_price_usd = price
            restaurant.price_source = source

    open_today = [r for r in nearby if r.open_status in {"open", "unknown"}]
    excluded_closed = [r for r in nearby if r.open_status == "closed"]
    return DiscoveryResult(
        nearby=nearby,
        open_today=open_today,
        excluded_closed=excluded_closed,
    )


def _restaurant_price_usd(restaurant: OsmRestaurant) -> float:
    if restaurant.estimated_price_usd is not None:
        return restaurant.estimated_price_usd
    from google_places import estimate_price_usd

    price, _source = estimate_price_usd(
        amenity=restaurant.amenity,
        cuisine=restaurant.cuisine,
        google_price_level=restaurant.google_price_level,
    )
    return price


def restaurant_to_menu_item(restaurant: OsmRestaurant) -> MenuItem:
    """Build a synthetic main item from OSM restaurant metadata."""
    dist_value = (
        str(int(round(restaurant.distance_meters)))
        if restaurant.distance_meters is not None
        else "unknown"
    )
    price = _restaurant_price_usd(restaurant)
    notes: list[str] = [
        f"OSM: {restaurant.osm_url}",
        f"dist_m={dist_value}",
        f"price_est={price:.2f}",
        f"price_source={restaurant.price_source}",
        f"hours={restaurant.opening_hours or 'not listed'}",
        f"hours_listed={'yes' if restaurant.opening_hours else 'no'}",
        restaurant.rating_label,
    ]
    if restaurant.google_price_level is not None:
        notes.append(f"google_price_level={restaurant.google_price_level}")
    if restaurant.google_rating is not None:
        notes.append(f"google_rating={restaurant.google_rating:.1f}")
    if restaurant.google_review_count is not None:
        notes.append(f"google_reviews={restaurant.google_review_count}")
    if restaurant.google_maps_url:
        notes.append(f"Google Maps: {restaurant.google_maps_url}")
    notes.append(f"DoorDash: {build_doordash_search_url(restaurant.name)}")
    if restaurant.stars:
        notes.append(f"michelin={restaurant.stars}")
    if restaurant.community_notes:
        notes.append(f"notes={restaurant.community_notes}")
    return MenuItem(
        id=f"osm-{restaurant.osm_id.replace('/', '-')}-lunch",
        name=f"Lunch at {restaurant.name}",
        restaurant=restaurant.name,
        cuisine=restaurant.cuisine,
        price_usd=price,
        item_type="main",
        allergens=(),
        tags=(restaurant.amenity,),
        description=" | ".join(notes),
        allergen_confirmed=True,
    )


def extract_osm_url(description: str) -> str:
    if "OSM:" not in description:
        return ""
    for part in description.split("|"):
        part = part.strip()
        if part.startswith("OSM:"):
            return part.split("OSM:", 1)[1].strip()
    return ""


def extract_google_maps_url(description: str) -> str:
    for part in description.split("|"):
        part = part.strip()
        if part.startswith("Google Maps:"):
            return part.split("Google Maps:", 1)[1].strip()
    return ""


class OsmDiscoveryProvider(Provider):
    """Discover restaurants from OSM; build lunch options from live metadata."""

    def __init__(
        self,
        transport: OverpassTransport | None = None,
        mock: MockProvider | None = None,
        *,
        fail_item_ids: set[str] | None = None,
        unknown_status_item_ids: set[str] | None = None,
    ) -> None:
        self._transport = transport or build_overpass_transport()
        self._mock = mock or MockProvider(
            fail_item_ids=fail_item_ids,
            unknown_status_item_ids=unknown_status_item_ids,
        )
        self._discovery: DiscoveryResult | None = None
        self._when: datetime | None = None
        self.last_discovery_report = ""
        self.last_discovery_discord_report = ""
        self._menu_cache: list[MenuItem] = []
        self._idempotency: dict[str, str] = {}
        self._orders: dict[str, OrderResult] = {}

    def run_discovery(self, when: datetime | None = None) -> DiscoveryResult:
        tz = ZoneInfo(os.getenv("OSM_TIMEZONE", "America/Los_Angeles"))
        self._when = when or datetime.now(tz)
        self._discovery = discover_restaurants(self._transport, self._when)
        self.last_discovery_report = self._discovery.format_report()
        self.last_discovery_discord_report = self._discovery.format_discord_report()
        return self._discovery

    def discovery_report(self, when: datetime | None = None) -> str:
        if self._discovery is None:
            self.run_discovery(when)
        return self.last_discovery_report

    def search_menu(self, query: str | None = None) -> list[MenuItem]:
        discovery = self.run_discovery(self._when)
        menu = [restaurant_to_menu_item(r) for r in discovery.open_today]
        if not menu:
            return []
        if not query:
            self._menu_cache = menu
            return menu
        filtered = [
            item
            for item in menu
            if needle in item.name.lower()
            or needle in item.restaurant.lower()
            or needle in item.cuisine.lower()
        ]
        self._menu_cache = filtered
        return filtered

    def check_availability(self, item_id: str) -> bool:
        if not self._menu_cache:
            self.search_menu()
        return any(item.id == item_id for item in self._menu_cache)

    def place_order(self, item_id: str, idempotency_key: str) -> OrderResult:
        if idempotency_key in self._idempotency:
            order_id = self._idempotency[idempotency_key]
            return self._orders[order_id]

        if not self._menu_cache:
            self.search_menu()
        item = next((i for i in self._menu_cache if i.id == item_id), None)
        if item is None:
            return OrderResult(
                success=False,
                status="failed",
                message=f"Unknown item: {item_id}",
            )

        order_id = f"osm-mock-{idempotency_key}"
        result = OrderResult(
            success=True,
            order_id=order_id,
            status="confirmed",
            message=(
                f"Status: selected {item.name} from {item.restaurant}. "
                "DoorDash remains a manual handoff."
            ),
            item=item,
        )
        self._idempotency[idempotency_key] = order_id
        self._orders[order_id] = result
        return result

    def get_order_status(self, order_id: str) -> str:
        order = self._orders.get(order_id)
        if order is None:
            return "unknown"
        return order.status


def build_osm_provider(**kwargs: Any) -> OsmDiscoveryProvider:
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = build_overpass_transport()
    return OsmDiscoveryProvider(transport=transport, **kwargs)
