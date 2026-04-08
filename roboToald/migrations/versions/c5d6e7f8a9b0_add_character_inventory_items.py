"""Add item_void, item_neck, item_lizard, item_thurg to sso_account_character

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-04-08 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("item_void", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("item_neck", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("item_lizard", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("item_thurg", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("item_thurg")
        batch_op.drop_column("item_lizard")
        batch_op.drop_column("item_neck")
        batch_op.drop_column("item_void")
