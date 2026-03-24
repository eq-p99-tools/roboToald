import zoneinfo

import sqlalchemy as sa

from roboToald.db.raid_base import RaidBase

ET = zoneinfo.ZoneInfo("America/New_York")


class Event(RaidBase):
    __tablename__ = "events"

    id = sa.Column(sa.Integer, primary_key=True)
    target_id = sa.Column(sa.Integer, sa.ForeignKey("targets.id"))
    channel_id = sa.Column(sa.String)
    eqdkp_event_id = sa.Column(sa.Integer)
    eqdkp_raid_id = sa.Column(sa.Integer)
    name = sa.Column(sa.String)
    dkp = sa.Column(sa.Integer)
    nokill_dkp = sa.Column(sa.Integer)
    killed = sa.Column(sa.Boolean)
    created_at = sa.Column(sa.DateTime)
    raid_status_post_id = sa.Column(sa.Text)
    first_message_id = sa.Column(sa.Text)

    target = sa.orm.relationship("Target", foreign_keys=[target_id], lazy="joined")

    @property
    def channel_name(self) -> str:
        if self.created_at:
            et_time = self.created_at.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(ET)
            return f"{self.name} {et_time.strftime('%b-%d-%I%p').lower()}"
        return self.name or ""

    @property
    def target_name(self) -> str:
        if self.target:
            return self.target.name
        return self.name or ""

    @property
    def dkp_value(self) -> int | None:
        if self.dkp is not None:
            if self.killed is False:
                return self.nokill_dkp_value
            return self.dkp
        if self.target:
            return self.target.dkp_value(bool(self.killed)) or 0
        return None

    @property
    def nokill_dkp_value(self) -> int | None:
        if self.nokill_dkp is not None:
            return self.nokill_dkp
        if self.target:
            return self.target.dkp_value(False) or 0
        return None


class Attendee(RaidBase):
    __tablename__ = "attendees"

    id = sa.Column(sa.Integer, primary_key=True)
    event_id = sa.Column(sa.Integer, sa.ForeignKey("events.id"))
    character_id = sa.Column(sa.String)
    on_character_id = sa.Column(sa.String)
    reason = sa.Column(sa.String)
    tracking_id = sa.Column(sa.Text)


class Removal(RaidBase):
    __tablename__ = "removals"

    id = sa.Column(sa.Integer, primary_key=True)
    event_id = sa.Column(sa.Integer, sa.ForeignKey("events.id"))
    character_id = sa.Column(sa.Integer)
    reason = sa.Column(sa.String)


class Fte(RaidBase):
    __tablename__ = "ftes"

    id = sa.Column(sa.Integer, primary_key=True)
    event_id = sa.Column(sa.Integer, sa.ForeignKey("events.id"))
    character_id = sa.Column(sa.Integer)
    dkp = sa.Column(sa.Integer)


class EqdkpEvent(RaidBase):
    __tablename__ = "eqdkp_events"

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)
    eqdkp_event_id = sa.Column(sa.String)
