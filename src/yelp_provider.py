"""Yelp Fusion discovery layer: live nearby restaurants, mock menu catalog."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any

from env_loader import load_project_env
from provider import MOCK_MENU, MenuItem, MockProvider, OrderResult, Provider

YELP_API_BASE = "https://api.yelp.com/v3"

# Modeled on Yelp Fusion business search (public docs).
FAKE_YELP_BUSINESSES: list[dict[str, Any]] = [
    {
        "id": "yelp-blue-fin-sushi",
        "name": "Blue Fin Sushi",
        "url": "https://www.yelp.com/biz/blue-fin-sushi-new-york",
        "categories": [{"alias": "japanese", "title": "Japanese"}],
        "price": "$$",
        "rating": 4.5,
        "is_closed": False,
    },
    {
        "id": "yelp-olive-grove",
        "name": "Olive Grove",
        "url": "https://www.yelp.com/biz/olive-grove-new-york",
        "categories": [{"alias": "mediterranean", "title": "Mediterranean"}],
        "price": "$$",
        "rating": 4.3,
        "is_closed": False,
    },
    {
        "id": "yelp-bangkok-kitchen",
        "name": "Bangkok Kitchen",
        "url": "https://www.yelp.com/biz/bangkok-kitchen-new-york",
        "categories": [{"alias": "thai", "title": "Thai"}],
        "price": "$",
        "rating": 4.2,
        "is_closed": False,
    },
    {
        "id": "yelp-corner-deli",
        "name": "Corner Deli",
        "url": "https://www.yelp.com/biz/corner-deli-new-york",
        "categories": [{"alias": "tradamerican", "title": "American"}],
        "price": "$",
        "rating": 4.0,
        "is_closed": False,
    },
    {
        "id": "yelp-spice-route",
        "name": "Spice Route",
        "url": "https://www.yelp.com/biz/spice-route-new-york",
        "categories": [{"alias": "indpak", "title": "Indian"}],
        "price": "$$",
        "rating": 4.4,
        "is_closed": False,
    },
]


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _names_match(restaurant: str, yelp_name: str) -> bool:
    a = _normalize_name(restaurant)
    b = _normalize_name(yelp_name)
    if not a or not b:
        return False
    return a in b or b in a


class YelpTransport(ABC):
    """HTTP seam for Yelp Fusion business search."""

    @abstractmethod
    def search_businesses(
        self,
        *,
        latitude: float,
        longitude: float,
        term: str = "lunch",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return open businesses near a point (modeled Fusion search shape)."""


