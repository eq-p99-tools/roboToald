"""Add sso_share_disclaimer_acceptance table

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-22 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sso_share_disclaimer_acceptance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("discord_user_id", sa.Integer(), nullable=False),
        sa.Column("disclaimer_version", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "guild_id",
            "discord_user_id",
            "disclaimer_version",
            name="uq_share_disclaimer_guild_user_ver",
        ),
    )
    with op.batch_alter_table("sso_share_disclaimer_acceptance") as batch_op:
        batch_op.create_index("ix_sso_share_disclaimer_acceptance_guild_id", ["guild_id"])
        batch_op.create_index("ix_sso_share_disclaimer_acceptance_discord_user_id", ["discord_user_id"])


def downgrade() -> None:
    with op.batch_alter_table("sso_share_disclaimer_acceptance") as batch_op:
        batch_op.drop_index("ix_sso_share_disclaimer_acceptance_discord_user_id")
        batch_op.drop_index("ix_sso_share_disclaimer_acceptance_guild_id")
    op.drop_table("sso_share_disclaimer_acceptance")
