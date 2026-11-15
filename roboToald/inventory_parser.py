"""Parse an EQ ``*-Inventory.txt`` export into the ``items`` wire keys.

The login proxy sends the whole export on ``update_location``. Names recognized
here can grow without a client release; the proxy's local-character parser is a
separate copy used only for characters that never reach the server.
"""

from __future__ import annotations

import csv
import io
import logging

logger = logging.getLogger(__name__)

# EQ item Name column -> WebSocket ``items`` wire key (matches WIRE_KEY_TO_ATTR).
INVENTORY_TRACKED_ITEMS = {
    "Trakanon Idol": "seb",
    "Key of Veeshan": "vp",
    "Sleeper's Key": "st",
    "Box of the Void": "void",
    "Necklace of Resolution": "neck",
    "Vial of Velium Vapors": "thurg",
    "Reaper of the Dead": "reaper",
    "Shiny Brass Idol": "brass_idol",
}

# Stackable items: sum ``Count`` for every row with this Name -> wire key.
INVENTORY_COUNTED_ITEMS = {
    "Lizard Blood Potion": "lizard",
    "Pearl": "pearl",
    "Peridot": "peridot",
    "Mana Battery - Class Three": "mb3",
    "Mana Battery - Class Four": "mb4",
    "Mana Battery - Class Five": "mb5",
}

# Servers ignore a larger ``inventory`` string and leave stored items unchanged.
MAX_INVENTORY_TEXT_BYTES = 512 * 1024


def _default_inventory_result() -> dict[str, bool | int]:
    result: dict[str, bool | int] = {wire: False for wire in INVENTORY_TRACKED_ITEMS.values()}
    result.update({wire: 0 for wire in INVENTORY_COUNTED_ITEMS.values()})
    return result


def parse_inventory_text(text: str) -> dict[str, bool | int] | None:
    """Parse a tab-delimited inventory export.

    Returns the full tracked-item map (missing items are ``False`` or ``0``).
    Returns ``None`` when the text has no ``Name`` column, so the caller can
    leave stored items unchanged instead of clearing them.
    """
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = next(reader, None)
    if not header:
        return None
    try:
        name_idx = header.index("Name")
    except ValueError:
        logger.warning("Inventory export missing Name column")
        return None
    try:
        count_idx = header.index("Count")
    except ValueError:
        count_idx = None
        logger.warning("Inventory export missing Count column (stack totals will be 0)")

    result = _default_inventory_result()
    for row in reader:
        if len(row) <= name_idx:
            continue
        cell = row[name_idx].strip()
        wire_bool = INVENTORY_TRACKED_ITEMS.get(cell)
        if wire_bool:
            result[wire_bool] = True
        wire_count = INVENTORY_COUNTED_ITEMS.get(cell)
        if wire_count is not None and count_idx is not None and len(row) > count_idx:
            raw = row[count_idx].strip()
            try:
                add = int(raw) if raw else 0
            except ValueError:
                add = 0
            result[wire_count] = int(result[wire_count]) + add
    return result
