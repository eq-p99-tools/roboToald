from __future__ import annotations

from typing import TYPE_CHECKING

from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.permission import Permission

if TYPE_CHECKING:
    import disnake


def can(member: disnake.Member, permission: str, guild_id: int) -> bool:
    """Check if a Discord member has a given permission.

    Matches the member's role names (lowercased) against the permissions table.
    Port of the Ruby can?(user, :permission) helper.
    """
    role_names = {r.name.lower() for r in member.roles}
    with get_raid_session(guild_id) as session:
        match = (
            session.query(Permission)
            .filter(
                Permission.permission == permission,
                Permission.role.in_(role_names),
            )
            .first()
        )
        return match is not None


def cannot(member: disnake.Member, permission: str, guild_id: int) -> bool:
    return not can(member, permission, guild_id)
