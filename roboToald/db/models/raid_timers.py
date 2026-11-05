"""Per-guild raid-timer catalog, ToDs, quakes, and board message state."""

from __future__ import annotations

import sqlalchemy
import sqlalchemy.orm

from roboToald.db import base


class RtTarget(base.Base, base.MyBase):
    __tablename__ = "rt_targets"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False, index=True)
    name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    short_name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False, default="")
    aliases = sqlalchemy.Column(sqlalchemy.String(1023), nullable=False, default="")
    era = sqlalchemy.Column(sqlalchemy.String(255), nullable=False, default="")
    zone = sqlalchemy.Column(sqlalchemy.String(255), nullable=False, default="")
    hidden = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    window_count = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)
    quake_immune = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    note = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    seed_key = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)
    customized = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)

    ranges = sqlalchemy.orm.relationship(
        "RtRespawnRange",
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="joined",
    )

    __table_args__ = (sqlalchemy.UniqueConstraint("guild_id", "name", name="uq_rt_targets_guild_name"),)


class RtRespawnRange(base.Base, base.MyBase):
    __tablename__ = "rt_respawn_ranges"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    target_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("rt_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    min_minutes = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    max_minutes = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    target = sqlalchemy.orm.relationship("RtTarget", back_populates="ranges")


class RtTod(base.Base, base.MyBase):
    __tablename__ = "rt_tods"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    target_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("rt_targets.id", ondelete="CASCADE"),
        nullable=False,
    )
    tod_utc = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    source = sqlalchemy.Column(sqlalchemy.String(32), nullable=False)
    reported_by = sqlalchemy.Column(sqlalchemy.String(255), nullable=False, default="")
    created_at = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    __table_args__ = (sqlalchemy.Index("ix_rt_tods_guild_target_id", "guild_id", "target_id", "id"),)


class RtQuake(base.Base, base.MyBase):
    __tablename__ = "rt_quakes"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    quake_utc = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    source = sqlalchemy.Column(sqlalchemy.String(32), nullable=False)
    reported_by = sqlalchemy.Column(sqlalchemy.String(255), nullable=False, default="")
    created_at = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    __table_args__ = (sqlalchemy.Index("ix_rt_quakes_guild_id", "guild_id", "id"),)


class RtBoardMessage(base.Base, base.MyBase):
    __tablename__ = "rt_board_messages"

    guild_id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    channel_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    message_ids = sqlalchemy.Column(sqlalchemy.Text, nullable=False, default="")


class RtLogCursor(base.Base, base.MyBase):
    """Last SSE event id applied for a guild log stream."""

    __tablename__ = "rt_log_cursors"

    guild_id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    seq = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    updated_at = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
