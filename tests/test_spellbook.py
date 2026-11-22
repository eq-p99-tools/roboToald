"""Tests for spellbook export parsing, storage, and the ``update_spellbook`` handler."""

from __future__ import annotations

import datetime
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from roboToald.api.server import _spells_from_text, app
from roboToald.db.models import sso
from roboToald.spellbook_parser import (
    MAX_SPELLBOOK_ENTRIES,
    MAX_SPELLBOOK_TEXT_BYTES,
    parse_spellbook_text,
)
from tests.test_ws_auth_flow import _patch_ws_auth_ok

SAMPLE_PATH = Path(__file__).parent / "data" / "p99-spellbook-sample.txt"
GUILD_ID = 515151


@pytest.fixture(scope="module")
def sample_text() -> str:
    return SAMPLE_PATH.read_text(encoding="utf-8")


def test_parse_real_p99_sample(sample_text):
    spells = parse_spellbook_text(sample_text)
    assert spells is not None
    assert len(spells) == 21
    assert spells[0] == (44, "Shock of Swords")
    assert spells[-1] == (34, "Minor Conjuration: Earth")
    assert (4, "Gate") in spells
    assert (12, "Elemental: Earth") in spells
    assert (29, "Burnout II") in spells


def test_parse_accepts_spaces_and_crlf(sample_text):
    spaced = sample_text.replace("\t", "    ").replace("\n", "\r\n")
    assert parse_spellbook_text(spaced) == parse_spellbook_text(sample_text)


def test_parse_skips_blank_lines_and_collapses_duplicates():
    assert parse_spellbook_text("\n4\tGate\n\n4\tGate\n  12  Bind Affinity  \n") == [
        (4, "Gate"),
        (12, "Bind Affinity"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "  \n\t\n",
        "Level\tName\n4\tGate\n",
        "4\tGate\nnot a spell\n",
        "4\n",
        "0\tGate\n",
        "300\tGate\n",
        "4\t" + "x" * 256 + "\n",
    ],
)
def test_parse_rejects_non_spellbook_text(text):
    assert parse_spellbook_text(text) is None


def test_parse_rejects_too_many_entries():
    text = "".join(f"1\tSpell {i}\n" for i in range(MAX_SPELLBOOK_ENTRIES + 1))
    assert parse_spellbook_text(text) is None


def test_spells_from_text_ignores_oversized_and_non_strings(sample_text):
    assert _spells_from_text(sample_text) == parse_spellbook_text(sample_text)
    assert _spells_from_text("4\tGate\n" + " " * MAX_SPELLBOOK_TEXT_BYTES) is None
    assert _spells_from_text(None) is None
    assert _spells_from_text(["4\tGate"]) is None


def test_replace_character_spells_replaces_full_set(sso_session):
    sso.create_account(GUILD_ID, "magebot", "pw")
    sso.add_account_character(GUILD_ID, "magebot", "Zzzz", sso.CharacterClass.Magician)

    first = datetime.datetime(2026, 11, 22, 1, 0, 0)
    assert sso.replace_character_spells(GUILD_ID, "Zzzz", [(4, "Gate"), (8, "Flame Bolt")], now=first)
    assert sso.get_character_spells(GUILD_ID, "Zzzz") == [(4, "Gate"), (8, "Flame Bolt")]

    second = first + datetime.timedelta(hours=1)
    assert sso.replace_character_spells(GUILD_ID, "Zzzz", [(12, "Bind Affinity"), (4, "Gate")], now=second)
    assert sso.get_character_spells(GUILD_ID, "Zzzz") == [(4, "Gate"), (12, "Bind Affinity")]
    assert sso_session.query(sso.SSOCharacterSpell).count() == 2

    character = sso_session.query(sso.SSOAccountCharacter).filter_by(name="Zzzz").one()
    assert character.spellbook_updated_at == second


def test_replace_character_spells_unknown_character(sso_session):
    assert not sso.replace_character_spells(GUILD_ID, "Nobody", [(4, "Gate")])
    assert sso.get_character_spells(GUILD_ID, "Nobody") == []


def test_removing_character_drops_its_spells(sso_session):
    sso.create_account(GUILD_ID, "magebot", "pw")
    sso.add_account_character(GUILD_ID, "magebot", "Zzzz", sso.CharacterClass.Magician)
    sso.replace_character_spells(GUILD_ID, "Zzzz", [(4, "Gate")])
    character = sso_session.query(sso.SSOAccountCharacter).filter_by(name="Zzzz").one()
    sso_session.delete(character)
    sso_session.commit()
    assert sso_session.query(sso.SSOCharacterSpell).count() == 0


@pytest.fixture()
def client():
    with TestClient(app) as tc:
        yield tc


def _patch_update_spellbook(monkeypatch, *, access: bool = True):
    _patch_ws_auth_ok(monkeypatch)
    acc = SimpleNamespace(id=3, real_user="u")
    monkeypatch.setattr(
        "roboToald.api.server.sso_model.find_account_by_character", lambda g, n: acc if n == "Zed" else None
    )
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc] if access else [])

    replaced: list[tuple] = []

    def fake_replace(guild_id, name, spells):
        replaced.append((guild_id, name, spells))
        return True

    monkeypatch.setattr("roboToald.api.server.sso_model.replace_character_spells", fake_replace)

    notified: list[int] = []

    async def notify(gid, immediate=False):
        notified.append(gid)

    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild_async", notify)
    return replaced, notified


def _send_after_auth(client, message: dict) -> None:
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json(message)
        time.sleep(0.05)


def test_ws_update_spellbook_stores_spells_without_delta(client, monkeypatch, sample_text):
    replaced, notified = _patch_update_spellbook(monkeypatch)
    _send_after_auth(client, {"type": "update_spellbook", "character_name": "Zed", "spellbook": sample_text})
    assert len(replaced) == 1
    guild_id, name, spells = replaced[0]
    assert (guild_id, name) == (1, "Zed")
    assert spells == parse_spellbook_text(sample_text)
    assert notified == []


def test_ws_update_spellbook_without_access_is_ignored(client, monkeypatch, sample_text):
    replaced, _ = _patch_update_spellbook(monkeypatch, access=False)
    _send_after_auth(client, {"type": "update_spellbook", "character_name": "Zed", "spellbook": sample_text})
    assert replaced == []


def test_ws_update_spellbook_unknown_character_is_ignored(client, monkeypatch, sample_text):
    replaced, _ = _patch_update_spellbook(monkeypatch)
    _send_after_auth(client, {"type": "update_spellbook", "character_name": "Other", "spellbook": sample_text})
    assert replaced == []


def test_ws_update_spellbook_unparseable_is_ignored(client, monkeypatch):
    replaced, _ = _patch_update_spellbook(monkeypatch)
    _send_after_auth(client, {"type": "update_spellbook", "character_name": "Zed", "spellbook": "garbage"})
    assert replaced == []
