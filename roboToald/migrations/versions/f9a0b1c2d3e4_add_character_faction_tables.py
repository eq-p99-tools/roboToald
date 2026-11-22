"""add sso_character_faction and sso_faction_event tables

Revision ID: f9a0b1c2d3e4
Revises: b3c4d5e6f7a8
Create Date: 2026-11-21 10:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sso_character_faction",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.Integer, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("sso_account.id"), nullable=False),
        sa.Column("character_name", sa.String(64), nullable=False),
        sa.Column("faction", sa.String(255), nullable=False),
        sa.Column("hits_better", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hits_worse", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cap", sa.String(3), nullable=True),
        sa.Column("cap_at", sa.DateTime, nullable=True),
        sa.Column("last_direction", sa.String(6), nullable=False),
        sa.Column("first_hit_at", sa.DateTime, nullable=False),
        sa.Column("last_hit_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("guild_id", "character_name", "faction", name="uq_character_faction"),
    )
    op.create_table(
        "sso_faction_event",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.Integer, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("sso_account.id"), nullable=False),
        sa.Column("character_name", sa.String(64), nullable=False),
        sa.Column("faction", sa.String(255), nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("eq_log_time", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime, nullable=False),
        sa.Column("discord_user_id", sa.Integer, nullable=False),
        sa.Column("login_by", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_faction_event_guild_char_time",
        "sso_faction_event",
        ["guild_id", "character_name", "received_at"],
    )
    op.create_index("ix_faction_event_received_at", "sso_faction_event", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_faction_event_received_at", table_name="sso_faction_event")
    op.drop_index("ix_faction_event_guild_char_time", table_name="sso_faction_event")
    op.drop_table("sso_faction_event")
    op.drop_table("sso_character_faction")
