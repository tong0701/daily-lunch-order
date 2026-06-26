"""Offline tests for Discord confirmation."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent import Candidate, run_agent, run_confirmation
from discord_confirm import (
    FakeDiscordTransport,
    format_lunch_message,
    parse_user_action,
    wait_for_discord_response,
)
from provider import MenuItem, MockProvider


def sample_prefs():
    return {
        "confirmation": {
            "lead_time_min": 5,
            "reminder_interval_min": 10,
            "auto_order_on_no_response": True,
        },
    }


def sample_pick():
    item = MenuItem(
        id="m4",
        name="Chicken Shawarma Plate",
        restaurant="Olive Grove",
        cuisine="mediterranean",
        price_usd=15.00,
    )
    return Candidate(item=item, score=10.0, reasons=[])


class TestParseUserAction:
    def test_order_aliases(self):
        assert parse_user_action("order_it") == "order_it"
        assert parse_user_action("1") == "order_it"

    def test_another_aliases(self):
        assert parse_user_action("show_another") == "show_another"
        assert parse_user_action("2") == "show_another"

    def test_skip_aliases(self):
        assert parse_user_action("not_today") == "not_today"
        assert parse_user_action("3") == "not_today"


class TestLunchMessage:
    def test_compact_recommendation_card(self):
        body = format_lunch_message(
            "Lunch at Hummus Republic",
            "Hummus Republic",
            12.0,
            5,
            recommendation_details=[
                "\U0001f4cd 280 m   \u00b7   \u2b50 4.6 (210)",
                "\U0001f4b5 ~$12/person",
                "\u2728 cuisine you like \u00b7 close by",
                "",
                "\U0001f6d2 **Order on DoorDash:** https://www.doordash.com/search/store/Hummus%20Republic",
            ],
        )

        assert "**Hummus Republic**" in body
        assert "Hey!" in body
        assert "Lunch pick for you" in body
        assert "280 m" in body
        assert "4.6 (210)" in body
        assert "Order on DoorDash:" in body
        assert "1\ufe0f\u20e3 order" in body
        assert "price_source" not in body
        assert body.count("doordash.com") == 1


class TestDiscordWait:
    def test_wait_returns_parsed_action(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "channel-1")
        transport = FakeDiscordTransport(scripted_replies=["show_another"])
        action = wait_for_discord_response(
            "Chicken Shawarma Plate",
            "Olive Grove",
            15.0,
            sample_prefs(),
            transport=transport,
        )
        assert action == "show_another"
        assert len([m for m in transport.sent_messages if "**Olive Grove**" in m]) == 1

    def test_discovery_merged_into_single_discord_message(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "channel-1")
        transport = FakeDiscordTransport(scripted_replies=["order_it"])
        wait_for_discord_response(
            "Chicken Shawarma Plate",
            "Olive Grove",
            15.0,
            sample_prefs(),
            transport=transport,
            discovery_report="Discovery complete",
        )
        assert len(transport.sent_messages) >= 1
        prompt = transport.sent_messages[0]
        assert "Discovery complete" in prompt
        assert "**Olive Grove**" in prompt
        assert prompt.count("**Olive Grove**") == 1

    def test_no_reply_auto_orders_when_enabled(self, monkeypatch):
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "channel-1")
        transport = FakeDiscordTransport(scripted_replies=[])
        action = wait_for_discord_response(
            "Chicken Shawarma Plate",
            "Olive Grove",
            15.0,
            sample_prefs(),
            transport=transport,
        )
        assert action == "order_it"


class TestAgentDiscordIntegration:
    def test_run_confirmation_discord_backend(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_CONFIRMATION", "discord")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "channel-1")
        monkeypatch.setenv("LUNCH_AGENT_DISCORD_MODE", "fake")

        import discord_confirm

        fake = FakeDiscordTransport(scripted_replies=["order_it"])
        monkeypatch.setattr(discord_confirm, "build_discord_transport", lambda: fake)

        action = run_confirmation(
            sample_pick(),
            sample_prefs(),
            verbose=False,
            user_output=False,
            simulated_response=None,
        )
        assert action == "order_it"

    def test_full_agent_run_with_discord_fake(self, monkeypatch):
        monkeypatch.setenv("LUNCH_AGENT_CONFIRMATION", "discord")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
        monkeypatch.setenv("DISCORD_CHANNEL_ID", "channel-1")
        monkeypatch.setenv("LUNCH_AGENT_DISCORD_MODE", "fake")

        import discord_confirm

        fake = FakeDiscordTransport(scripted_replies=["order_it"])
        monkeypatch.setattr(discord_confirm, "build_discord_transport", lambda: fake)

        prefs = {
            "schedule": {
                "order_times": ["12:00"],
                "timezone": "America/New_York",
                "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                "paused": False,
                "pause_until": None,
            },
            "ordering_platform": "mock",
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
        state = {"days": {}, "ratings": {}, "do_not_show_again": []}
        when = datetime(2026, 6, 22, 11, 55, 0, tzinfo=ZoneInfo("America/New_York"))

        outcome = run_agent(
            provider=MockProvider(),
            prefs=prefs,
            state=state,
            when=when,
            simulated_response=None,
            skip_schedule_check=True,
        )
        assert outcome.status == "ordered"
        assert fake.sent_messages
