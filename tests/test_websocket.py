"""Tests for ``build_account_tree`` and ``compute_diff`` in ``roboToald.api.websocket``."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

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
    }
    return SimpleNamespace(**defaults)


def _account(real_user, *, aliases=(), tags=(), characters=(), last_login=None, last_login_by=None, id=1):
    return SimpleNamespace(
        id=id,
        real_user=real_user,
        aliases=[SimpleNamespace(alias=a) for a in aliases],
        tags=[SimpleNamespace(tag=t) for t in tags],
        characters=list(characters),
        last_login=last_login,
        last_login_by=last_login_by,
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
                }
            },
            "last_login": ts.astimezone(datetime.timezone.utc).isoformat(),
            "last_login_by": None,
            "active_character": "Raid",
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
