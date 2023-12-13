import datetime
import time
from typing import List

import sqlalchemy.orm

from roboToald.db import base


class Subscription(base.Base, base.MyBase):
    __tablename__ = "subscriptions"

    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    target = sqlalchemy.Column(sqlalchemy.String(255))
    expiry = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    last_notified = sqlalchemy.Column(sqlalchemy.Integer, default=0)
    lead_time = sqlalchemy.Column(sqlalchemy.Integer, default=1800,
                                  nullable=False)
    last_window_start = sqlalchemy.Column(sqlalchemy.Integer, default=0)

    # Cached for convenience
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    __table_args__ = (
        sqlalchemy.PrimaryKeyConstraint(
            'user_id', 'target', name='pk_user_id_target'),
    )

    def __init__(self, user_id, target, expiry, guild_id, lead_time,
                 last_notified=0, last_window_start=0):
        self.user_id = user_id
        self.target = target
        self.expiry = expiry
        self.last_notified = last_notified
        self.guild_id = guild_id
        self.lead_time = lead_time
        self.last_window_start = last_window_start


def get_subscription(user_id: int, target: str) -> Subscription:
    with base.get_session() as session:
        sub = session.get(Subscription, {"user_id": user_id, "target": target})
    return sub


def get_subscriptions() -> List[Subscription]:
    with base.get_session() as session:
        subs = session.query(Subscription).all()
    return subs


def get_subscriptions_for_user(user_id: int) -> List[Subscription]:
    with base.get_session() as session:
        subs = session.query(Subscription).filter_by(user_id=user_id)
        subs = subs.order_by(Subscription.expiry).all()
    return subs


def get_subscriptions_for_notification() -> List[Subscription]:
    with base.get_session() as session:
        subs = session.query(Subscription).all()
    return subs


def mark_subscription_sent(user_id: int, target: str, start_time: int) -> bool:
    with base.get_session() as session:
        sub: Subscription = session.get(
            Subscription, {"user_id": user_id, "target": target})
    try:
        sub.last_notified = int(time.time())
        sub.last_window_start = start_time
        sub.store()
        return True
    except:
        return False


def delete_subscription(user_id: int, target: str) -> bool:
    with base.get_session() as session:
        sub: Subscription = session.get(
            Subscription, {"user_id": user_id, "target": target})
    try:
        sub.delete()
        return True
    except:
        return False


def refresh_subscription(user_id: int, target: str) -> Subscription:
    with base.get_session() as session:
        sub: Subscription = session.get(
            Subscription, {"user_id": user_id, "target": target})
    try:
        sub.expiry = int(
            time.time() + datetime.timedelta(days=30).total_seconds())
        sub.store()
        return sub
    except:
        print(f"Failed to refresh subscription {user_id}/{target}.")


def clean_expired_subscriptions() -> None:
    with base.get_session() as session:
        expired = session.query(Subscription).filter(
            Subscription.expiry < time.time()).all()
        for sub in expired:
            sub.delete()
    if expired:
        print(f"Cleaned up {len(expired)} expired subscriptions.")


if __name__ == "__main__":
    print(clean_expired_subscriptions())