class FakeYelpTransport(YelpTransport):
    """Offline canned Yelp search results."""

    def __init__(self, businesses: list[dict[str, Any]] | None = None) -> None:
        self._businesses = list(businesses) if businesses is not None else list(FAKE_YELP_BUSINESSES)
        self.last_search: dict[str, Any] | None = None

    def search_businesses(
        self,
        *,
        latitude: float,
        longitude: float,
        term: str = "lunch",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.last_search = {
            "latitude": latitude,
            "longitude": longitude,
            "term": term,
            "limit": limit,
        }
        open_businesses = [b for b in self._businesses if not b.get("is_closed")]
        return open_businesses[:limit]


class HttpYelpTransport(YelpTransport):
    """Live Yelp Fusion REST transport."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search_businesses(
        self,
        *,
        latitude: float,
        longitude: float,
        term: str = "lunch",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "term": term,
                "open_now": "true",
                "limit": min(limit, 50),
                "sort_by": "rating",
            }
        )
        url = f"{YELP_API_BASE}/businesses/search?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        businesses = payload.get("businesses") or []
        return [b for b in businesses if not b.get("is_closed", False)]


def build_yelp_transport(**kwargs: Any) -> YelpTransport:
    load_project_env()
    mode = os.getenv("LUNCH_AGENT_YELP_MODE", "fake").lower()
    if mode == "live":
        api_key = os.getenv("YELP_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "Live Yelp mode requires YELP_API_KEY. Set LUNCH_AGENT_YELP_MODE=fake for offline demo."
            )
        return HttpYelpTransport(api_key)
    return kwargs.pop("transport", None) or FakeYelpTransport(
        businesses=kwargs.pop("businesses", None),
    )


def _parse_coordinates() -> tuple[float, float]:
    lat = os.getenv("YELP_LATITUDE", "40.7580")
    lng = os.getenv("YELP_LONGITUDE", "-73.9855")
    return float(lat), float(lng)


def _yelp_url_for_restaurant(businesses: list[dict[str, Any]], restaurant: str) -> str:
    for biz in businesses:
        if _names_match(restaurant, str(biz.get("name", ""))):
            return str(biz.get("url") or "")
    return ""


def extract_yelp_url(description: str) -> str:
    if "Yelp:" not in description:
        return ""
    return description.split("Yelp:", 1)[1].strip()


class YelpDiscoveryProvider(Provider):
    """Discover open restaurants via Yelp; pick meals from mock catalog."""

    def __init__(
        self,
        transport: YelpTransport | None = None,
        mock: MockProvider | None = None,
        menu_catalog: list[MenuItem] | None = None,
        *,
        fail_item_ids: set[str] | None = None,
        unknown_status_item_ids: set[str] | None = None,
    ) -> None:
        self._transport = transport or build_yelp_transport()
        catalog = menu_catalog or list(MOCK_MENU)
        self._mock = mock or MockProvider(
            menu=catalog,
            fail_item_ids=fail_item_ids,
            unknown_status_item_ids=unknown_status_item_ids,
        )
        self._businesses: list[dict[str, Any]] | None = None
        self.discovery_fallback = False

    def discover_businesses(self) -> list[dict[str, Any]]:
        """Yelp Fusion: nearby open restaurants (menu still from mock catalog)."""
        if self._businesses is None:
            lat, lng = _parse_coordinates()
            self._businesses = self._transport.search_businesses(
                latitude=lat,
                longitude=lng,
                term=os.getenv("YELP_SEARCH_TERM", "lunch"),
            )
        return list(self._businesses)

    def _filter_menu_to_discovered(self, menu: list[MenuItem]) -> list[MenuItem]:
        businesses = self.discover_businesses()
        if not businesses:
            self.discovery_fallback = True
            return menu

        enriched: list[MenuItem] = []
        for item in menu:
            matched = False
            yelp_url = ""
            for biz in businesses:
                if _names_match(item.restaurant, str(biz.get("name", ""))):
                    matched = True
                    yelp_url = str(biz.get("url") or "")
                    break
            if not matched:
                continue
            description = item.description
            if yelp_url and "Yelp:" not in description:
                suffix = f"Yelp: {yelp_url}"
                description = f"{description} {suffix}".strip() if description else suffix
            enriched.append(replace(item, description=description))

        if not enriched:
            self.discovery_fallback = True
            return menu

        self.discovery_fallback = False
        return enriched

    def search_menu(self, query: str | None = None) -> list[MenuItem]:
        base_menu = self._mock.search_menu(query)
        discovered_menu = self._filter_menu_to_discovered(base_menu)
        if not query:
            return discovered_menu
        needle = query.lower()
        return [
            item
            for item in discovered_menu
            if needle in item.name.lower()
            or needle in item.restaurant.lower()
            or needle in item.cuisine.lower()
        ]

    def check_availability(self, item_id: str) -> bool:
        return self._mock.check_availability(item_id)

    def place_order(self, item_id: str, idempotency_key: str) -> OrderResult:
        # Order placement is simulated; Yelp Fusion does not expose consumer ordering.
        return self._mock.place_order(item_id, idempotency_key)

    def get_order_status(self, order_id: str) -> str:
        return self._mock.get_order_status(order_id)


def build_yelp_provider(**kwargs: Any) -> YelpDiscoveryProvider:
    """Build YelpDiscoveryProvider from env (fake mode by default, offline)."""
    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = build_yelp_transport()
    return YelpDiscoveryProvider(transport=transport, **kwargs)
