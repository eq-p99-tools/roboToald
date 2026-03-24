"""Tests for the permissions helper."""

from unittest.mock import MagicMock

from roboToald.db.raid_models.permission import Permission


def _make_member(role_names: list[str]) -> MagicMock:
    member = MagicMock()
    roles = []
    for name in role_names:
        role = MagicMock()
        role.name = name
        roles.append(role)
    member.roles = roles
    return member


FAKE_GUILD_ID = 12345


def test_can_with_matching_role(raid_session):
    raid_session.add(Permission(role="officer", server="main", permission="submit"))
    raid_session.flush()

    import roboToald.raid.permissions as pmod
    import contextlib

    @contextlib.contextmanager
    def fake_session(guild_id):
        yield raid_session

    orig = pmod.get_raid_session
    pmod.get_raid_session = fake_session
    try:
        member = _make_member(["Officer", "Member"])
        assert pmod.can(member, "submit", FAKE_GUILD_ID) is True
    finally:
        pmod.get_raid_session = orig


def test_cannot_without_matching_role(raid_session):
    raid_session.add(Permission(role="officer", server="main", permission="submit"))
    raid_session.flush()

    import roboToald.raid.permissions as pmod
    import contextlib

    @contextlib.contextmanager
    def fake_session(guild_id):
        yield raid_session

    orig = pmod.get_raid_session
    pmod.get_raid_session = fake_session
    try:
        member = _make_member(["Member"])
        assert pmod.can(member, "submit", FAKE_GUILD_ID) is False
    finally:
        pmod.get_raid_session = orig


def test_cannot_function(raid_session):
    raid_session.add(Permission(role="officer", server="main", permission="submit"))
    raid_session.flush()

    import roboToald.raid.permissions as pmod
    import contextlib

    @contextlib.contextmanager
    def fake_session(guild_id):
        yield raid_session

    orig = pmod.get_raid_session
    pmod.get_raid_session = fake_session
    try:
        member = _make_member(["Member"])
        assert pmod.cannot(member, "submit", FAKE_GUILD_ID) is True
    finally:
        pmod.get_raid_session = orig
