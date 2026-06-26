"""Discord confirmation channel for lunch agent (REST API, offline-testable)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from env_loader import load_project_env

DISCORD_API_BASE = "https://discord.com/api/v10"

ORDER_ALIASES = frozenset({"1", "order", "order_it", "yes", "y", "ok", "好", "下单"})
ANOTHER_ALIASES = frozenset({"2", "another", "show_another", "swap", "change", "换", "换一个"})
SKIP_ALIASES = frozenset({"3", "skip", "not_today", "no", "不吃", "今天不吃了"})


def parse_user_action(content: str) -> str | None:
    """Map free-text Discord reply to agent action name."""
    text = content.strip().lower()
    if not text:
        return None
    first = text.split()[0]
    if text in ORDER_ALIASES or first in ORDER_ALIASES:
        return "order_it"
    if text in ANOTHER_ALIASES or first in ANOTHER_ALIASES:
        return "show_another"
    if text in SKIP_ALIASES or first in SKIP_ALIASES:
        return "not_today"
    return None


def format_lunch_message(
    item_name: str,
    restaurant: str,
    price_usd: float,
    lead_min: int,
    yelp_url: str = "",
    place_url: str = "",
    recommendation_details: list[str] | None = None,
    discovery_preamble: str = "",
) -> str:
    lines: list[str] = [f"Hey! \U0001f44b **Lunch pick for you**"]
    if discovery_preamble:
        lines.extend(["", discovery_preamble])
    lines.append("")
    lines.append(f"\U0001f37d\ufe0f **{restaurant}** \u00b7 lunch in ~{lead_min} min")
    dish = item_name.strip()
    if dish.lower() not in {f"lunch at {restaurant}".lower(), restaurant.lower()}:
        lines.append(f"_{dish}_")

    if recommendation_details:
        lines.extend(recommendation_details)
    else:
        lines.append(f"\U0001f4b5 ~${price_usd:.0f}/person")
        url = place_url or yelp_url
        if url:
            lines.append(f"\U0001f5fa\ufe0f Map: {url}")

    lines.extend(
        [
            "",
            "**1\ufe0f\u20e3 order   \u00b7   2\ufe0f\u20e3 another   \u00b7   3\ufe0f\u20e3 skip**",
        ]
    )
    return "\n".join(lines)


class DiscordTransport(ABC):
    """HTTP seam for Discord channel messages."""

    @abstractmethod
    def send_message(self, channel_id: str, content: str, token: str) -> dict[str, Any]:
        """Post a message. Returns message payload with id."""

    @abstractmethod
    def list_messages(
        self,
        channel_id: str,
        token: str,
        after: str | None,
    ) -> list[dict[str, Any]]:
        """Return recent channel messages (newest first)."""


class HttpDiscordTransport(DiscordTransport):
    """Live Discord REST transport (requires bot token and channel access)."""

    def _request(
        self,
        method: str,
        path: str,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{DISCORD_API_BASE}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "User-Agent": "lunch-agent (https://github.com/local, 1.0)",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def send_message(self, channel_id: str, content: str, token: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/channels/{channel_id}/messages",
            token,
            {"content": content},
        )

    def list_messages(
        self,
        channel_id: str,
        token: str,
        after: str | None,
    ) -> list[dict[str, Any]]:
        # Fetch recent messages; caller filters by snowflake id.
        path = f"/channels/{channel_id}/messages?limit=25"
        result = self._request("GET", path, token)
        return result if isinstance(result, list) else []


class FakeDiscordTransport(DiscordTransport):
    """Offline transport for tests and local dry runs."""

    def __init__(self, scripted_replies: list[str] | None = None) -> None:
        self.scripted_replies = list(scripted_replies or [])
        self.sent_messages: list[str] = []
        self._message_seq = 0
        self._reply_index = 0
        self._prompt_id: str | None = None

    def send_message(self, channel_id: str, content: str, token: str) -> dict[str, Any]:
        self._message_seq += 1
        self._prompt_id = str(1_000_000_000_000_000_000 + self._message_seq)
        self.sent_messages.append(content)
        return {"id": self._prompt_id, "channel_id": channel_id, "content": content}

    def list_messages(
        self,
        channel_id: str,
        token: str,
        after: str | None,
    ) -> list[dict[str, Any]]:
        if after is None or after != self._prompt_id:
            return []
        if self._reply_index >= len(self.scripted_replies):
            return []
        reply = self.scripted_replies[self._reply_index]
        self._reply_index += 1
        msg_id = str(int(self._prompt_id) + 1)
        return [
            {
                "id": msg_id,
                "content": reply,
                "author": {"id": "user-1", "bot": False},
            }
        ]


def build_discord_transport() -> DiscordTransport:
    mode = os.getenv("LUNCH_AGENT_DISCORD_MODE", "fake").lower()
    if mode == "live":
        return HttpDiscordTransport()
    return FakeDiscordTransport()


def _message_id(value: str) -> int:
    return int(value)


def notify_discord(text: str, transport: DiscordTransport | None = None) -> None:
    """Post a follow-up message to the configured Discord channel."""
    load_project_env()
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
    if not token or not channel_id:
        return
    transport = transport or build_discord_transport()
    transport.send_message(channel_id, text, token)


def wait_for_discord_response(
    item_name: str,
    restaurant: str,
    price_usd: float,
    prefs: dict[str, Any],
    *,
    verbose: bool = False,
    user_output: bool = False,
    transport: DiscordTransport | None = None,
    poll_interval_sec: float = 2.0,
    yelp_url: str = "",
    place_url: str = "",
    discovery_report: str = "",
    recommendation_details: list[str] | None = None,
) -> str:
    """Send lunch prompt to Discord and wait for user reply."""
    load_project_env()
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv("DISCORD_CHANNEL_ID", "")
    if not token or not channel_id:
        raise RuntimeError(
            "Discord confirmation requires DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID. "
            f"Check {Path(__file__).resolve().parent.parent / '.env'}"
        )

    transport = transport or build_discord_transport()
    lead = int(prefs["confirmation"]["lead_time_min"])
    reminder_min = int(prefs["confirmation"]["reminder_interval_min"])
    auto = bool(prefs["confirmation"]["auto_order_on_no_response"])

    body = format_lunch_message(
        item_name,
        restaurant,
        price_usd,
        lead,
        yelp_url=yelp_url,
        place_url=place_url,
        recommendation_details=recommendation_details,
        discovery_preamble=discovery_report,
    )
    if user_output:
        print(body)
        if verbose:
            print("\n(sent to Discord)")

    sent = transport.send_message(channel_id, body, token)
    prompt_id = str(sent["id"])

    if verbose:
        print(f"DISCORD: prompt sent (message_id={prompt_id})")
        print("DISCORD: waiting for your reply (1, 2, or 3)...")

    warned_empty_content = False
    prompt_snow = _message_id(prompt_id)

    def poll_once() -> str | None:
        nonlocal warned_empty_content
        messages = transport.list_messages(channel_id, token, prompt_id)
        for message in messages:
            try:
                msg_id = _message_id(str(message["id"]))
            except (KeyError, TypeError, ValueError):
                continue
            if msg_id <= prompt_snow:
                continue
            author = message.get("author") or {}
            if author.get("bot"):
                continue
            content = str(message.get("content", ""))
            if not content.strip():
                if not warned_empty_content and (verbose or user_output):
                    print(
                        "DISCORD: saw your message but content is empty. "
                        "Enable Message Content Intent: Developer Portal -> Bot -> Privileged Gateway Intents."
                    )
                    warned_empty_content = True
                continue
            action = parse_user_action(content)
            if action:
                if verbose or user_output:
                    print(f"DISCORD: got reply '{content.strip()}' -> {action}")
                return action
        return None

    # First wait window (reminder_min). Fake transport returns on first poll.
    deadline = time.time() + reminder_min * 60
    while time.time() < deadline:
        action = poll_once()
        if action:
            return action
        if isinstance(transport, FakeDiscordTransport):
            break
        time.sleep(poll_interval_sec)

    # Reminder
    reminder_text = (
        f"Reminder: reply 1 (order), 2 (another), or 3 (skip) for {item_name}."
    )
    transport.send_message(channel_id, reminder_text, token)
    if user_output:
        print(f"\nNo reply yet. Reminder sent on Discord.")

    if not auto:
        return "not_today"

    # Second wait window (same length), then auto-order on silence.
    deadline = time.time() + reminder_min * 60
    while time.time() < deadline:
        action = poll_once()
        if action:
            return action
        if isinstance(transport, FakeDiscordTransport):
            break
        time.sleep(poll_interval_sec)

    if user_output:
        print(f"\nNo reply after {reminder_min} minutes. Placing order automatically.")
    if verbose:
        print("DISCORD: no response, auto-ordering")
    return "order_it"
