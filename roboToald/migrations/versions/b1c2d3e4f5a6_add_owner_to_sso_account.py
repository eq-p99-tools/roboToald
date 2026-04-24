"""Add owner_discord_user_id to sso_account

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-22 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_account") as batch_op:
        batch_op.add_column(sa.Column("owner_discord_user_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_sso_account_owner_discord_user_id",
            ["owner_discord_user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("sso_account") as batch_op:
        batch_op.drop_index("ix_sso_account_owner_discord_user_id")
        batch_op.drop_column("owner_discord_user_id")
