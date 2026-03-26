"""Add client_version to sso_audit_log

Revision ID: a2b3c4d5e6f7
Revises: f8d2a6c93e05
Create Date: 2026-03-26 17:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f8d2a6c93e05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_audit_log") as batch_op:
        batch_op.add_column(sa.Column("client_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sso_audit_log") as batch_op:
        batch_op.drop_column("client_version")
