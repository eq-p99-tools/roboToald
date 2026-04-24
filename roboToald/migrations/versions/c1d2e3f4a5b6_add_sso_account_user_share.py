"""Add sso_account_user_share table for direct user-to-user shares

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-04-22 13:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sso_account_user_share",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("shared_with_discord_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_discord_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["sso_account.id"], ondelete="CASCADE", name="fk_sso_account_user_share_account_id"
        ),
        sa.UniqueConstraint(
            "account_id",
            "shared_with_discord_user_id",
            name="uq_account_id_shared_with",
        ),
    )
    with op.batch_alter_table("sso_account_user_share") as batch_op:
        batch_op.create_index("ix_sso_account_user_share_account_id", ["account_id"])
        batch_op.create_index(
            "ix_sso_account_user_share_shared_with_discord_user_id",
            ["shared_with_discord_user_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("sso_account_user_share") as batch_op:
        batch_op.drop_index("ix_sso_account_user_share_shared_with_discord_user_id")
        batch_op.drop_index("ix_sso_account_user_share_account_id")
    op.drop_table("sso_account_user_share")
