"""Tests for ``build_account_tree`` and ``compute_diff`` in ``roboToald.api.websocket``."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from roboToald.db.models import sso as sso_model
from roboToald.db.models.sso import CharacterClass
from roboToald.api.websocket import build_account_tree, compute_diff


def _char(name, klass=None, **kwargs):
    defaults = {
        "name": name,
        "klass": klass,
        "bind_location": kwargs.get("bind_location"),
        "park_location": kwargs.get("park_location"),
        "level": kwargs.get("level"),
        "key_seb": kwargs.get("key_seb"),
        "key_vp": kwargs.get("key_vp"),
        "key_st": kwargs.get("key_st"),
        "item_void": kwargs.get("item_void"),
        "item_neck": kwargs.get("item_neck"),
        "item_lizard": kwargs.get("item_lizard"),
        "item_thurg": kwargs.get("item_thurg"),
        "item_reaper": kwargs.get("item_reaper"),
        "item_brass_idol": kwargs.get("item_brass_idol"),
        "item_pearl": kwargs.get("item_pearl"),
        "item_peridot": kwargs.get("item_peridot"),
        "item_mb3": kwargs.get("item_mb3"),
        "item_mb4": kwargs.get("item_mb4"),
        "item_mb5": kwargs.get("item_mb5"),
        "notes": kwargs.get("notes"),
    }
    return SimpleNamespace(**defaults)


def _account(
    real_user,
    *,
    aliases=(),
    tags=(),
    characters=(),
    last_login=None,
    last_login_by=None,
    id=1,
    owner_discord_user_id=None,
    shares=(),
    groups=(),
    notes=None,
):
    return SimpleNamespace(
        id=id,
        real_user=real_user,
        aliases=[SimpleNamespace(alias=a) for a in aliases],
        tags=[SimpleNamespace(tag=t) for t in tags],
        characters=list(characters),
        last_login=last_login,
        last_login_by=last_login_by,
        owner_discord_user_id=owner_discord_user_id,
        shares=[SimpleNamespace(shared_with_discord_user_id=uid) for uid in shares],
        groups=[SimpleNamespace(role_id=rid) for rid in groups],
        notes=notes,
    )


def test_merge_keys_and_items_message():
    assert sso_model.merge_keys_and_items_message({}) == {}
    assert sso_model.merge_keys_and_items_message({"keys": {"seb": False}, "items": {"seb": True}}) == {
        "seb": True,
    }
    assert sso_model.merge_keys_and_items_message({"keys": {"vp": True}, "items": {}}) == {"vp": True}


def test_merged_wires_coerces_bool_to_int_for_stack_items():
    kw = sso_model.merged_wires_to_character_kwargs({"lizard": True, "pearl": False})
    assert kw["item_lizard"] == 1
    assert kw["item_pearl"] == 0


def test_build_account_tree_shape():
    ts = datetime.datetime(2024, 1, 15, 8, 30, 0, tzinfo=datetime.timezone.utc)
    acc = _account(
        "main",
        aliases=["m"],
        tags=["t1"],
        characters=[_char("Raid", CharacterClass.Warrior, bind_location="Norrath", level=60)],
        last_login=ts,
        id=42,
    )
    tree = build_account_tree([acc], active_characters={42: "Raid"})
    assert tree == {
        "main": {
            "aliases": ["m"],
            "tags": ["t1"],
            "characters": {
                "Raid": {
                    "class": "Warrior",
                    "bind": "Norrath",
                    "park": None,
                    "level": 60,
                    "items": {
                        "seb": None,
                        "vp": None,
                        "st": None,
                        "void": None,
                        "neck": None,
                        "lizard": None,
                        "thurg": None,
                        "reaper": None,
                        "brass_idol": None,
                        "pearl": None,
                        "peridot": None,
                        "mb3": None,
                        "mb4": None,
                        "mb5": None,
                    },
                    "keys": {"seb": None, "vp": None, "st": None},
                    "notes": None,
                }
            },
            "last_login": ts.astimezone(datetime.timezone.utc).isoformat(),
            "last_login_by": None,
            "active_character": "Raid",
            "owned": False,
            "shared": False,
            "group_roles": [],
            "notes": None,
        }
    }


def test_build_account_tree_last_login_suppressed_when_year_le_one():
    acc = _account("old", last_login=datetime.datetime(1, 1, 1))
    tree = build_account_tree([acc])
    assert tree["old"]["last_login"] is None


def test_compute_diff_add_remove_account():
    old = {}
    new = {
        "a": {
            "aliases": [],
            "tags": [],
            "characters": {},
            "last_login": None,
            "last_login_by": None,
            "active_character": None,
            "owned": False,
            "shared": False,
            "group_roles": [],
        }
    }
    ch = compute_diff(old, new)
    assert ch == [
        {
            "action": "add",
            "entity": "account",
            "account": "a",
            "data": new["a"],
        }
    ]
    ch2 = compute_diff(new, old)
    assert ch2 == [{"action": "remove", "entity": "account", "account": "a"}]


def test_compute_diff_alias_tag_changes():
    base = {
        "aliases": ["x"],
        "tags": ["t"],
        "characters": {},
        "last_login": None,
        "last_login_by": None,
        "active_character": None,
    }
    old_t = {"u": dict(base)}
    new_t = {"u": {**base, "aliases": ["x", "y"], "tags": []}}
    ch = compute_diff(old_t, new_t)
    assert len(ch) == 1
    assert ch[0]["action"] == "update"
    assert ch[0]["fields"]["aliases"] == {"add": ["y"], "remove": []}
    assert ch[0]["fields"]["tags"] == {"add": [], "remove": ["t"]}


def test_compute_diff_character_add_remove_update():
    char_blob = {
        "class": "Warrior",
        "bind": None,
        "park": None,
        "level": 1,
        "items": {
            "seb": None,
            "vp": None,
            "st": None,
            "void": None,
            "neck": None,
            "lizard": None,
            "thurg": None,
            "reaper": None,
            "brass_idol": None,
            "pearl": None,
            "peridot": None,
            "mb3": None,
            "mb4": None,
            "mb5": None,
        },
        "keys": {"seb": None, "vp": None, "st": None},
    }
    old_t = {
        "u": {
            "aliases": [],
            "tags": [],
            "characters": {"A": dict(char_blob)},
            "last_login": None,
            "last_login_by": None,
            "active_character": None,
        }
    }
    new_blob = dict(char_blob)
    new_blob["level"] = 2
    new_t = {
        "u": {
            "aliases": [],
            "tags": [],
            "characters": {"A": new_blob, "B": dict(char_blob)},
            "last_login": None,
            "last_login_by": None,
            "active_character": None,
        }
    }
    ch = compute_diff(old_t, new_t)[0]
    fc = ch["fields"]["characters"]
    assert "B" in fc["add"]
    assert fc["update"]["A"]["level"] == 2


def test_compute_diff_no_change_empty():
    t = {"u": {"a": 1}}
    assert compute_diff(t, t) == []


def test_compute_diff_scalar_fields():
    old_t = {
        "u": {
            "aliases": [],
            "tags": [],
            "characters": {},
            "last_login": "a",
            "last_login_by": None,
            "active_character": None,
        }
    }
    new_t = {
        "u": {
            "aliases": [],
            "tags": [],
            "characters": {},
            "last_login": "b",
            "last_login_by": "bob",
            "active_character": "Z",
        }
    }
    ch = compute_diff(old_t, new_t)[0]["fields"]
    assert ch["last_login"] == "b"
    assert ch["last_login_by"] == "bob"
    assert ch["active_character"] == "Z"


def test_build_account_tree_group_roles_sorted_deduped():
    acc = _account("main", groups=[100, 200, 100])
    role_map = {100: "Member", 200: "Officer"}
    tree = build_account_tree([acc], role_names_by_id=role_map)
    assert tree["main"]["group_roles"] == ["Member", "Officer"]


def test_build_account_tree_group_roles_omits_unresolved_ids():
    acc = _account("main", groups=[100, 999])
    tree = build_account_tree([acc], role_names_by_id={100: "Member"})
    assert tree["main"]["group_roles"] == ["Member"]


def test_build_account_tree_group_roles_empty_without_groups():
    acc = _account("main")
    tree = build_account_tree([acc], role_names_by_id={100: "Member"})
    assert tree["main"]["group_roles"] == []


def test_compute_diff_group_roles_changes():
    base = {
        "aliases": [],
        "tags": [],
        "characters": {},
        "last_login": None,
        "last_login_by": None,
        "active_character": None,
        "group_roles": ["Member"],
    }
    old_t = {"u": dict(base)}
    new_t = {"u": {**base, "group_roles": ["Member", "Officer"]}}
    ch = compute_diff(old_t, new_t)
    assert len(ch) == 1
    assert ch[0]["fields"]["group_roles"] == {"add": ["Officer"], "remove": []}


def test_build_account_tree_includes_account_and_character_notes():
    acc = _account(
        "main",
        notes="Shared with raid",
        characters=[_char("Raid", CharacterClass.Warrior, notes="Kael factioned"), _char("Alt", CharacterClass.Cleric)],
    )
    tree = build_account_tree([acc])
    assert tree["main"]["notes"] == "Shared with raid"
    assert tree["main"]["characters"]["Raid"]["notes"] == "Kael factioned"
    assert tree["main"]["characters"]["Alt"]["notes"] is None


def test_compute_diff_account_notes_scalar_set_and_clear():
    acc = _account("main")
    old_t = build_account_tree([acc])
    new_t = build_account_tree([_account("main", notes="Kael factioned")])
    ch = compute_diff(old_t, new_t)
    assert ch == [{"action": "update", "entity": "account", "account": "main", "fields": {"notes": "Kael factioned"}}]
    cleared = compute_diff(new_t, old_t)
    assert cleared[0]["fields"] == {"notes": None}


def test_compute_diff_character_notes_ride_in_character_update():
    old_t = build_account_tree([_account("main", characters=[_char("Raid", CharacterClass.Warrior)])])
    new_t = build_account_tree(
        [_account("main", characters=[_char("Raid", CharacterClass.Warrior, notes="Kael factioned")])]
    )
    fields = compute_diff(old_t, new_t)[0]["fields"]
    assert set(fields) == {"characters"}
    assert fields["characters"]["update"]["Raid"]["notes"] == "Kael factioned"


def test_login_notes_for_account():
    assert sso_model.login_notes_for_account(_account("main", characters=[_char("Raid")])) is None
    acc = _account("main", notes="Acct note", characters=[_char("Raid", notes="Char note"), _char("Alt")])
    assert sso_model.login_notes_for_account(acc) == {"account": "Acct note", "characters": {"Raid": "Char note"}}
    only_char = _account("main", characters=[_char("Raid", notes="Char note")])
    assert sso_model.login_notes_for_account(only_char) == {"account": None, "characters": {"Raid": "Char note"}}


def test_normalize_notes():
    assert sso_model.normalize_notes(None) is None
    assert sso_model.normalize_notes("   ") is None
    assert sso_model.normalize_notes("  hi  ") == "hi"
    assert sso_model.normalize_notes("x" * sso_model.NOTES_MAX_LENGTH) == "x" * sso_model.NOTES_MAX_LENGTH
    with pytest.raises(ValueError):
        sso_model.normalize_notes("x" * (sso_model.NOTES_MAX_LENGTH + 1))
