"""Tests for bot ownership (Phase 1).

Covers:
  * ``SSOAccount.owner_discord_user_id`` column and ``create_account`` wiring.
  * Helpers ``can_manage_account``, ``set_account_owner``, ``get_accounts_owned_by``.
  * ``user_has_access_to_accounts`` grants login access to owners without matching roles.
  * ``build_account_tree`` emits an ``owned`` flag for the viewing user.
  * ``ConnectionManager._filter_accessible`` includes owned accounts.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from roboToald.api import server as api_server
from roboToald.api.websocket import ConnectionManager, build_account_tree
from roboToald.db.models import sso as sso_model


GUILD_ID = 4242
OWNER_ID = 555
OTHER_ID = 777


def test_create_account_defaults_to_no_owner(sso_session):
    sso_model.create_account(GUILD_ID, "LegacyBot", "pw")
    acc = sso_model.get_account(GUILD_ID, "legacybot")
    assert acc.owner_discord_user_id is None


def test_create_account_records_owner(sso_session):
    sso_model.create_account(GUILD_ID, "OwnerBot", "pw", owner_discord_user_id=OWNER_ID)
    acc = sso_model.get_account(GUILD_ID, "ownerbot")
    assert acc.owner_discord_user_id == OWNER_ID


def test_can_manage_account_owner_only():
    acc = SimpleNamespace(owner_discord_user_id=OWNER_ID)
    assert sso_model.can_manage_account(acc, OWNER_ID, is_admin=False) is True
    assert sso_model.can_manage_account(acc, OTHER_ID, is_admin=False) is False


def test_can_manage_account_admin_override_even_when_not_owner():
    acc = SimpleNamespace(owner_discord_user_id=OWNER_ID)
    assert sso_model.can_manage_account(acc, OTHER_ID, is_admin=True) is True


def test_can_manage_account_unowned_admin_only():
    acc = SimpleNamespace(owner_discord_user_id=None)
    assert sso_model.can_manage_account(acc, OWNER_ID, is_admin=False) is False
    assert sso_model.can_manage_account(acc, OWNER_ID, is_admin=True) is True


def test_set_account_owner_assign_and_clear(sso_session):
    sso_model.create_account(GUILD_ID, "MyBot", "pw")
    sso_model.set_account_owner(GUILD_ID, "mybot", OWNER_ID)
    assert sso_model.get_account(GUILD_ID, "mybot").owner_discord_user_id == OWNER_ID
    # Clearing ownership returns it to admin-only (NULL).
    sso_model.set_account_owner(GUILD_ID, "mybot", None)
    assert sso_model.get_account(GUILD_ID, "mybot").owner_discord_user_id is None


def test_set_account_owner_raises_when_missing(sso_session):
    import pytest

    with pytest.raises(sso_model.SSOAccountNotFoundError):
        sso_model.set_account_owner(GUILD_ID, "nope", OWNER_ID)


def test_get_accounts_owned_by(sso_session):
    sso_model.create_account(GUILD_ID, "mine1", "pw", owner_discord_user_id=OWNER_ID)
    sso_model.create_account(GUILD_ID, "mine2", "pw", owner_discord_user_id=OWNER_ID)
    sso_model.create_account(GUILD_ID, "theirs", "pw", owner_discord_user_id=OTHER_ID)
    sso_model.create_account(GUILD_ID, "legacy", "pw")

    owned = sso_model.get_accounts_owned_by(GUILD_ID, OWNER_ID)
    assert sorted(a.real_user for a in owned) == ["mine1", "mine2"]
    assert sso_model.get_accounts_owned_by(GUILD_ID, 999) == []


def test_user_has_access_to_accounts_owner_without_role(sso_session):
    """An owner with zero matching group roles still sees their own account."""
    sso_model.create_account(GUILD_ID, "owned", "pw", owner_discord_user_id=OWNER_ID)
    owned = sso_model.get_account(GUILD_ID, "owned")

    bot = MagicMock()
    # _get_user_role_ids() calls bot.get_guild(...).get_member(...); return a member with no roles.
    member = MagicMock()
    member.roles = []
    guild = MagicMock()
    guild.get_member.return_value = member
    bot.get_guild.return_value = guild

    result = api_server.user_has_access_to_accounts(bot, OWNER_ID, GUILD_ID, [owned.id])
    assert [a.id for a in result] == [owned.id]


def test_user_has_access_to_accounts_non_owner_no_role_denied(sso_session):
    sso_model.create_account(GUILD_ID, "owned2", "pw", owner_discord_user_id=OWNER_ID)
    owned = sso_model.get_account(GUILD_ID, "owned2")

    bot = MagicMock()
    member = MagicMock()
    member.roles = []
    guild = MagicMock()
    guild.get_member.return_value = member
    bot.get_guild.return_value = guild

    result = api_server.user_has_access_to_accounts(bot, OTHER_ID, GUILD_ID, [owned.id])
    assert result == []


def test_build_account_tree_owned_flag():
    acc_owned = SimpleNamespace(
        id=1,
        real_user="mine",
        aliases=[],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
        owner_discord_user_id=OWNER_ID,
    )
    acc_other = SimpleNamespace(
        id=2,
        real_user="shared",
        aliases=[],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
        owner_discord_user_id=OTHER_ID,
    )
    tree = build_account_tree([acc_owned, acc_other], viewer_discord_user_id=OWNER_ID)
    assert tree["mine"]["owned"] is True
    assert tree["shared"]["owned"] is False


def test_build_account_tree_owned_false_when_no_viewer():
    acc = SimpleNamespace(
        id=1,
        real_user="mine",
        aliases=[],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
        owner_discord_user_id=OWNER_ID,
    )
    tree = build_account_tree([acc])
    assert tree["mine"]["owned"] is False


def _bot_with_member_roles(role_ids: list[int]):
    """Build a ``bot`` mock whose ``get_guild().get_member()`` returns a member with the given role ids."""
    bot = MagicMock()
    member = MagicMock()
    member.roles = [SimpleNamespace(id=rid) for rid in role_ids]
    guild = MagicMock()
    guild.get_member.return_value = member
    bot.get_guild.return_value = guild
    return bot


def test_filter_accessible_includes_owner_without_group(monkeypatch):
    mgr = ConnectionManager()
    mgr.set_discord_client(_bot_with_member_roles([]))

    accounts = [
        SimpleNamespace(id=1, real_user="own", groups=[], owner_discord_user_id=OWNER_ID),
        SimpleNamespace(id=2, real_user="other", groups=[], owner_discord_user_id=OTHER_ID),
    ]
    filtered = mgr._filter_accessible(OWNER_ID, GUILD_ID, accounts)
    assert [a.id for a in filtered] == [1]


def test_filter_accessible_role_access_still_works(monkeypatch):
    mgr = ConnectionManager()
    mgr.set_discord_client(_bot_with_member_roles([999]))

    accounts = [
        SimpleNamespace(
            id=1,
            real_user="group_visible",
            groups=[SimpleNamespace(role_id=999)],
            owner_discord_user_id=None,
        ),
        SimpleNamespace(
            id=2,
            real_user="hidden",
            groups=[SimpleNamespace(role_id=888)],
            owner_discord_user_id=None,
        ),
    ]
    filtered = mgr._filter_accessible(OWNER_ID, GUILD_ID, accounts)
    assert [a.id for a in filtered] == [1]
