import sqlalchemy as sa

from roboToald.db.raid_base import RaidBase

RTE_ROLES = {
    1:  {"name": "Tank",      "column": "rte_tank"},
    2:  {"name": "Ramp",      "column": "rte_ramp"},
    3:  {"name": "Kiter",     "column": "rte_kiter"},
    4:  {"name": "Bumper",    "column": "rte_bumper"},
    5:  {"name": "Puller",    "column": "rte_puller"},
    6:  {"name": "Racer",     "column": "rte_racer"},
    7:  {"name": "Tracker",   "column": "rte_tracker"},
    8:  {"name": "Trainer",   "column": "rte_trainer"},
    9:  {"name": "Tagger",    "column": "rte_tagger"},
    10: {"name": "Cother",    "column": "rte_cother"},
    11: {"name": "Anchor",    "column": "rte_anchor"},
    12: {"name": "Sower",     "column": "rte_sower"},
    13: {"name": "DMF",       "column": "rte_dmf"},
    14: {"name": "Cleric",    "column": "rte_cleric"},
    15: {"name": "Enchanter", "column": "rte_enchanter"},
    16: {"name": "Shaman",    "column": "rte_shaman"},
    17: {"name": "Bard",      "column": "rte_bard"},
}

RTE_ROLE_NAMES = [v["name"].lower() for v in RTE_ROLES.values()]


class Tracking(RaidBase):
    __tablename__ = "trackings"

    id = sa.Column(sa.Integer, primary_key=True)
    message_id = sa.Column(sa.String)
    adjustment_id = sa.Column(sa.Integer)
    target_id = sa.Column(sa.Integer, sa.ForeignKey("targets.id"))
    character_id = sa.Column(sa.Integer, sa.ForeignKey("characters.id"))
    start_time = sa.Column(sa.DateTime)
    end_time = sa.Column(sa.DateTime)
    is_rte = sa.Column(sa.Boolean, default=False)
    user_pm_message_id = sa.Column(sa.Text)
    user_id = sa.Column(sa.Text)
    is_racing = sa.Column(sa.Boolean, default=False)
    on_character_id = sa.Column(sa.Integer, sa.ForeignKey("characters.id"))
    role_id = sa.Column(sa.Integer)
    close_event_id = sa.Column(sa.Integer, sa.ForeignKey("events.id"))
    event_id = sa.Column(sa.Integer, sa.ForeignKey("events.id"))

    target = sa.orm.relationship("Target", foreign_keys=[target_id], lazy="joined")
    character = sa.orm.relationship("Character", foreign_keys=[character_id], lazy="joined")
    on_character = sa.orm.relationship("Character", foreign_keys=[on_character_id], lazy="joined")

    @property
    def role(self) -> dict:
        return RTE_ROLES.get(self.role_id, {"name": ""})

    @property
    def duration(self) -> float | None:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def rate_per_hour(self) -> int:
        role_info = self.role
        col = role_info.get("column")
        if col and self.target:
            val = getattr(self.target, col, None)
            if val is not None:
                return val
        if self.target:
            return self.target.rate_per_hour or 4
        return 4

    @property
    def dkp_amount(self) -> int:
        from roboToald.raid.dkp_calculator import dkp_from_duration
        dur = self.duration
        if dur is not None:
            return dkp_from_duration(self.rate_per_hour, dur)
        return 0

    @property
    def role_name(self) -> str:
        name = self.role.get("name", "")
        if name:
            return name
        char = self.on_character or self.character
        if char:
            return char.klass_name
        return ""

    @property
    def character_name(self) -> str:
        char = self.on_character or self.character
        return char.name if char else ""
