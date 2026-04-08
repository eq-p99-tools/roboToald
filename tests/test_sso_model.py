"""Tests for ``roboToald.db.models.sso`` — helpers, resolution, revocations, rate limits, access keys."""

from __future__ import annotations

import datetime

import pytest
from freezegun import freeze_time

from roboToald import config
from roboToald.db.models import sso as sso


GUILD_ID = 424242


@pytest.mark.parametrize(
    ("ip", "length"),
    [
        ("192.0.2.1", 14),
        ("::1", 8),
    ],
)
def test_hash_ip_deterministic(ip, length):
    h1 = sso.hash_ip(ip, length=length)
    h2 = sso.hash_ip(ip, length=length)
    assert h1 == h2
    assert len(h1) == length
    # URL-safe base64 alphabet
    assert all(c.isalnum() or c in "-_" for c in h1)


def test_max_character_level_empty():
    acc = type("A", (), {"characters": []})()
    assert sso._max_character_level(acc) == 0


def test_max_character_level_mixed():
    class C:
        def __init__(self, level):
            self.level = level

    acc = type("A", (), {"characters": [C(5), C(None), C(60)]})()
    assert sso._max_character_level(acc) == 60


def test_login_sort_key_buckets_and_level():
    now = datetime.datetime(2020, 1, 1, 12, 0, 0)
    # age 0 -> bucket 0
    a = type("A", (), {"last_login": now, "characters": []})()
    k0 = sso._login_sort_key(a, now, lambda _: 10)
    # age 35s -> bucket 1
    a2 = type("A", (), {"last_login": now - datetime.timedelta(seconds=35), "characters": []})()
    k1 = sso._login_sort_key(a2, now, lambda _: 10)
    assert k0[0] > k1[0]  # -0 > -1 → first tuple sorts after second (older preferred)
    # higher level wins within same bucket
    a3 = type("A", (), {"last_login": now - datetime.timedelta(seconds=35), "characters": []})()
    k_hi = sso._login_sort_key(a3, now, lambda _: 50)
    k_lo = sso._login_sort_key(a2, now, lambda _: 10)
    assert k_hi < k_lo  # more negative second element = higher level


def test_get_dynamic_tags_structure():
    zones, classes = sso.get_dynamic_tags()
    assert "vp" in zones
    assert "veeshan" in zones["vp"]
    assert classes["clr"] == sso.CharacterClass.Cleric


def test_get_dynamic_tag_list_contains_vpclr():
    assert "vpclr" in sso.get_dynamic_tag_list()


def test_find_account_by_real_user(sso_session):
    sso.create_account(GUILD_ID, "BotOne", "secret1")
    found = sso.find_account_by_username("botone", guild_id=GUILD_ID)
    assert found is not None
    assert found.real_user == "botone"


def test_find_account_by_character(sso_session):
    sso.create_account(GUILD_ID, "acc", "pw")
    acc = sso.get_account(GUILD_ID, "acc")
    sso.add_account_character(GUILD_ID, "acc", "Raidmain", sso.CharacterClass.Warrior)
    found = sso.find_account_by_username("raidmain", guild_id=GUILD_ID)
    assert found is not None
    assert found.id == acc.id


def test_find_account_by_alias(sso_session):
    sso.create_account(GUILD_ID, "acc", "pw")
    sso.create_account_alias(GUILD_ID, "acc", "bob")
    found = sso.find_account_by_username("bob", guild_id=GUILD_ID)
    assert found is not None
    assert found.real_user == "acc"


def test_find_account_by_static_tag_picks_most_stale_in_bucket(sso_session, monkeypatch):
    """Within the <20m window, higher ``age//30`` bucket (more stale) wins; tie-break is level."""
    monkeypatch.setattr(config, "SSO_INACTIVITY_SECONDS", 62)
    sso.create_account(GUILD_ID, "first", "p1")
    sso.create_account(GUILD_ID, "second", "p2")
    a1 = sso.get_account(GUILD_ID, "first")
    a2 = sso.get_account(GUILD_ID, "second")
    now = datetime.datetime(2021, 6, 1, 12, 0, 0)
    # 60s vs 120s ago → buckets 2 and 4 → "second" is more stale
    sso_session.query(sso.SSOAccount).filter(sso.SSOAccount.id == a1.id).update(
        {"last_login": now - datetime.timedelta(seconds=60)}
    )
    sso_session.query(sso.SSOAccount).filter(sso.SSOAccount.id == a2.id).update(
        {"last_login": now - datetime.timedelta(seconds=120)}
    )
    sso_session.commit()
    sso.tag_account(GUILD_ID, "first", "sharedtag")
    sso.tag_account(GUILD_ID, "second", "sharedtag")
    with freeze_time(now):
        found = sso.find_account_by_username("sharedtag", guild_id=GUILD_ID, inactive_only=True)
    assert found.real_user == "second"


