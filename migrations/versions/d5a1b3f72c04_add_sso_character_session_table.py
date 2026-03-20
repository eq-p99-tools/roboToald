"""add sso_character_session table

Revision ID: d5a1b3f72c04
Revises: c4f8a2e71b03
Create Date: 2026-03-07 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5a1b3f72c04"
down_revision: Union[str, None] = "c4f8a2e71b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sso_character_session",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.Integer, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("sso_account.id"), nullable=False),
        sa.Column("character_name", sa.String(64), nullable=False),
        sa.Column("discord_user_id", sa.Integer, nullable=False),
        sa.Column("first_seen", sa.DateTime, nullable=False),
        sa.Column("last_seen", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_char_session_guild_time",
        "sso_character_session",
        ["guild_id", "first_seen", "last_seen"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_char_session_guild_time", table_name="sso_character_session")
    op.drop_table("sso_character_session")
