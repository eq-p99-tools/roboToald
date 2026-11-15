"""Tests for parsing raw EQ inventory exports on the server."""

from __future__ import annotations

from roboToald.api.server import _inventory_wires_from_message
from roboToald.inventory_parser import (
    INVENTORY_COUNTED_ITEMS,
    INVENTORY_TRACKED_ITEMS,
    MAX_INVENTORY_TEXT_BYTES,
    parse_inventory_text,
)

_HEADER = "Location\tName\tID\tCount\tSlots\n"


def test_parse_empty_text_is_ignored():
    assert parse_inventory_text("") is None
    assert parse_inventory_text("   \n") is None


def test_parse_missing_name_column_is_ignored():
    assert parse_inventory_text("Location\tID\tCount\n") is None


def test_parse_sums_pearl_counts():
    text = _HEADER + "G1\tPearl\t13073\t3\t5\nG2\tPearl\t13073\t20\t5\nG3\tPearl\t13073\t20\t5\n"
    parsed = parse_inventory_text(text)
    assert parsed is not None
    assert parsed["pearl"] == 43
    assert parsed["peridot"] == 0
    assert parsed["seb"] is False


def test_parse_presence_flags():
    text = _HEADER + "X\tReaper of the Dead\t1\t1\t5\nY\tShiny Brass Idol\t2\t1\t5\nZ\tTrakanon Idol\t3\t1\t5\n"
    parsed = parse_inventory_text(text)
    assert parsed is not None
    assert parsed["reaper"] is True
    assert parsed["brass_idol"] is True
    assert parsed["seb"] is True
    assert parsed["vp"] is False


def test_parse_stack_counts():
    text = (
        _HEADER
        + "A\tLizard Blood Potion\t1\t5\t5\n"
        + "B\tLizard Blood Potion\t1\t3\t5\n"
        + "C\tMana Battery - Class Three\t1\t2\t5\n"
        + "D\tMana Battery - Class Four\t2\t1\t5\n"
        + "E\tMana Battery - Class Five\t3\t4\t5\n"
        + "F\tPeridot\t4\t10\t5\n"
        + "G\tPearl\t5\tx\t5\n"
        + "H\tPearl\t5\t7\t5\n"
    )
    parsed = parse_inventory_text(text)
    assert parsed is not None
    assert parsed["lizard"] == 8
    assert parsed["mb3"] == 2
    assert parsed["mb4"] == 1
    assert parsed["mb5"] == 4
    assert parsed["peridot"] == 10
    assert parsed["pearl"] == 7


def test_parse_covers_every_tracked_wire():
    parsed = parse_inventory_text(_HEADER)
    assert parsed is not None
    assert set(parsed) == set(INVENTORY_TRACKED_ITEMS.values()) | set(INVENTORY_COUNTED_ITEMS.values())


def test_inventory_text_replaces_legacy_items():
    text = _HEADER + "Primary\tTrakanon Idol\t1\t1\t5\nGeneral1\tPearl\t2\t4\t5\n"
    wires = _inventory_wires_from_message(
        {
            "inventory": text,
            "items": {"seb": False, "pearl": 99},
            "keys": {"vp": True},
        }
    )
    assert wires["seb"] is True
    assert wires["pearl"] == 4
    assert wires["vp"] is False


def test_unparseable_inventory_falls_back_to_items():
    wires = _inventory_wires_from_message({"inventory": "not an export", "items": {"seb": True}})
    assert wires == {"seb": True}


def test_oversized_inventory_falls_back_to_items():
    wires = _inventory_wires_from_message(
        {"inventory": "Name\tCount\n" + ("x" * (MAX_INVENTORY_TEXT_BYTES + 1)), "items": {"pearl": 3}}
    )
    assert wires == {"pearl": 3}


def test_blank_inventory_uses_items():
    wires = _inventory_wires_from_message({"inventory": "  \n", "keys": {"vp": True}})
    assert wires == {"vp": True}
