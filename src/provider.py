"""Delivery platform adapter with a deterministic mock for local runs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

ITEM_TYPES = ("main", "side", "drink")


@dataclass(frozen=True)
class MenuItem:
    id: str
    name: str
    restaurant: str
    cuisine: str
    price_usd: float
    item_type: str = "main"
    allergens: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    description: str = ""
    allergen_confirmed: bool = True

    def __post_init__(self) -> None:
        if self.item_type not in ITEM_TYPES:
            raise ValueError(f"item_type must be one of {ITEM_TYPES}")


@dataclass
class OrderResult:
    success: bool
    order_id: str | None = None
    status: str = "unknown"
    message: str = ""
    item: MenuItem | None = None


class Provider(ABC):
    """Interface for ordering platforms."""

    @abstractmethod
    def search_menu(self, query: str | None = None) -> list[MenuItem]:
        """Return available menu items."""

    @abstractmethod
    def check_availability(self, item_id: str) -> bool:
        """Return True if the item can be ordered right now."""

    @abstractmethod
    def place_order(self, item_id: str, idempotency_key: str) -> OrderResult:
        """Place an order. Same idempotency_key must not double-charge."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> str:
        """Return order status: confirmed, pending, failed, unknown."""


MOCK_MENU: list[MenuItem] = [
    MenuItem(
        id="m1",
        name="Salmon Poke Bowl",
        restaurant="Blue Fin Sushi",
        cuisine="japanese",
        price_usd=16.50,
        item_type="main",
        allergens=("fish",),
        tags=("light", "raw"),
        description="Fresh salmon over rice with seaweed salad.",
    ),
    MenuItem(
        id="m2",
        name="Spicy Tuna Roll Combo",
        restaurant="Blue Fin Sushi",
        cuisine="japanese",
        price_usd=14.00,
        item_type="main",
        allergens=("fish",),
        tags=("spicy",),
        description="Eight-piece spicy tuna roll with miso soup.",
    ),
    MenuItem(
        id="m3",
        name="Shrimp Tempura Bento",
        restaurant="Blue Fin Sushi",
        cuisine="japanese",
        price_usd=17.00,
        item_type="main",
        allergens=("shellfish", "gluten"),
        tags=("fried",),
        description="Tempura shrimp with rice and pickles.",
    ),
    MenuItem(
        id="m4",
        name="Chicken Shawarma Plate",
        restaurant="Olive Grove",
        cuisine="mediterranean",
        price_usd=15.00,
        item_type="main",
        allergens=("gluten",),
        tags=("grilled",),
        description="Marinated chicken with hummus and pita.",
    ),
    MenuItem(
        id="m5",
        name="Falafel Wrap",
        restaurant="Olive Grove",
        cuisine="mediterranean",
        price_usd=12.50,
        item_type="main",
        allergens=("sesame",),
        tags=("vegetarian", "fried"),
        description="Crispy falafel with tahini in a wrap.",
    ),
    MenuItem(
        id="m6",
        name="Pad Thai with Peanuts",
        restaurant="Bangkok Kitchen",
        cuisine="thai",
        price_usd=13.50,
        item_type="main",
        allergens=("peanuts", "shellfish"),
        tags=("spicy",),
        description="Classic pad thai topped with crushed peanuts.",
    ),
    MenuItem(
        id="m7",
        name="Green Curry Chicken",
        restaurant="Bangkok Kitchen",
        cuisine="thai",
        price_usd=14.50,
        item_type="main",
        allergens=("fish",),
        tags=("spicy",),
        description="Coconut green curry with jasmine rice.",
    ),
    MenuItem(
        id="m8",
        name="Turkey Sandwich",
        restaurant="Corner Deli",
        cuisine="american",
        price_usd=11.00,
        item_type="main",
        allergens=("gluten",),
        tags=("sandwich",),
        description="Roasted turkey on whole wheat with lettuce.",
    ),
    MenuItem(
        id="m9",
        name="Garden Salad",
        restaurant="Corner Deli",
        cuisine="american",
        price_usd=9.50,
        item_type="main",
        allergens=(),
        tags=("vegetarian", "light"),
        description="Mixed greens with vinaigrette.",
    ),
    MenuItem(
        id="m10",
        name="Veggie Wrap",
        restaurant="Corner Deli",
        cuisine="american",
        price_usd=10.50,
        item_type="main",
        allergens=("gluten",),
        tags=("vegetarian",),
        description="Roasted vegetables in a spinach wrap.",
    ),
    MenuItem(
        id="m11",
        name="Chicken Tikka Masala",
        restaurant="Spice Route",
        cuisine="indian",
        price_usd=15.50,
        item_type="main",
        allergens=("dairy",),
        tags=("spicy",),
        description="Creamy tomato curry with basmati rice.",
    ),
    MenuItem(
        id="m12",
        name="Miso Soup",
        restaurant="Blue Fin Sushi",
        cuisine="japanese",
        price_usd=4.50,
        item_type="side",
        allergens=("soy",),
        tags=("light", "soup"),
        description="Traditional miso soup with tofu and scallions.",
    ),
    MenuItem(
        id="m13",
        name="Mystery Chef Special",
        restaurant="Daily Drop",
        cuisine="american",
        price_usd=12.00,
        item_type="main",
        allergens=(),
        tags=(),
        description="Changes daily. Allergens not listed on menu.",
        allergen_confirmed=False,
    ),
    MenuItem(
        id="m14",
        name="Liver and Onions",
        restaurant="Homestyle Grill",
        cuisine="american",
        price_usd=13.00,
        item_type="main",
        allergens=(),
        tags=("fried",),
        description="Pan-fried liver with caramelized onions.",
    ),
    MenuItem(
        id="m15",
        name="Premium Wagyu Bowl",
        restaurant="Blue Fin Sushi",
        cuisine="japanese",
        price_usd=24.00,
        item_type="main",
        allergens=("fish",),
        tags=("premium",),
        description="Wagyu over sushi rice with truffle oil.",
    ),
    MenuItem(
        id="m16",
        name="Fruit Cup",
        restaurant="Corner Deli",
        cuisine="american",
        price_usd=6.00,
        item_type="side",
        allergens=(),
        tags=("light", "vegetarian"),
        description="Seasonal cut fruit.",
    ),
    MenuItem(
        id="m17",
        name="Iced Green Tea",
        restaurant="Morning Table",
        cuisine="american",
        price_usd=3.50,
        item_type="drink",
        allergens=(),
        tags=("light",),
        description="Unsweetened iced green tea.",
    ),
]


