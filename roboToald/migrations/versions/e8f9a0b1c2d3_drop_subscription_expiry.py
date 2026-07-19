"""drop subscription expiry column

Revision ID: e8f9a0b1c2d3
Revises: d2e3f4a5b6c7
Create Date: 2026-07-19 02:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.drop_column("expiry")


def downgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.add_column(sa.Column("expiry", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE subscriptions SET expiry = 0")
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.alter_column("expiry", server_default=None)
