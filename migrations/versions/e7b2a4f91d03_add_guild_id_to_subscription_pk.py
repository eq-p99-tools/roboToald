"""add guild_id to subscription primary key

Revision ID: e7b2a4f91d03
Revises: d5a1b3f72c04
Create Date: 2026-03-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b2a4f91d03'
down_revision: Union[str, None] = 'd5a1b3f72c04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_GUILD_ID = 1007080931695267870

# Explicit copy of the current table schema so batch_alter_table can
# find the named PK constraint (SQLite reflection does not preserve names).
_existing_table = sa.Table(
    'subscriptions', sa.MetaData(),
    sa.Column('user_id', sa.Integer),
    sa.Column('target', sa.String(255)),
    sa.Column('expiry', sa.Integer, nullable=False),
    sa.Column('last_notified', sa.Integer, default=0),
    sa.Column('lead_time', sa.Integer, nullable=False, default=1800),
    sa.Column('last_window_start', sa.Integer, default=0),
    sa.Column('guild_id', sa.Integer, nullable=False),
    sa.PrimaryKeyConstraint('user_id', 'target',
                            name='pk_user_id_target'),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        f"UPDATE subscriptions SET guild_id = {LEGACY_GUILD_ID} "
        f"WHERE guild_id IS NULL OR guild_id = 0"
    )

    with op.batch_alter_table(
            'subscriptions', copy_from=_existing_table,
            recreate='always') as batch_op:
        batch_op.drop_constraint('pk_user_id_target', type_='primary')
        batch_op.create_primary_key(
            'pk_user_target_guild',
            ['user_id', 'target', 'guild_id'])


def downgrade() -> None:
    """Downgrade schema."""
    _new_table = sa.Table(
        'subscriptions', sa.MetaData(),
        sa.Column('user_id', sa.Integer),
        sa.Column('target', sa.String(255)),
        sa.Column('expiry', sa.Integer, nullable=False),
        sa.Column('last_notified', sa.Integer, default=0),
        sa.Column('lead_time', sa.Integer, nullable=False, default=1800),
        sa.Column('last_window_start', sa.Integer, default=0),
        sa.Column('guild_id', sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'target', 'guild_id',
                                name='pk_user_target_guild'),
    )

    with op.batch_alter_table(
            'subscriptions', copy_from=_new_table,
            recreate='always') as batch_op:
        batch_op.drop_constraint('pk_user_target_guild', type_='primary')
        batch_op.create_primary_key(
            'pk_user_id_target',
            ['user_id', 'target'])
