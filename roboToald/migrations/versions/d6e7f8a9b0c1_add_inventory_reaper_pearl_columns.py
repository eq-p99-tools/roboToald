"""Add item_reaper, item_brass_idol, item_pearl, item_peridot to sso_account_character

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-04-08 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("item_reaper", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("item_brass_idol", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("item_pearl", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("item_peridot", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("item_peridot")
        batch_op.drop_column("item_pearl")
        batch_op.drop_column("item_brass_idol")
        batch_op.drop_column("item_reaper")
