"""item_lizard Boolean -> Integer (Lizard Blood Potion stack count)

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-04-08 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite cannot ALTER COLUMN type in place; copy via temp column.
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("item_lizard_i", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE sso_account_character SET item_lizard_i = "
            "CASE WHEN item_lizard IS NULL THEN NULL "
            "ELSE CAST(item_lizard AS INTEGER) END"
        )
    )
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("item_lizard")
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("item_lizard", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE sso_account_character SET item_lizard = item_lizard_i"))
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("item_lizard_i")


def downgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("item_lizard_b", sa.Boolean(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE sso_account_character SET item_lizard_b = "
            "CASE WHEN item_lizard IS NULL THEN NULL "
            "WHEN item_lizard > 0 THEN 1 ELSE 0 END"
        )
    )
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("item_lizard")
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("item_lizard", sa.Boolean(), nullable=True))
    op.execute(sa.text("UPDATE sso_account_character SET item_lizard = item_lizard_b"))
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("item_lizard_b")
