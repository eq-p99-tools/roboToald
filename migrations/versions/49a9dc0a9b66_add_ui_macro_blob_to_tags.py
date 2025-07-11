"""Add UI Macro blob to tags

Revision ID: 49a9dc0a9b66
Revises: 66e231e32503
Create Date: 2025-05-12 03:49:49.889717

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49a9dc0a9b66'
down_revision: Union[str, None] = '66e231e32503'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    # First create the new table
    op.create_table(
        'sso_tag_ui_macro',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('guild_id', sa.Integer(), nullable=False),
        sa.Column('tag_name', sa.String(length=255), nullable=False),
        sa.Column('ui_macro_data', sa.BLOB(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tag_name', 'guild_id', name='uq_tag_name_guild_id')
    )
    
    # Use batch operations for SQLite to add the foreign key
    with op.batch_alter_table('sso_tag') as batch_op:
        batch_op.add_column(sa.Column('ui_macro_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_sso_tag_ui_macro_id', 
            'sso_tag_ui_macro', 
            ['ui_macro_id'], 
            ['id']
        )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    # Use batch operations for SQLite to drop the foreign key and column
    with op.batch_alter_table('sso_tag') as batch_op:
        batch_op.drop_constraint('fk_sso_tag_ui_macro_id', type_='foreignkey')
        batch_op.drop_column('ui_macro_id')
    
    # Drop the table
    op.drop_table('sso_tag_ui_macro')
    # ### end Alembic commands ###
