"""Add login notes to sso_account and sso_account_character

Revision ID: b3c4d5e6f7a8
Revises: e8f9a0b1c2d3
Create Date: 2026-11-21 10:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_account") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("notes")
    with op.batch_alter_table("sso_account") as batch_op:
        batch_op.drop_column("notes")