def test_find_account_dynamic_tag_vpclr(sso_session, monkeypatch):
    monkeypatch.setattr(config, "SSO_INACTIVITY_SECONDS", 62)
    monkeypatch.setattr(config, "REQUIRE_KEYS_FOR_DYNAMIC_TAGS", False)
    sso.create_account(GUILD_ID, "dynacc", "pw")
    sso_session.query(sso.SSOAccount).filter(sso.SSOAccount.real_user == "dynacc").update(
        {"last_login": datetime.datetime(1999, 1, 1)}
    )
    sso_session.commit()
    sso.add_account_character(GUILD_ID, "dynacc", "Healer", sso.CharacterClass.Cleric)
    sso_session.query(sso.SSOAccountCharacter).filter(sso.SSOAccountCharacter.name == "Healer").update(
        {"park_location": "veeshan"}
    )
    sso_session.commit()
    found = sso.find_account_by_username("vpclr", guild_id=GUILD_ID, inactive_only=True)
    assert found is not None
    assert found.real_user == "dynacc"


def test_tag_temporarily_empty_raises(sso_session, monkeypatch):
    monkeypatch.setattr(config, "SSO_INACTIVITY_SECONDS", 62)
    sso.create_account(GUILD_ID, "only", "pw")
    sso_session.query(sso.SSOAccount).update({"last_login": datetime.datetime.now()})
    sso_session.commit()
    sso.tag_account(GUILD_ID, "only", "busy")
    with pytest.raises(sso.SSOTagTemporarilyEmptyError):
        sso.find_account_by_username("busy", guild_id=GUILD_ID, inactive_only=True)


def test_is_user_access_revoked_permanent(sso_session):
    sso.revoke_user_access(GUILD_ID, 999001, expiry_days=0)
    assert sso.is_user_access_revoked(GUILD_ID, 999001) is True


def test_is_user_access_revoked_expired(sso_session):
    with freeze_time("2020-06-15T12:00:00"):
        sso.revoke_user_access(GUILD_ID, 999002, expiry_days=1)
        assert sso.is_user_access_revoked(GUILD_ID, 999002) is True
    with freeze_time("2020-06-17T12:00:00"):
        assert sso.is_user_access_revoked(GUILD_ID, 999002) is False


def test_revocation_cache_invalidated_on_remove(sso_session):
    sso.revoke_user_access(GUILD_ID, 999003, expiry_days=0)
    assert sso.is_user_access_revoked(GUILD_ID, 999003) is True
    sso.remove_access_revocation(GUILD_ID, 999003)
    assert sso.is_user_access_revoked(GUILD_ID, 999003) is False


