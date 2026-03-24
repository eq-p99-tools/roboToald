"""Tests for the EQ log player parser. Port of Ruby player_parser_spec.rb.

These tests use an in-memory DB fixture to create known Characters,
matching the Ruby spec's setup.
"""

from roboToald.db.raid_models.character import Character
from roboToald.raid import player_parser


FAKE_GUILD_ID = 12345


def _parse(content: str, session, known_chars=None):
    """Helper that patches the session used by parse_players_from_content."""
    for char_name in (known_chars or []):
        session.add(Character(name=char_name))
    session.flush()

    import roboToald.raid.player_parser as pp
    orig_get = pp.get_raid_session

    import contextlib

    @contextlib.contextmanager
    def fake_session(guild_id):
        yield session

    pp.get_raid_session = fake_session
    try:
        players, anon = pp.parse_players_from_content(content, FAKE_GUILD_ID)
    finally:
        pp.get_raid_session = orig_get
    return players, anon


def test_parse_guild_member(raid_session):
    content = (
        "[Wed Aug 31 13:25:51 2022] [20 Ranger] Stede (Wood Elf)\n"
        "[Wed Aug 31 13:25:51 2022] [ANONYMOUS] Portlia <Good Guys>\n"
    )
    players, anon = _parse(content, raid_session, known_chars=["Portlia"])
    assert sorted(p.name for p in players) == ["Portlia"]
    assert anon == []


def test_unknown_anon_goes_to_anon_list(raid_session):
    content = (
        "[Wed Aug 31 13:25:51 2022] [20 Ranger] Stede (Wood Elf)\n"
        "[Wed Aug 31 13:25:51 2022] [ANONYMOUS] Portlia <Good Guys>\n"
    )
    players, anon = _parse(content, raid_session)
    assert sorted(p.name for p in players) == []
    assert sorted(p.name for p in anon) == ["Portlia"]


def test_parse_leveled_guild_member(raid_session):
    content = (
        "[Wed Aug 31 10:37:51 2022] [52 Wanderer] Portlia (Wood Elf) <Good Guys>\n"
    )
    players, anon = _parse(content, raid_session)
    assert sorted(p.name for p in players) == ["Portlia"]
    assert players[0].klass == "Wanderer"


def test_linkdead_member(raid_session):
    content = (
        "[Tue Aug 30 20:42:01 2022]  <LINKDEAD>[60 Assassin] Hamza (Dark Elf) <Good Guys>\n"
        "[Wed Aug 31 13:14:45 2022] [ANONYMOUS] Portlia  <Good Guys>\n"
    )
    players, anon = _parse(content, raid_session)
    names = sorted(p.name for p in players)
    assert names == ["Hamza", "Portlia"]


def test_known_character_anonymous(raid_session):
    content = (
        "[Wed Aug 31 13:14:45 2022] [ANONYMOUS] Portlia\n"
    )
    players, anon = _parse(content, raid_session, known_chars=["Portlia"])
    assert sorted(p.name for p in players) == ["Portlia"]
    assert anon == []


def test_guild_members_only(raid_session):
    content = (
        "[Wed Sep 07 16:13:08 2022] [53 Illusionist] Hungzo (Gnome) <Good Guys>\n"
        "[Wed Sep 07 16:13:08 2022] [60 Virtuoso] Beaon (Gnome) <Good Guys>\n"
        "[Wed Sep 07 16:13:08 2022] [60 Assassin] Amgalad (Barbarian) <Good Guys>\n"
        "[Wed Sep 07 16:13:08 2022] [58 Conjurer] Theiya (High Elf) <Good Guys>\n"
    )
    players, anon = _parse(content, raid_session)
    assert sorted(p.name for p in players) == ["Amgalad", "Beaon", "Hungzo", "Theiya"]
    assert anon == []
