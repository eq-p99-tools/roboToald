import sqlalchemy as sa

from roboToald.db.raid_base import RaidBase


class Tier(RaidBase):
    __tablename__ = "tiers"

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)
    value = sa.Column(sa.Integer)
    nokill_value = sa.Column(sa.Integer)


class Target(RaidBase):
    __tablename__ = "targets"

    id = sa.Column(sa.Integer, primary_key=True)
    tier_id = sa.Column(sa.Integer, sa.ForeignKey("tiers.id"))
    name = sa.Column(sa.String)
    value = sa.Column(sa.Integer)
    nokill_value = sa.Column(sa.Integer)
    rate_per_hour = sa.Column(sa.Integer, default=4)
    eqdkp_event_id = sa.Column(sa.Integer)
    racing_per_hour = sa.Column(sa.Integer, default=6)
    parent = sa.Column(sa.Text)
    can_rte = sa.Column(sa.Boolean)
    rte_attendence = sa.Column(sa.Boolean)
    pull_other_rte_in = sa.Column(sa.Boolean)
    close_on_quake = sa.Column(sa.Boolean)
    lockout_hrs = sa.Column(sa.Integer)
    last_batphone_at = sa.Column(sa.DateTime)

    rte_tank = sa.Column(sa.Integer)
    rte_ramp = sa.Column(sa.Integer)
    rte_kiter = sa.Column(sa.Integer)
    rte_bumper = sa.Column(sa.Integer)
    rte_puller = sa.Column(sa.Integer)
    rte_racer = sa.Column(sa.Integer)
    rte_tracker = sa.Column(sa.Integer)
    rte_trainer = sa.Column(sa.Integer)
    rte_tagger = sa.Column(sa.Integer)
    rte_cother = sa.Column(sa.Integer)
    rte_anchor = sa.Column(sa.Integer)
    rte_sower = sa.Column(sa.Integer)
    rte_dmf = sa.Column(sa.Integer)
    rte_cleric = sa.Column(sa.Integer)
    rte_enchanter = sa.Column(sa.Integer)
    rte_shaman = sa.Column(sa.Integer)
    rte_bard = sa.Column(sa.Integer)

    tier = sa.orm.relationship("Tier", foreign_keys=[tier_id], lazy="joined")
    aliases = sa.orm.relationship("TargetAlias", back_populates="target", lazy="joined")

    def dkp_value(self, killed=False):
        if self.tier:
            if not killed:
                return self.nokill_value if self.nokill_value is not None else self.tier.nokill_value
            return self.value if self.value is not None else self.tier.value
        if not killed and self.nokill_value is not None:
            return self.nokill_value
        return self.value


class TargetAlias(RaidBase):
    __tablename__ = "target_aliases"

    id = sa.Column(sa.Integer, primary_key=True)
    target_id = sa.Column(sa.Integer, sa.ForeignKey("targets.id"))
    name = sa.Column(sa.String)

    target = sa.orm.relationship("Target", foreign_keys=[target_id], back_populates="aliases")
