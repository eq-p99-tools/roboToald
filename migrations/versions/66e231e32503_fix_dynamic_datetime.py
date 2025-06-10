"""fix dynamic datetime

Revision ID: 66e231e32503
Revises: 966d405d64c2
Create Date: 2025-05-07 00:34:44.416423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '66e231e32503'
down_revision: Union[str, None] = '966d405d64c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema using batch operations for SQLite compatibility."""
    # Get database connection and check if it's SQLite
    context = op.get_context()
    is_sqlite = context.dialect.name == 'sqlite'
    
    # Handle sso_audit_log table changes
    if is_sqlite:
        with op.batch_alter_table('sso_audit_log') as batch_op:
            batch_op.alter_column('timestamp', existing_type=sa.DATETIME(), nullable=False)
    else:
        op.alter_column('sso_audit_log', 'timestamp', existing_type=sa.DATETIME(), nullable=False)

    # Handle sso_revocations table changes
    if is_sqlite:
        with op.batch_alter_table('sso_revocations') as batch_op:
            batch_op.alter_column('timestamp', existing_type=sa.DATETIME(), nullable=False)
    else:
        op.alter_column('sso_revocations', 'timestamp', existing_type=sa.DATETIME(), nullable=False)


def downgrade() -> None:
    """Downgrade schema using batch operations for SQLite compatibility."""
    # Get database connection and check if it's SQLite
    context = op.get_context()
    is_sqlite = context.dialect.name == 'sqlite'
    
    # Handle reverting changes in reverse order
    
    # Handle sso_revocations table changes
    if is_sqlite:
        with op.batch_alter_table('sso_revocations') as batch_op:
            batch_op.alter_column('timestamp', existing_type=sa.DATETIME(), nullable=True)
    else:
        op.alter_column('sso_revocations', 'timestamp', existing_type=sa.DATETIME(), nullable=True)
    
    # Handle sso_audit_log table changes
    if is_sqlite:
        with op.batch_alter_table('sso_audit_log') as batch_op:
            batch_op.alter_column('timestamp', existing_type=sa.DATETIME(), nullable=True)
    else:
        op.alter_column('sso_audit_log', 'timestamp', existing_type=sa.DATETIME(), nullable=True)
    