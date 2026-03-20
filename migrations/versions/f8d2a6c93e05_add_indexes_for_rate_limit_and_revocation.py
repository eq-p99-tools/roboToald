"""Add indexes for rate limit and revocation lookups

Revision ID: f8d2a6c93e05
Revises: e7b2a4f91d03
Create Date: 2026-03-16 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f8d2a6c93e05"
down_revision: Union[str, None] = "e7b2a4f91d03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_rate_limit",
        "sso_audit_log",
        ["ip_address", "success", "timestamp"],
    )
    op.create_index(
        "ix_revocation_lookup",
        "sso_revocations",
        ["guild_id", "discord_user_id", "active"],
    )


def downgrade() -> None:
    op.drop_index("ix_revocation_lookup", table_name="sso_revocations")
    op.drop_index("ix_audit_rate_limit", table_name="sso_audit_log")
