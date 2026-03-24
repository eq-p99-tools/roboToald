import sqlalchemy as sa

from roboToald.db.raid_base import RaidBase


class Item(RaidBase):
    __tablename__ = "items"

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)


class Loot(RaidBase):
    __tablename__ = "loots"

    id = sa.Column(sa.Integer, primary_key=True)
    item_id = sa.Column(sa.Integer, sa.ForeignKey("items.id"))
    name = sa.Column(sa.String)


class EventLoot(RaidBase):
    __tablename__ = "event_loots"

    id = sa.Column(sa.Integer, primary_key=True)
    eqdkp_item_id = sa.Column(sa.Integer)
    event_id = sa.Column(sa.Integer, sa.ForeignKey("events.id"))
    loot_id = sa.Column(sa.Integer, sa.ForeignKey("loots.id"))
    item_id = sa.Column(sa.Integer, sa.ForeignKey("items.id"))
    character_id = sa.Column(sa.Integer, sa.ForeignKey("characters.id"))
    attendee_id = sa.Column(sa.Integer, sa.ForeignKey("attendees.id"))
    dkp = sa.Column(sa.Integer)
    created_at = sa.Column(sa.DateTime)

    loot = sa.orm.relationship("Loot", foreign_keys=[loot_id], lazy="joined")
    character = sa.orm.relationship("Character", foreign_keys=[character_id], lazy="joined")


class LootTable(RaidBase):
    __tablename__ = "loot_tables"

    id = sa.Column(sa.Integer, primary_key=True)
    item_id = sa.Column(sa.Integer, sa.ForeignKey("items.id"))
    target_id = sa.Column(sa.Integer, sa.ForeignKey("targets.id"))

    item = sa.orm.relationship("Item", foreign_keys=[item_id], lazy="joined")
