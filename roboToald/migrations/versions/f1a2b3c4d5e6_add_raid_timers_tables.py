"""add raid timers tables

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-10-22 05:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rt_targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=255), nullable=False),
        sa.Column("aliases", sa.String(length=1023), nullable=False),
        sa.Column("era", sa.String(length=255), nullable=False),
        sa.Column("zone", sa.String(length=255), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=True),
        sa.Column("quake_immune", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("seed_key", sa.String(length=255), nullable=True),
        sa.Column("customized", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "name", name="uq_rt_targets_guild_name"),
    )
    op.create_index("ix_rt_targets_guild_id", "rt_targets", ["guild_id"])

    op.create_table(
        "rt_respawn_ranges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("min_minutes", sa.Integer(), nullable=False),
        sa.Column("max_minutes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["rt_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rt_respawn_ranges_target_id", "rt_respawn_ranges", ["target_id"])

    op.create_table(
        "rt_tods",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("tod_utc", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reported_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["rt_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rt_tods_guild_target_id", "rt_tods", ["guild_id", "target_id", "id"])

    op.create_table(
        "rt_quakes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("quake_utc", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reported_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rt_quakes_guild_id", "rt_quakes", ["guild_id", "id"])

    op.create_table(
        "rt_board_messages",
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("message_ids", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("guild_id"),
    )


def downgrade() -> None:
    op.drop_table("rt_board_messages")
    op.drop_index("ix_rt_quakes_guild_id", table_name="rt_quakes")
    op.drop_table("rt_quakes")
    op.drop_index("ix_rt_tods_guild_target_id", table_name="rt_tods")
    op.drop_table("rt_tods")
    op.drop_index("ix_rt_respawn_ranges_target_id", table_name="rt_respawn_ranges")
    op.drop_table("rt_respawn_ranges")
    op.drop_index("ix_rt_targets_guild_id", table_name="rt_targets")
    op.drop_table("rt_targets")
