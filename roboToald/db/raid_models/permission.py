import sqlalchemy as sa

from roboToald.db.raid_base import RaidBase


class Permission(RaidBase):
    __tablename__ = "permissions"

    id = sa.Column(sa.Integer, primary_key=True)
    role = sa.Column(sa.String)
    server = sa.Column(sa.String)
    permission = sa.Column(sa.String)
