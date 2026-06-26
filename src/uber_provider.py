"""Uber Eats Consumer Delivery provider (modeled flow, offline fake transport).

Uber's Consumer Delivery API is in early access. Public docs describe the flow
(account linking, merchant discovery, menu, cart, order submission, status) but
not exact endpoint paths or schemas. Paths and JSON shapes here are modeled
placeholders pending Uber early-access specification.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from provider import ITEM_TYPES, MenuItem, OrderResult, Provider

# Re-export for PROVIDERS registry (instantiation goes through build_uber_provider).
__all__ = [
    "UberEatsProvider",
    "UberTransport",
    "FakeUberTransport",
    "build_uber_provider",
]

# Modeled placeholder paths (pending Uber early-access spec).
PATH_MERCHANTS = "/v1/delivery/merchants"
PATH_MERCHANT_MENU = "/v1/delivery/merchants/{merchant_id}/menu"
PATH_MERCHANT_STATUS = "/v1/delivery/merchants/{merchant_id}/status"
PATH_ITEM_AVAILABILITY = "/v1/delivery/items/{item_id}/availability"
PATH_CARTS = "/v1/delivery/carts"
PATH_ORDERS = "/v1/delivery/orders"
PATH_ORDER_STATUS = "/v1/delivery/orders/{order_id}"

DEFAULT_API_BASE = "https://sandbox-api.uber.com"


def _category_to_item_type(category: str) -> str:
    normalized = category.upper()
    if normalized in {"ENTREE", "MAIN", "MAIN_COURSE"}:
        return "main"
    if normalized in {"SIDE", "APPETIZER", "DESSERT"}:
        return "side"
    if normalized in {"BEVERAGE", "DRINK"}:
        return "drink"
    return "main"


def _map_uber_item(raw: dict[str, Any]) -> MenuItem:
    """Map a modeled Uber menu item payload to MenuItem."""
    allergen_block = raw.get("allergens") or {}
    confirmed = bool(allergen_block.get("confirmed", False))
    tags = allergen_block.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    allergen_tags = tuple(str(t).lower() for t in tags)

    price_block = raw.get("price") or {}
    amount_cents = price_block.get("amount", 0)
    try:
        price_usd = float(amount_cents) / 100.0
    except (TypeError, ValueError):
        price_usd = 0.0

    dietary = raw.get("dietary_tags") or []
    if not isinstance(dietary, list):
        dietary = []

    return MenuItem(
        id=str(raw["item_id"]),
        name=str(raw.get("title", "")),
        restaurant=str(raw.get("merchant_name", "")),
        cuisine=str(raw.get("cuisine_type", "american")).lower(),
        price_usd=price_usd,
        item_type=_category_to_item_type(str(raw.get("item_category", "ENTREE"))),
        allergens=allergen_tags,
        tags=tuple(str(t).lower() for t in dietary),
        description=str(raw.get("description", "")),
        allergen_confirmed=confirmed,
    )


# Modeled placeholder catalog (pending Uber early-access spec).
FAKE_MERCHANTS: list[dict[str, Any]] = [
    {"merchant_id": "merchant-sushi", "name": "Blue Fin Sushi", "cuisine_type": "japanese", "is_open": True},
    {"merchant_id": "merchant-olive", "name": "Olive Grove", "cuisine_type": "mediterranean", "is_open": True},
    {"merchant_id": "merchant-bangkok", "name": "Bangkok Kitchen", "cuisine_type": "thai", "is_open": True},
    {"merchant_id": "merchant-deli", "name": "Corner Deli", "cuisine_type": "american", "is_open": True},
    {"merchant_id": "merchant-spice", "name": "Spice Route", "cuisine_type": "indian", "is_open": True},
    {"merchant_id": "merchant-drop", "name": "Daily Drop", "cuisine_type": "american", "is_open": True},
    {"merchant_id": "merchant-grill", "name": "Homestyle Grill", "cuisine_type": "american", "is_open": True},
    {"merchant_id": "merchant-tea", "name": "Morning Table", "cuisine_type": "american", "is_open": True},
]

FAKE_MENU_ITEMS: list[dict[str, Any]] = [
    {
        "item_id": "ue-m1",
        "title": "Salmon Poke Bowl",
        "merchant_id": "merchant-sushi",
        "merchant_name": "Blue Fin Sushi",
        "cuisine_type": "japanese",
        "price": {"amount": 1650, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": ["fish"]},
        "dietary_tags": ["light", "raw"],
        "description": "Fresh salmon over rice with seaweed salad.",
        "is_available": True,
    },
    {
        "item_id": "ue-m2",
        "title": "Spicy Tuna Roll Combo",
        "merchant_id": "merchant-sushi",
        "merchant_name": "Blue Fin Sushi",
        "cuisine_type": "japanese",
        "price": {"amount": 1400, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": ["fish"]},
        "dietary_tags": ["spicy"],
        "description": "Eight-piece spicy tuna roll with miso soup.",
        "is_available": True,
    },
    {
        "item_id": "ue-m3",
        "title": "Shrimp Tempura Bento",
        "merchant_id": "merchant-sushi",
        "merchant_name": "Blue Fin Sushi",
        "cuisine_type": "japanese",
        "price": {"amount": 1700, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": ["shellfish", "gluten"]},
        "dietary_tags": ["fried"],
        "description": "Tempura shrimp with rice and pickles.",
        "is_available": True,
    },
    {
        "item_id": "ue-m4",
        "title": "Chicken Shawarma Plate",
        "merchant_id": "merchant-olive",
        "merchant_name": "Olive Grove",
        "cuisine_type": "mediterranean",
        "price": {"amount": 1500, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": ["gluten"]},
        "dietary_tags": ["grilled"],
        "description": "Marinated chicken with hummus and pita.",
        "is_available": True,
    },
    {
        "item_id": "ue-m6",
        "title": "Pad Thai with Peanuts",
        "merchant_id": "merchant-bangkok",
        "merchant_name": "Bangkok Kitchen",
        "cuisine_type": "thai",
        "price": {"amount": 1350, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": ["peanuts", "shellfish"]},
        "dietary_tags": ["spicy"],
        "description": "Classic pad thai topped with crushed peanuts.",
        "is_available": True,
    },
    {
        "item_id": "ue-m8",
        "title": "Turkey Sandwich",
        "merchant_id": "merchant-deli",
        "merchant_name": "Corner Deli",
        "cuisine_type": "american",
        "price": {"amount": 1100, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": ["gluten"]},
        "dietary_tags": ["sandwich"],
        "description": "Roasted turkey on whole wheat with lettuce.",
        "is_available": True,
    },
    {
        "item_id": "ue-m9",
        "title": "Garden Salad",
        "merchant_id": "merchant-deli",
        "merchant_name": "Corner Deli",
        "cuisine_type": "american",
        "price": {"amount": 950, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": []},
        "dietary_tags": ["vegetarian", "light"],
        "description": "Mixed greens with vinaigrette.",
        "is_available": True,
    },
    {
        "item_id": "ue-m10",
        "title": "Veggie Wrap",
        "merchant_id": "merchant-deli",
        "merchant_name": "Corner Deli",
        "cuisine_type": "american",
        "price": {"amount": 1050, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": ["gluten"]},
        "dietary_tags": ["vegetarian"],
        "description": "Roasted vegetables in a spinach wrap.",
        "is_available": True,
    },
    {
        "item_id": "ue-m12",
        "title": "Miso Soup",
        "merchant_id": "merchant-sushi",
        "merchant_name": "Blue Fin Sushi",
        "cuisine_type": "japanese",
        "price": {"amount": 450, "currency": "USD"},
        "item_category": "SIDE",
        "allergens": {"confirmed": True, "tags": ["soy"]},
        "dietary_tags": ["light", "soup"],
        "description": "Traditional miso soup with tofu and scallions.",
        "is_available": True,
    },
    {
        "item_id": "ue-m13",
        "title": "Mystery Chef Special",
        "merchant_id": "merchant-drop",
        "merchant_name": "Daily Drop",
        "cuisine_type": "american",
        "price": {"amount": 1200, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": False, "tags": []},
        "dietary_tags": [],
        "description": "Changes daily. Allergens not listed on menu.",
        "is_available": True,
    },
    {
        "item_id": "ue-m14",
        "title": "Liver and Onions",
        "merchant_id": "merchant-grill",
        "merchant_name": "Homestyle Grill",
        "cuisine_type": "american",
        "price": {"amount": 1300, "currency": "USD"},
        "item_category": "ENTREE",
        "allergens": {"confirmed": True, "tags": []},
        "dietary_tags": ["fried"],
        "description": "Pan-fried liver with caramelized onions.",
        "is_available": True,
    },
    {
        "item_id": "ue-m17",
        "title": "Iced Green Tea",
        "merchant_id": "merchant-tea",
        "merchant_name": "Morning Table",
        "cuisine_type": "american",
        "price": {"amount": 350, "currency": "USD"},
        "item_category": "BEVERAGE",
        "allergens": {"confirmed": True, "tags": []},
        "dietary_tags": ["light"],
        "description": "Unsweetened iced green tea.",
        "is_available": True,
    },
]


class UberTransport(ABC):
    """HTTP seam for Uber Consumer Delivery calls (real or fake)."""

    @abstractmethod
    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        token: str | None,
    ) -> dict[str, Any]:
        """Return a modeled JSON response body."""


class FakeUberTransport(UberTransport):
    """Offline transport returning canned Consumer Delivery shaped responses."""

    def __init__(
        self,
        fail_item_ids: set[str] | None = None,
        unknown_status_item_ids: set[str] | None = None,
        merchants: list[dict[str, Any]] | None = None,
        menu_items: list[dict[str, Any]] | None = None,
    ) -> None:
        self._merchants = list(merchants) if merchants is not None else list(FAKE_MERCHANTS)
        self._menu_items = list(menu_items) if menu_items is not None else list(FAKE_MENU_ITEMS)
        self._fail_item_ids = fail_item_ids or set()
        self._unknown_status_item_ids = unknown_status_item_ids or set()
        self._orders: dict[str, dict[str, Any]] = {}
        self._carts: dict[str, dict[str, Any]] = {}
        self.submit_calls: list[dict[str, Any]] = []

    def _merchant_by_id(self, merchant_id: str) -> dict[str, Any] | None:
        return next((m for m in self._merchants if m["merchant_id"] == merchant_id), None)

    def _item_by_id(self, item_id: str) -> dict[str, Any] | None:
        return next((i for i in self._menu_items if i["item_id"] == item_id), None)

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        token: str | None,
    ) -> dict[str, Any]:
        if not token:
            return {"error": "missing_access_token"}

        if path == PATH_MERCHANTS and method.upper() == "GET":
            return {"merchants": self._merchants}

        if method.upper() == "GET" and path.startswith("/v1/delivery/merchants/") and path.endswith("/menu"):
            merchant_id = path.split("/")[4]
            items = [i for i in self._menu_items if i["merchant_id"] == merchant_id]
            return {"merchant_id": merchant_id, "items": items}

        if method.upper() == "GET" and path.startswith("/v1/delivery/merchants/") and path.endswith("/status"):
            merchant_id = path.split("/")[4]
            merchant = self._merchant_by_id(merchant_id)
            if merchant is None:
                return {"error": "merchant_not_found"}
            return {"merchant_id": merchant_id, "is_open": merchant.get("is_open", False)}

        if method.upper() == "GET" and path.startswith("/v1/delivery/items/") and path.endswith("/availability"):
            item_id = path.split("/")[4]
            item = self._item_by_id(item_id)
            if item is None:
                return {"item_id": item_id, "is_available": False}
            return {"item_id": item_id, "is_available": bool(item.get("is_available", True))}

        if path == PATH_CARTS and method.upper() == "POST":
            item_id = (payload or {}).get("item_id")
            cart_id = f"cart-{(payload or {}).get('idempotency_key', 'unknown')}"
            cart = {"cart_id": cart_id, "item_id": item_id, "status": "open"}
            self._carts[cart_id] = cart
            return cart

        if path == PATH_ORDERS and method.upper() == "POST":
            body = payload or {}
            item_id = body.get("item_id")
            idempotency_key = body.get("idempotency_key", "")
            self.submit_calls.append(body)

            item = self._item_by_id(str(item_id)) if item_id else None
            if item is None:
                return {
                    "success": False,
                    "order_id": None,
                    "status": "failed",
                    "message": f"Unknown item: {item_id}",
                }

            if str(item_id) in self._fail_item_ids:
                return {
                    "success": False,
                    "order_id": None,
                    "status": "failed",
                    "message": f"Placement failed for {item.get('title')}",
                }

            order_id = f"uber-{idempotency_key}"
            status = "unknown" if str(item_id) in self._unknown_status_item_ids else "confirmed"
            order = {
                "success": True,
                "order_id": order_id,
                "status": status,
                "message": f"Ordered {item.get('title')} from {item.get('merchant_name')}",
                "item_id": item_id,
            }
            self._orders[order_id] = order
            return order

        if method.upper() == "GET" and path.startswith("/v1/delivery/orders/"):
            order_id = path.split("/")[-1]
            order = self._orders.get(order_id)
            if order is None:
                return {"order_id": order_id, "status": "unknown"}
            return {"order_id": order_id, "status": order.get("status", "unknown")}

        return {"error": "unhandled_path", "path": path, "method": method}


class UberEatsProvider(Provider):
    """Provider modeled on Uber Consumer Delivery flow (offline by default)."""

    def __init__(
        self,
        transport: UberTransport | None = None,
        access_token: str | None = None,
        api_base: str | None = None,
        fail_item_ids: set[str] | None = None,
        unknown_status_item_ids: set[str] | None = None,
    ) -> None:
        self._transport = transport or FakeUberTransport(
            fail_item_ids=fail_item_ids,
            unknown_status_item_ids=unknown_status_item_ids,
        )
        token = access_token if access_token else os.getenv("UBER_ACCESS_TOKEN")
        self._access_token = token if token else "fake-linked-token"
        self._api_base = api_base or os.getenv("UBER_API_BASE", DEFAULT_API_BASE)
        self._menu_cache: list[MenuItem] | None = None
        self._item_merchants: dict[str, str] = {}
        self._idempotency: dict[str, str] = {}
        self._orders: dict[str, OrderResult] = {}
        self.place_order_calls: list[tuple[str, str]] = []

    def account_linked(self) -> bool:
        """Return True when a linked-account OAuth token is present.

        Real account linking (OAuth handshake with Uber) is out of scope and
        requires Uber Consumer Delivery early-access approval.
        """
        return bool(self._access_token)

    def _token(self) -> str | None:
        return self._access_token if self.account_linked() else None

    def _load_menu_items(self) -> list[MenuItem]:
        if self._menu_cache is not None:
            return list(self._menu_cache)

        if not self.account_linked():
            self._menu_cache = []
            return []

        # Merchant Discovery + Menu and Items (modeled placeholder flow).
        merchants_resp = self._transport.request(
            "GET", PATH_MERCHANTS, None, self._token()
        )
        merchants = merchants_resp.get("merchants") or []

        items: list[MenuItem] = []
        for merchant in merchants:
            merchant_id = merchant.get("merchant_id")
            if not merchant_id:
                continue
            menu_path = PATH_MERCHANT_MENU.format(merchant_id=merchant_id)
            menu_resp = self._transport.request("GET", menu_path, None, self._token())
            for raw in menu_resp.get("items") or []:
                mapped = _map_uber_item(raw)
                if mapped.item_type not in ITEM_TYPES:
                    continue
                merchant_key = str(raw.get("merchant_id", ""))
                if merchant_key:
                    self._item_merchants[mapped.id] = merchant_key
                items.append(mapped)

        self._menu_cache = items
        return list(items)

    def search_menu(self, query: str | None = None) -> list[MenuItem]:
        # Consumer Delivery: Merchant Discovery + Menu and Items.
        menu = self._load_menu_items()
        if not query:
            return menu
        needle = query.lower()
        return [
            item
            for item in menu
            if needle in item.name.lower()
            or needle in item.restaurant.lower()
            or needle in item.cuisine.lower()
        ]

    def check_availability(self, item_id: str) -> bool:
        # Consumer Delivery: store open + item availability.
        if not self.account_linked():
            return False

        menu = self._load_menu_items()
        item = next((i for i in menu if i.id == item_id), None)
        if item is None:
            return False

        raw = next((r for r in FAKE_MENU_ITEMS if r["item_id"] == item_id), None)
        if raw is None and isinstance(self._transport, FakeUberTransport):
            raw = self._transport._item_by_id(item_id)
        merchant_id = self._item_merchants.get(item_id)
        if not merchant_id and raw:
            merchant_id = raw.get("merchant_id")
        if not merchant_id:
            return False

        status_path = PATH_MERCHANT_STATUS.format(merchant_id=merchant_id)
        status_resp = self._transport.request("GET", status_path, None, self._token())
        if not status_resp.get("is_open"):
            return False

        avail_path = PATH_ITEM_AVAILABILITY.format(item_id=item_id)
        avail_resp = self._transport.request("GET", avail_path, None, self._token())
        return bool(avail_resp.get("is_available"))

    def place_order(self, item_id: str, idempotency_key: str) -> OrderResult:
        # Consumer Delivery: Account Linking + Cart creation + Order Submission.
        self.place_order_calls.append((item_id, idempotency_key))

        if not self.account_linked():
            return OrderResult(
                success=False,
                status="failed",
                message="Uber account is not linked. Provide UBER_ACCESS_TOKEN.",
            )

        if idempotency_key in self._idempotency:
            existing_id = self._idempotency[idempotency_key]
            return self._orders[existing_id]

        menu = self._load_menu_items()
        item = next((i for i in menu if i.id == item_id), None)
        if item is None:
            return OrderResult(
                success=False,
                status="failed",
                message=f"Unknown item: {item_id}",
            )

        if not self.check_availability(item_id):
            return OrderResult(
                success=False,
                status="failed",
                message=f"Item not available: {item.name}",
                item=item,
            )

        # Cart creation (modeled placeholder).
        cart_resp = self._transport.request(
            "POST",
            PATH_CARTS,
            {"item_id": item_id, "idempotency_key": idempotency_key},
            self._token(),
        )
        if cart_resp.get("error"):
            return OrderResult(
                success=False,
                status="failed",
                message=str(cart_resp.get("error")),
                item=item,
            )

        # Order submission (modeled placeholder).
        submit_resp = self._transport.request(
            "POST",
            PATH_ORDERS,
            {
                "item_id": item_id,
                "cart_id": cart_resp.get("cart_id"),
                "idempotency_key": idempotency_key,
            },
            self._token(),
        )

        if not submit_resp.get("success"):
            return OrderResult(
                success=False,
                status=submit_resp.get("status", "failed"),
                message=submit_resp.get("message", "Order submission failed"),
                item=item,
            )

        order_id = str(submit_resp.get("order_id"))
        status = str(submit_resp.get("status", "unknown"))
        result = OrderResult(
            success=True,
            order_id=order_id,
            status=status,
            message=str(submit_resp.get("message", "")),
            item=item,
        )
        self._idempotency[idempotency_key] = order_id
        self._orders[order_id] = result
        return result

    def get_order_status(self, order_id: str) -> str:
        # Consumer Delivery: Order Status Notifications (modeled GET fallback).
        if not self.account_linked():
            return "unknown"

        cached = self._orders.get(order_id)
        if cached is not None:
            return cached.status

        status_path = PATH_ORDER_STATUS.format(order_id=order_id)
        resp = self._transport.request("GET", status_path, None, self._token())
        return str(resp.get("status", "unknown"))


def build_uber_provider(**kwargs: Any) -> UberEatsProvider:
    """Build UberEatsProvider from env (fake mode by default, offline)."""
    mode = os.getenv("LUNCH_AGENT_UBER_MODE", "fake").lower()
    if mode == "live":
        raise NotImplementedError(
            "Live Uber Consumer Delivery access requires Uber early-access approval "
            "and a real HTTP transport. Set LUNCH_AGENT_UBER_MODE=fake for offline demo."
        )

    transport = kwargs.pop("transport", None)
    if transport is None:
        transport = FakeUberTransport(
            fail_item_ids=kwargs.pop("fail_item_ids", None),
            unknown_status_item_ids=kwargs.pop("unknown_status_item_ids", None),
        )
    else:
        kwargs.pop("fail_item_ids", None)
        kwargs.pop("unknown_status_item_ids", None)

    if "access_token" not in kwargs:
        token = os.getenv("UBER_ACCESS_TOKEN")
        kwargs["access_token"] = token if token else None

    # UBER_CLIENT_ID and UBER_CLIENT_SECRET reserved for future live OAuth transport.
    _ = os.getenv("UBER_CLIENT_ID")
    _ = os.getenv("UBER_CLIENT_SECRET")
    _ = os.getenv("UBER_API_BASE", DEFAULT_API_BASE)

    return UberEatsProvider(transport=transport, **kwargs)
