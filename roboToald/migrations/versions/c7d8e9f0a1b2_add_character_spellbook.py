"""add sso_character_spell table and spellbook_updated_at

Revision ID: c7d8e9f0a1b2
Revises: f9a0b1c2d3e4
Create Date: 2026-11-22 02:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("spellbook_updated_at", sa.DateTime, nullable=True))
    op.create_table(
        "sso_character_spell",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "character_id",
            sa.Integer,
            sa.ForeignKey("sso_account_character.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("spell_name", sa.String(255), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.UniqueConstraint("character_id", "spell_name", name="uq_character_spell"),
    )
    op.create_index("ix_character_spell_name", "sso_character_spell", ["spell_name"])


def downgrade() -> None:
    op.drop_index("ix_character_spell_name", table_name="sso_character_spell")
    op.drop_table("sso_character_spell")
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("spellbook_updated_at")