def test_count_failed_attempts_and_rate_limit(sso_session, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_MAX_ATTEMPTS", 3)
    ip = "198.51.100.7"
    assert sso.count_failed_attempts(ip) == 0
    assert sso.is_ip_rate_limited(ip, max_attempts=3, minutes=30) is False
    for _ in range(3):
        sso.create_audit_log("u", ip_address=ip, success=False, rate_limit=True)
    assert sso.count_failed_attempts(ip, minutes=30) == 3
    assert sso.is_ip_rate_limited(ip, max_attempts=3, minutes=30) is True


def test_count_failed_attempts_empty_ip():
    assert sso.count_failed_attempts("") == 0
    assert sso.is_ip_rate_limited("", max_attempts=10) is False


def test_failed_attempts_excludes_rate_limit_false(sso_session):
    ip = "198.51.100.8"
    sso.create_audit_log("u", ip_address=ip, success=False, rate_limit=False)
    assert sso.count_failed_attempts(ip) == 0


def test_access_key_cache_invalidation(sso_session, monkeypatch):
    monkeypatch.setattr(sso, "generate_access_key", lambda: "FixedKeyOneTwoThree")
    key1 = sso.get_access_key_by_user(GUILD_ID, 777001)
    plain1 = key1.access_key
    assert sso.get_access_key_by_key(plain1) is not None
    monkeypatch.setattr(sso, "generate_access_key", lambda: "FixedKeyFourFiveSixSeven")
    sso.reset_access_key(GUILD_ID, 777001)
    assert sso.get_access_key_by_key(plain1) is None
    key2 = sso.get_access_key_by_user(GUILD_ID, 777001)
    assert sso.get_access_key_by_key(key2.access_key) is not None


def test_get_audit_logs_excludes_noise_usernames(sso_session):
    sso.create_audit_log("keeper", ip_address="1.1.1.1", success=True, guild_id=GUILD_ID, account_id=None)
    sso.create_audit_log("list_accounts", ip_address="1.1.1.1", success=False, guild_id=GUILD_ID)
    sso.create_audit_log("heartbeat", ip_address="1.1.1.1", success=True, guild_id=GUILD_ID)
    logs = sso.get_audit_logs(limit=20, guild_id=GUILD_ID)
    names = {log.username for log in logs}
    assert "list_accounts" not in names
    assert "heartbeat" not in names
    assert "keeper" in names


def test_clear_rate_limit_clears_failed_attempts(sso_session):
    ip = "198.51.100.99"
    sso.create_audit_log("u", ip_address=ip, success=False, rate_limit=True)
    assert sso.count_failed_attempts(ip) >= 1
    updated = sso.clear_rate_limit(ip)
    assert updated >= 1
    assert sso.count_failed_attempts(ip) == 0


def test_list_accounts_filter_by_group_and_tag(sso_session):
    sso.create_account_group(GUILD_ID, "officers", role_id=9001)
    sso.create_account(GUILD_ID, "alpha", "pw", group="officers")
    sso.create_account(GUILD_ID, "beta", "pw")
    sso.tag_account(GUILD_ID, "beta", "vessel")
    by_group = sso.list_accounts(GUILD_ID, group="officers")
    assert len(by_group) == 1
    assert by_group[0].real_user == "alpha"
    by_tag = sso.list_accounts(GUILD_ID, tag="vessel")
    assert len(by_tag) == 1
    assert by_tag[0].real_user == "beta"


def test_set_character_stack_item_pearl_and_unknown(sso_session):
    sso.create_account(GUILD_ID, "stackuser", "pw")
    sso.add_account_character(GUILD_ID, "stackuser", "Tank", sso.CharacterClass.Warrior)
    assert sso.set_character_stack_item(GUILD_ID, "Tank", "pearl", 12)
    ch = sso_session.query(sso.SSOAccountCharacter).filter_by(name="Tank", guild_id=GUILD_ID).one()
    assert ch.item_pearl == 12
    assert sso.set_character_stack_item(GUILD_ID, "Tank", "pearl", None)
    sso_session.refresh(ch)
    assert ch.item_pearl is None
    assert sso.set_character_stack_item(GUILD_ID, "Tank", "lizard", 0)
    sso_session.refresh(ch)
    assert ch.item_lizard == 0
    assert not sso.set_character_stack_item(GUILD_ID, "Tank", "void", 3)
    assert not sso.set_character_stack_item(GUILD_ID, "Nope", "pearl", 1)


def test_set_character_stack_item_mb4_sets_updated_at(sso_session):
    sso.create_account(GUILD_ID, "mbuser", "pw")
    sso.add_account_character(GUILD_ID, "mbuser", "Clr", sso.CharacterClass.Cleric)
    frozen = datetime.datetime(2024, 6, 1, 12, 0, 0)
    with freeze_time(frozen):
        assert sso.set_character_stack_item(GUILD_ID, "Clr", "mb4", 2)
    ch = sso_session.query(sso.SSOAccountCharacter).filter_by(name="Clr", guild_id=GUILD_ID).one()
    assert ch.item_mb4 == 2
    assert ch.item_mb4_updated_at == frozen


def test_set_character_item_sets_updated_at(sso_session):
    sso.create_account(GUILD_ID, "booluser", "pw")
    sso.add_account_character(GUILD_ID, "booluser", "Dru", sso.CharacterClass.Druid)
    t0 = datetime.datetime(2024, 7, 1, 9, 0, 0)
    with freeze_time(t0):
        assert sso.set_character_item(GUILD_ID, "Dru", "void", True)
    ch = sso_session.query(sso.SSOAccountCharacter).filter_by(name="Dru", guild_id=GUILD_ID).one()
    assert ch.item_void is True
    assert ch.item_void_updated_at == t0


def test_mark_key_from_park_zone_sets_key_updated_at(sso_session):
    sso.create_account(GUILD_ID, "parkuser", "pw")
    sso.add_account_character(GUILD_ID, "parkuser", "Wiz", sso.CharacterClass.Wizard)
    t1 = datetime.datetime(2024, 8, 15, 18, 30, 0)
    with freeze_time(t1):
        assert sso.mark_key_from_park_zone(GUILD_ID, "Wiz", "sebilis")
    ch = sso_session.query(sso.SSOAccountCharacter).filter_by(name="Wiz", guild_id=GUILD_ID).one()
    assert ch.key_seb is True
    assert ch.key_seb_updated_at == t1
