import datetime
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
    expiry = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    last_notified = sqlalchemy.Column(sqlalchemy.Integer, default=0)
    lead_time = sqlalchemy.Column(sqlalchemy.Integer, default=1800, nullable=False)
    last_window_start = sqlalchemy.Column(sqlalchemy.Integer, default=0)

    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    __table_args__ = (sqlalchemy.PrimaryKeyConstraint("user_id", "target", "guild_id", name="pk_user_target_guild"),)

    def __init__(self, user_id, target, expiry, guild_id, lead_time, last_notified=0, last_window_start=0):
        self.user_id = user_id
        self.target = target
        self.expiry = expiry
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
        subs = query.order_by(Subscription.expiry).all()
    return subs


def get_subscriptions_for_notification() -> List[Subscription]:
    with base.get_session() as session:
        subs = session.query(Subscription).all()
    return subs


def mark_subscription_sent(user_id: int, target: str, guild_id: int, start_time: int) -> bool:
    with base.get_session() as session:
        sub: Subscription = session.get(Subscription, {"user_id": user_id, "target": target, "guild_id": guild_id})
    try:
        sub.last_notified = int(time.time())
        sub.last_window_start = start_time
        sub.store()
        return True
    except Exception:
        return False


def delete_subscription(user_id: int, target: str, guild_id: int) -> bool:
    with base.get_session() as session:
        sub: Subscription = session.get(Subscription, {"user_id": user_id, "target": target, "guild_id": guild_id})
    try:
        sub.delete()
        return True
    except Exception:
        return False


def refresh_subscription(user_id: int, target: str, guild_id: int) -> Subscription:
    with base.get_session() as session:
        sub: Subscription = session.get(Subscription, {"user_id": user_id, "target": target, "guild_id": guild_id})
    try:
        sub.expiry = int(time.time() + datetime.timedelta(days=30).total_seconds())
        sub.store()
        return sub
    except Exception:
        logger.exception(
            "Failed to refresh subscription user_id=%s target=%s guild_id=%s",
            user_id,
            target,
            guild_id,
        )


def clean_expired_subscriptions() -> None:
    with base.get_session() as session:
        expired = session.query(Subscription).filter(Subscription.expiry < time.time()).all()
        for sub in expired:
            sub.delete()
    if expired:
        logger.info("Cleaned up %s expired subscriptions.", len(expired))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    clean_expired_subscriptions()
