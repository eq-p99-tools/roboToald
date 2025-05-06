"""Add rate_limit column to SSOAuditLog

Revision ID: 966d405d64c2
Revises: 
Create Date: 2025-05-06 03:22:53.205128

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '966d405d64c2'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add rate_limit column to sso_audit_log - this is the main change we need
    op.add_column('sso_audit_log', sa.Column('rate_limit', sa.Boolean(), nullable=True, server_default='1'))
    
    # For SQLite, we need to use batch operations for constraint changes
    # We'll skip the constraint changes for now as they're not critical
    # If you need to apply these changes later, use batch operations
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the rate_limit column from sso_audit_log
    op.drop_column('sso_audit_log', 'rate_limit')
    # ### end Alembic commands ###
