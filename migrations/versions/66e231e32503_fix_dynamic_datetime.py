"""fix dynamic datetime

Revision ID: 66e231e32503
Revises: 966d405d64c2
Create Date: 2025-05-07 00:34:44.416423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

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
    
    # Create unique constraint on alerts table
    if is_sqlite:
        with op.batch_alter_table('alerts') as batch_op:
            batch_op.create_unique_constraint('uc1', ['user_id', 'channel_id', 'alert_regex', 'alert_url'])
    else:
        op.create_unique_constraint('uc1', 'alerts', ['user_id', 'channel_id', 'alert_regex', 'alert_url'])
    
    # Handle sso_access_key table changes
    if is_sqlite:
        # For SQLite, we need to use batch operations
        with op.batch_alter_table('sso_access_key') as batch_op:
            batch_op.drop_index('idx_access_key')
            batch_op.drop_index('idx_guild_id_discord_user_id')
            batch_op.create_index('ix_sso_access_key_access_key', ['access_key'], unique=True)
            batch_op.create_unique_constraint('uq_guild_id_discord_user_id', ['guild_id', 'discord_user_id'])
    else:
        # For other databases, use standard operations
        op.drop_index('idx_access_key', table_name='sso_access_key')
        op.drop_index('idx_guild_id_discord_user_id', table_name='sso_access_key')
        op.create_index(op.f('ix_sso_access_key_access_key'), 'sso_access_key', ['access_key'], unique=True)
        op.create_unique_constraint('uq_guild_id_discord_user_id', 'sso_access_key', ['guild_id', 'discord_user_id'])
    
    # Handle sso_account table changes
    if is_sqlite:
        with op.batch_alter_table('sso_account') as batch_op:
            batch_op.alter_column('real_pass', existing_type=sa.BLOB(), nullable=False)
            # For SQLite, we need to drop and recreate the constraint in batch mode
            batch_op.drop_constraint('pk_guild_id_real_user', type_='unique')
            batch_op.create_unique_constraint('uq_guild_id_real_user', ['guild_id', 'real_user'])
    else:
        op.alter_column('sso_account', 'real_pass', existing_type=sa.BLOB(), nullable=False)
        op.drop_constraint('pk_guild_id_real_user', 'sso_account', type_='unique')
        op.create_unique_constraint('uq_guild_id_real_user', 'sso_account', ['guild_id', 'real_user'])
    
    # Handle sso_account_group table changes
    if is_sqlite:
        with op.batch_alter_table('sso_account_group') as batch_op:
            batch_op.drop_constraint('pk_guild_id_group_name', type_='unique')
            batch_op.create_unique_constraint('uq_guild_id_group_name', ['guild_id', 'group_name'])
    else:
        op.drop_constraint('pk_guild_id_group_name', 'sso_account_group', type_='unique')
        op.create_unique_constraint('uq_guild_id_group_name', 'sso_account_group', ['guild_id', 'group_name'])
    
    # Handle sso_audit_log table changes
    if is_sqlite:
        with op.batch_alter_table('sso_audit_log') as batch_op:
            batch_op.alter_column('timestamp', existing_type=sa.DATETIME(), nullable=False)
            # Check if foreign key exists before creating it
            inspector = inspect(op.get_bind())
            fks = inspector.get_foreign_keys('sso_audit_log')
            has_fk = any(fk['referred_table'] == 'sso_account' and 'account_id' in fk['constrained_columns'] for fk in fks)
            if not has_fk:
                batch_op.create_foreign_key('fk_sso_audit_log_account_id', 'sso_account', ['account_id'], ['id'])
    else:
        op.alter_column('sso_audit_log', 'timestamp', existing_type=sa.DATETIME(), nullable=False)
        op.create_foreign_key('fk_sso_audit_log_account_id', 'sso_audit_log', 'sso_account', ['account_id'], ['id'])
    
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
            # Find the name of the foreign key constraint to drop
            inspector = inspect(op.get_bind())
            fks = inspector.get_foreign_keys('sso_audit_log')
            for fk in fks:
                if fk['referred_table'] == 'sso_account' and 'account_id' in fk['constrained_columns']:
                    batch_op.drop_constraint(fk.get('name'), type_='foreignkey')
            batch_op.alter_column('timestamp', existing_type=sa.DATETIME(), nullable=True)
    else:
        op.drop_constraint(None, 'sso_audit_log', type_='foreignkey')
        op.alter_column('sso_audit_log', 'timestamp', existing_type=sa.DATETIME(), nullable=True)
    
    # Handle sso_account_group table changes
    if is_sqlite:
        with op.batch_alter_table('sso_account_group') as batch_op:
            batch_op.drop_constraint('uq_guild_id_group_name', type_='unique')
            batch_op.create_unique_constraint('pk_guild_id_group_name', ['guild_id', 'group_name'])
    else:
        op.drop_constraint('uq_guild_id_group_name', 'sso_account_group', type_='unique')
        op.create_unique_constraint('pk_guild_id_group_name', 'sso_account_group', ['guild_id', 'group_name'])
    
    # Handle sso_account table changes
    if is_sqlite:
        with op.batch_alter_table('sso_account') as batch_op:
            batch_op.drop_constraint('uq_guild_id_real_user', type_='unique')
            batch_op.create_unique_constraint('pk_guild_id_real_user', ['guild_id', 'real_user'])
            batch_op.alter_column('real_pass', existing_type=sa.BLOB(), nullable=True)
    else:
        op.drop_constraint('uq_guild_id_real_user', 'sso_account', type_='unique')
        op.create_unique_constraint('pk_guild_id_real_user', 'sso_account', ['guild_id', 'real_user'])
        op.alter_column('sso_account', 'real_pass', existing_type=sa.BLOB(), nullable=True)
    
    # Handle sso_access_key table changes
    if is_sqlite:
        with op.batch_alter_table('sso_access_key') as batch_op:
            batch_op.drop_constraint('uq_guild_id_discord_user_id', type_='unique')
            batch_op.drop_index('ix_sso_access_key_access_key')
            batch_op.create_index('idx_guild_id_discord_user_id', ['guild_id', 'discord_user_id'], unique=False)
            batch_op.create_index('idx_access_key', ['access_key'], unique=False)
    else:
        op.drop_constraint('uq_guild_id_discord_user_id', 'sso_access_key', type_='unique')
        op.drop_index(op.f('ix_sso_access_key_access_key'), table_name='sso_access_key')
        op.create_index('idx_guild_id_discord_user_id', 'sso_access_key', ['guild_id', 'discord_user_id'], unique=False)
        op.create_index('idx_access_key', 'sso_access_key', ['access_key'], unique=False)
    
    # Drop unique constraint on alerts table
    if is_sqlite:
        with op.batch_alter_table('alerts') as batch_op:
            batch_op.drop_constraint('uc1', type_='unique')
    else:
        op.drop_constraint('uc1', 'alerts', type_='unique')