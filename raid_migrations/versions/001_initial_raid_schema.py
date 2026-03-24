"""Initial raid schema — collapsed from 38 Ruby Sequel migrations.

On the existing production database, stamp this as applied rather than running it.
On a fresh dev database, this creates the full schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tiers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("value", sa.Integer),
        sa.Column("nokill_value", sa.Integer),
    )

    op.create_table(
        "targets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tier_id", sa.Integer, sa.ForeignKey("tiers.id")),
        sa.Column("name", sa.String),
        sa.Column("value", sa.Integer),
        sa.Column("nokill_value", sa.Integer),
        sa.Column("rate_per_hour", sa.Integer, server_default="4"),
        sa.Column("eqdkp_event_id", sa.Integer),
        sa.Column("racing_per_hour", sa.Integer, server_default="6"),
        sa.Column("parent", sa.Text),
        sa.Column("can_rte", sa.Boolean),
        sa.Column("rte_attendence", sa.Boolean),
        sa.Column("pull_other_rte_in", sa.Boolean),
        sa.Column("close_on_quake", sa.Boolean),
        sa.Column("lockout_hrs", sa.Integer),
        sa.Column("last_batphone_at", sa.DateTime),
        sa.Column("rte_tank", sa.Integer),
        sa.Column("rte_ramp", sa.Integer),
        sa.Column("rte_kiter", sa.Integer),
        sa.Column("rte_bumper", sa.Integer),
        sa.Column("rte_puller", sa.Integer),
        sa.Column("rte_racer", sa.Integer),
        sa.Column("rte_tracker", sa.Integer),
        sa.Column("rte_trainer", sa.Integer),
        sa.Column("rte_tagger", sa.Integer),
        sa.Column("rte_cother", sa.Integer),
        sa.Column("rte_anchor", sa.Integer),
        sa.Column("rte_sower", sa.Integer),
        sa.Column("rte_dmf", sa.Integer),
        sa.Column("rte_cleric", sa.Integer),
        sa.Column("rte_enchanter", sa.Integer),
        sa.Column("rte_shaman", sa.Integer),
        sa.Column("rte_bard", sa.Integer),
    )

    op.create_table(
        "target_aliases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id")),
        sa.Column("name", sa.String),
    )

    op.create_table(
        "characters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("eqdkp_member_id", sa.Integer),
        sa.Column("eqdkp_main_id", sa.Text),
        sa.Column("eqdkp_user_id", sa.Text),
        sa.Column("klass", sa.Text),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id")),
        sa.Column("channel_id", sa.String),
        sa.Column("eqdkp_event_id", sa.Integer),
        sa.Column("eqdkp_raid_id", sa.Integer),
        sa.Column("name", sa.String),
        sa.Column("dkp", sa.Integer),
        sa.Column("nokill_dkp", sa.Integer),
        sa.Column("killed", sa.Boolean),
        sa.Column("created_at", sa.DateTime),
        sa.Column("raid_status_post_id", sa.Text),
        sa.Column("first_message_id", sa.Text),
    )

    op.create_table(
        "attendees",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id")),
        sa.Column("character_id", sa.String),
        sa.Column("on_character_id", sa.String),
        sa.Column("reason", sa.String),
        sa.Column("tracking_id", sa.Text),
    )

    op.create_table(
        "trackings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("message_id", sa.String),
        sa.Column("adjustment_id", sa.Integer),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id")),
        sa.Column("character_id", sa.Integer, sa.ForeignKey("characters.id")),
        sa.Column("start_time", sa.DateTime),
        sa.Column("end_time", sa.DateTime),
        sa.Column("is_rte", sa.Boolean, server_default="false"),
        sa.Column("user_pm_message_id", sa.Text),
        sa.Column("user_id", sa.Text),
        sa.Column("is_racing", sa.Boolean, server_default="false"),
        sa.Column("on_character_id", sa.Integer, sa.ForeignKey("characters.id")),
        sa.Column("role_id", sa.Integer),
        sa.Column("close_event_id", sa.Integer, sa.ForeignKey("events.id")),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id")),
    )

    op.create_table(
        "items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
    )

    op.create_table(
        "loots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id")),
        sa.Column("name", sa.String),
    )

    op.create_table(
        "event_loots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("eqdkp_item_id", sa.Integer),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id")),
        sa.Column("loot_id", sa.Integer, sa.ForeignKey("loots.id")),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id")),
        sa.Column("character_id", sa.Integer, sa.ForeignKey("characters.id")),
        sa.Column("attendee_id", sa.Integer, sa.ForeignKey("attendees.id")),
        sa.Column("dkp", sa.Integer),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "removals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id")),
        sa.Column("character_id", sa.Integer),
        sa.Column("reason", sa.String),
    )

    op.create_table(
        "loot_tables",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id")),
        sa.Column("target_id", sa.Integer, sa.ForeignKey("targets.id")),
    )

    op.create_table(
        "ftes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id")),
        sa.Column("character_id", sa.Integer),
        sa.Column("dkp", sa.Integer),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("role", sa.String),
        sa.Column("server", sa.String),
        sa.Column("permission", sa.String),
    )

    op.create_table(
        "eqdkp_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("eqdkp_event_id", sa.String),
    )


def downgrade() -> None:
    op.drop_table("eqdkp_events")
    op.drop_table("permissions")
    op.drop_table("ftes")
    op.drop_table("loot_tables")
    op.drop_table("removals")
    op.drop_table("event_loots")
    op.drop_table("loots")
    op.drop_table("items")
    op.drop_table("trackings")
    op.drop_table("attendees")
    op.drop_table("events")
    op.drop_table("characters")
    op.drop_table("target_aliases")
    op.drop_table("targets")
    op.drop_table("tiers")
