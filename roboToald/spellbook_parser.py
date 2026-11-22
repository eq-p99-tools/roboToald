"""Parse an EQ ``<Char>-Spellbook.txt`` export (``/outputfile spellbook``).

P99 writes one ``<level><TAB><spell name>`` line per scribed spell, unsorted,
with no header and no spell IDs. Tabs may have been turned into spaces on the
way, so any run of whitespace after the level is accepted.
"""

from __future__ import annotations

import re

# Servers ignore a larger ``spellbook`` string and keep the stored spells.
MAX_SPELLBOOK_TEXT_BYTES = 128 * 1024
MAX_SPELLBOOK_ENTRIES = 1000
MAX_SPELL_LEVEL = 255
SPELL_NAME_MAX_LEN = 255

_LINE = re.compile(r"^(\d{1,3})\s+(\S.*?)\s*$")


def parse_spellbook_text(text: str) -> list[tuple[int, str]] | None:
    """Return ``(level, spell_name)`` pairs in file order, without duplicate names.

    Returns ``None`` when the text is blank or any non-blank line is not a
    ``level name`` pair, so a stray file never replaces a stored spellbook.
    """
    spells: list[tuple[int, str]] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if not match:
            return None
        level = int(match.group(1))
        name = match.group(2)
        if not 1 <= level <= MAX_SPELL_LEVEL or len(name) > SPELL_NAME_MAX_LEN:
            return None
        if name in seen:
            continue
        seen.add(name)
        spells.append((level, name))
        if len(spells) > MAX_SPELLBOOK_ENTRIES:
            return None
    return spells or None