class MockProvider(Provider):
    """Offline provider with fixed menu data for deterministic demos."""

    def __init__(
        self,
        fail_item_ids: set[str] | None = None,
        unknown_status_item_ids: set[str] | None = None,
        menu: list[MenuItem] | None = None,
    ) -> None:
        self._menu = list(menu) if menu is not None else list(MOCK_MENU)
        self._fail_item_ids = fail_item_ids or set()
        self._unknown_status_item_ids = unknown_status_item_ids or set()
        self._orders: dict[str, OrderResult] = {}
        self._idempotency: dict[str, str] = {}
        self.place_order_calls: list[tuple[str, str]] = []

    def search_menu(self, query: str | None = None) -> list[MenuItem]:
        if not query:
            return list(self._menu)
        needle = query.lower()
        return [
            item
            for item in self._menu
            if needle in item.name.lower()
            or needle in item.restaurant.lower()
            or needle in item.cuisine.lower()
        ]

    def check_availability(self, item_id: str) -> bool:
        return any(item.id == item_id for item in self._menu)

    def place_order(self, item_id: str, idempotency_key: str) -> OrderResult:
        self.place_order_calls.append((item_id, idempotency_key))

        if idempotency_key in self._idempotency:
            existing_id = self._idempotency[idempotency_key]
            return self._orders[existing_id]

        item = next((i for i in self._menu if i.id == item_id), None)
        if item is None:
            return OrderResult(
                success=False,
                status="failed",
                message=f"Unknown item: {item_id}",
            )

        if item_id in self._fail_item_ids:
            return OrderResult(
                success=False,
                status="failed",
                message=f"Placement failed for {item.name}",
                item=item,
            )

        order_id = f"mock-{idempotency_key}"
        status = "unknown" if item_id in self._unknown_status_item_ids else "confirmed"
        result = OrderResult(
            success=True,
            order_id=order_id,
            status=status,
            message=f"Ordered {item.name} from {item.restaurant}",
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


PROVIDERS: dict[str, type[Provider]] = {
    "mock": MockProvider,
}


def get_provider(name: str, **kwargs: Any) -> Provider:
    """Instantiate a provider by config name."""
    if name == "uber":
        from uber_provider import UberEatsProvider, build_uber_provider

        PROVIDERS.setdefault("uber", UberEatsProvider)
        return build_uber_provider(**kwargs)
    if name == "yelp":
        from yelp_provider import YelpDiscoveryProvider, build_yelp_provider

        PROVIDERS.setdefault("yelp", YelpDiscoveryProvider)
        return build_yelp_provider(**kwargs)
    if name == "osm":
        from osm_provider import OsmDiscoveryProvider, build_osm_provider

        PROVIDERS.setdefault("osm", OsmDiscoveryProvider)
        return build_osm_provider(**kwargs)
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}")
    return PROVIDERS[name](**kwargs)
