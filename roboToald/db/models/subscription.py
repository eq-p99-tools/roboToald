import logging
import time
from typing import List

import sqlalchemy.orm

from roboToald.db import base

logger = logging.getLogger(__name__)


class Subscription(base.Base, base.MyBase):
    __tablename__ = "subscriptions"

    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    target = sqlalchemy.Column(sqlalchemy.String(255))
    last_notified = sqlalchemy.Column(sqlalchemy.Integer, default=0)
    lead_time = sqlalchemy.Column(sqlalchemy.Integer, default=1800, nullable=False)
    last_window_start = sqlalchemy.Column(sqlalchemy.Integer, default=0)

    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    __table_args__ = (sqlalchemy.PrimaryKeyConstraint("user_id", "target", "guild_id", name="pk_user_target_guild"),)

    def __init__(self, user_id, target, guild_id, lead_time, last_notified=0, last_window_start=0):
        self.user_id = user_id
        self.target = target
        self.last_notified = last_notified
        self.guild_id = guild_id
        self.lead_time = lead_time
        self.last_window_start = last_window_start


def get_subscription(user_id: int, target: str, guild_id: int) -> Subscription:
    with base.get_session() as session:
        sub = session.get(Subscription, {"user_id": user_id, "target": target, "guild_id": guild_id})
    return sub


def get_subscriptions() -> List[Subscription]:
    with base.get_session() as session:
        subs = session.query(Subscription).all()
    return subs


def get_subscriptions_for_user(user_id: int, guild_id: int = None) -> List[Subscription]:
    with base.get_session() as session:
        query = session.query(Subscription).filter_by(user_id=user_id)
        if guild_id is not None:
            query = query.filter_by(guild_id=guild_id)
        subs = query.order_by(Subscription.target).all()
    return subs


def get_subscriptions_for_notification() -> List[Subscription]:
    with base.get_session() as session:
        subs = session.query(Subscription).all()
    return subs


def mark_subscription_sent(user_id: int, target: str, guild_id: int, start_time: int) -> bool:
    with base.get_session() as session:
        sub: Subscription | None = session.get(
            Subscription, {"user_id": user_id, "target": target, "guild_id": guild_id}
        )
        if sub is None:
            return False
        sub.last_notified = int(time.time())
        sub.last_window_start = start_time
        session.add(sub)
        session.commit()
        return True


def delete_subscription(user_id: int, target: str, guild_id: int) -> bool:
    with base.get_session() as session:
        sub: Subscription | None = session.get(
            Subscription, {"user_id": user_id, "target": target, "guild_id": guild_id}
        )
        if sub is None:
            return False
        session.delete(sub)
        session.commit()
        return True
