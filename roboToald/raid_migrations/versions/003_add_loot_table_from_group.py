"""Add loot_tables.from_group flag for group-expanded items.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("loot_tables", sa.Column("from_group", sa.Boolean(), nullable=True, server_default="0"))


def downgrade() -> None:
    op.drop_column("loot_tables", "from_group")
