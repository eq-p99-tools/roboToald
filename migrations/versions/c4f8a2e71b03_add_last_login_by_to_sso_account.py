"""add last_login_by to sso_account

Revision ID: c4f8a2e71b03
Revises: b3e7c1d58a02
Create Date: 2026-03-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f8a2e71b03'
down_revision: Union[str, None] = 'b3e7c1d58a02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sso_account', sa.Column('last_login_by', sa.String(255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sso_account', 'last_login_by')
