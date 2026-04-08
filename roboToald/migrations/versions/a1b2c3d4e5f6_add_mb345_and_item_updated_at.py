"""Add item_mb3/4/5 and per-field *_updated_at timestamps on sso_account_character

Revision ID: a1b2c3d4e5f6
Revises: e7f8a9b0c1d2
Create Date: 2026-04-08 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.add_column(sa.Column("item_mb3", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("item_mb4", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("item_mb5", sa.Integer(), nullable=True))
        dt = sa.DateTime()
        batch_op.add_column(sa.Column("key_seb_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("key_vp_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("key_st_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_void_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_neck_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_lizard_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_thurg_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_reaper_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_brass_idol_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_pearl_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_peridot_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_mb3_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_mb4_updated_at", dt, nullable=True))
        batch_op.add_column(sa.Column("item_mb5_updated_at", dt, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sso_account_character") as batch_op:
        batch_op.drop_column("item_mb5_updated_at")
        batch_op.drop_column("item_mb4_updated_at")
        batch_op.drop_column("item_mb3_updated_at")
        batch_op.drop_column("item_peridot_updated_at")
        batch_op.drop_column("item_pearl_updated_at")
        batch_op.drop_column("item_brass_idol_updated_at")
        batch_op.drop_column("item_reaper_updated_at")
        batch_op.drop_column("item_thurg_updated_at")
        batch_op.drop_column("item_lizard_updated_at")
        batch_op.drop_column("item_neck_updated_at")
        batch_op.drop_column("item_void_updated_at")
        batch_op.drop_column("key_st_updated_at")
        batch_op.drop_column("key_vp_updated_at")
        batch_op.drop_column("key_seb_updated_at")
        batch_op.drop_column("item_mb5")
        batch_op.drop_column("item_mb4")
        batch_op.drop_column("item_mb3")
