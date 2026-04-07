"""Add key_seb, key_vp, key_st to sso_account_character

Revision ID: b4c5d6e7f8a9
Revises: a2b3c4d5e6f7
Create Date: 2026-04-04 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("key_seb", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("key_vp", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("key_st", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("key_st")
        batch_op.drop_column("key_vp")
        batch_op.drop_column("key_seb")
