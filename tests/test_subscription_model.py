"""Tests for raid-target subscription CRUD."""

from __future__ import annotations

from roboToald.db.models import subscription as sub_model
from roboToald.discord_client.commands import cmd_raidtarget


def _make_sub(**overrides):
    defaults = {
        "user_id": 1,
        "target": "Scout Charisa",
        "guild_id": 99,
        "lead_time": 1800,
    }
    defaults.update(overrides)
    return sub_model.Subscription(**defaults)


def test_store_and_fetch_subscription(subscription_session):
    sub = _make_sub()
    sub.store()

    fetched = sub_model.get_subscription(user_id=1, target="Scout Charisa", guild_id=99)
    assert fetched is not None
    assert fetched.target == "Scout Charisa"
    assert fetched.lead_time == 1800


def test_get_subscriptions_for_user_orders_by_target(subscription_session):
    _make_sub(target="Zebuxoruk").store()
    _make_sub(target="Alpha").store()

    subs = sub_model.get_subscriptions_for_user(user_id=1, guild_id=99)
    assert [s.target for s in subs] == ["Alpha", "Zebuxoruk"]


def test_delete_missing_returns_false(subscription_session):
    assert sub_model.delete_subscription(user_id=1, target="Missing", guild_id=99) is False


def test_mark_sent_missing_returns_false(subscription_session):
    assert sub_model.mark_subscription_sent(user_id=1, target="Missing", guild_id=99, start_time=123) is False


def test_mark_sent_updates_fields(subscription_session):
    sub = _make_sub()
    sub.store()

    assert sub_model.mark_subscription_sent(user_id=1, target="Scout Charisa", guild_id=99, start_time=999)
    updated = sub_model.get_subscription(user_id=1, target="Scout Charisa", guild_id=99)
    assert updated.last_window_start == 999
    assert updated.last_notified > 0


def test_subscription_dm_buttons_unsubscribe_only():
    buttons = cmd_raidtarget._subscription_dm_buttons("Scout Charisa", 99)
    assert len(buttons) == 1
    assert buttons[0].label == "Unsubscribe"
    assert buttons[0].custom_id == "unsubscribe:Scout Charisa:99"
