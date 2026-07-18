"""Validate the WebSocket protocol schema against fixtures and live message shapes.

The schema at ``schemas/ws-protocol.schema.json`` is the canonical contract for the
WebSocket channel shared with the ``p99-login-proxy`` client (which vendors a copy).
These tests keep the server honest two ways:

* every fixture under ``schemas/fixtures/`` must validate against the schema, and
* messages built from the real server helpers (``build_account_tree`` /
  ``compute_diff``) must validate when wrapped in their ``full_state`` / ``delta``
  envelopes -- so a change to the emitted shape trips this test.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from roboToald.api.websocket import build_account_tree, compute_diff

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "ws-protocol.schema.json"
FIXTURES_DIR = SCHEMA_PATH.parent / "fixtures"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _fixture_files() -> list[Path]:
    return sorted(FIXTURES_DIR.rglob("*.json"))


def _fixture_id(path: Path) -> str:
    return str(path.relative_to(FIXTURES_DIR)).replace("\\", "/")


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("fixture_path", _fixture_files(), ids=_fixture_id)
def test_fixture_matches_schema(schema: dict, fixture_path: Path) -> None:
    message = json.loads(fixture_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=message, schema=schema)


def test_unknown_message_type_is_rejected(schema: dict) -> None:
    # A message whose `type` matches no `$defs` const satisfies none of the
    # `oneOf` branches, so it must fail validation (the client tolerates it at
    # runtime, but it is not part of the contract).
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance={"type": "not_a_real_message"}, schema=schema)


def _char(name: str, **kwargs) -> SimpleNamespace:
    fields = {
        "name": name,
        "klass": kwargs.get("klass"),
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
    return SimpleNamespace(**fields)


def _account(real_user: str, *, tags=(), characters=(), id=1) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        real_user=real_user,
        aliases=[],
        tags=[SimpleNamespace(tag=t) for t in tags],
        characters=list(characters),
        last_login=None,
        last_login_by=None,
        owner_discord_user_id=None,
        shares=[],
    )


def test_live_full_state_matches_schema(schema: dict) -> None:
    account = _account("main", tags=["clr"], characters=[_char("Zzzz", level=60, key_seb=True)])
    tree = build_account_tree([account], active_characters={1: "Zzzz"})
    message = {
        "type": "full_state",
        "account_tree": tree,
        "count": len(tree),
        "dynamic_tag_zones": ["seb", "vp"],
        "dynamic_tag_classes": ["clr"],
    }
    jsonschema.validate(instance=message, schema=schema)


def test_live_delta_matches_schema(schema: dict) -> None:
    old_tree = build_account_tree([_account("main", tags=["clr"])])
    new_tree = build_account_tree([_account("main", tags=["clr", "vp"], characters=[_char("Zzzz", level=60)])])
    changes = compute_diff(old_tree, new_tree)
    assert changes, "expected compute_diff to produce at least one change"
    message = {"type": "delta", "changes": changes}
    jsonschema.validate(instance=message, schema=schema)
