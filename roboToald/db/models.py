from typing import List

import sqlalchemy.orm

from roboToald.db import base


class Timer(base.Base, base.MyBase):
    __use_quota__ = True
    __tablename__ = "timers"

    id = sqlalchemy.Column(sqlalchemy.String(8), primary_key=True)
    channel_id = sqlalchemy.Column(sqlalchemy.Integer)
    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    name = sqlalchemy.Column(sqlalchemy.String(100))
    seconds = sqlalchemy.Column(sqlalchemy.Integer)
    first_run = sqlalchemy.Column(sqlalchemy.Integer)
    next_run = sqlalchemy.Column(sqlalchemy.Integer)
    repeating = sqlalchemy.Column(sqlalchemy.Boolean)

    # Cached for convenience
    guild_id = sqlalchemy.Column(sqlalchemy.Integer)

    def __init__(self, timer_id: str, channel_id: int, user_id: int, name: str,
                 seconds: int, first_run: int, next_run: int, guild_id: int,
                 repeating: bool):
        self.id = timer_id
        self.channel_id = channel_id
        self.user_id = user_id
        self.name = name
        self.seconds = seconds
        self.first_run = first_run
        self.next_run = next_run
        self.guild_id = guild_id
        self.repeating = repeating


def get_timer(timer_id: str) -> Timer:
    with base.get_session() as session:
        timer = session.get(Timer, timer_id)
    return timer


def get_timers() -> List[Timer]:
    with base.get_session() as session:
        timers = session.query(Timer).all()
    return timers


def get_timers_for_channel(channel: int) -> List[Timer]:
    with base.get_session() as session:
        timers = session.query(Timer).filter_by(channel_id=channel).all()
    return timers


def get_timers_for_user(user_id: int, guild_id=None) -> List[Timer]:
    with base.get_session() as session:
        timers = session.query(Timer).filter_by(user_id=user_id)
        if guild_id:
            timers = timers.filter_by(guild_id=guild_id)
        timers = timers.order_by(Timer.channel_id).all()
    return timers


class Alert(base.Base, base.MyBase):
    __tablename__ = "alerts"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    channel_id = sqlalchemy.Column(sqlalchemy.Integer)
    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    alert_regex = sqlalchemy.Column(sqlalchemy.String(255))
    alert_role = sqlalchemy.Column(sqlalchemy.Integer)
    alert_url = sqlalchemy.Column(sqlalchemy.String(100))
    trigger_count = sqlalchemy.Column(sqlalchemy.Integer)

    # Cached for convenience
    guild_id = sqlalchemy.Column(sqlalchemy.Integer)

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'user_id', 'channel_id', 'alert_regex', 'alert_url', name='uc1'),
    )

    def __init__(self, channel_id, user_id, alert_regex, alert_url,
                 guild_id, alert_role):
        self.channel_id = channel_id
        self.user_id = user_id
        self.alert_regex = alert_regex
        self.alert_role = alert_role
        self.alert_url = alert_url
        self.guild_id = guild_id
        self.trigger_count = 0

    def increment_counter(self):
        # This isn't strictly speaking an atomic action, but
        # honestly it doesn't matter. I don't care enough to deal
        # with transactions, since they don't work right in
        # sqlite anyway.
        self.trigger_count += 1
        self.store()

    def reset_counter(self):
        self.trigger_count = 0
        self.store()


def get_alert(alert_id: int) -> Alert:
    with base.get_session() as session:
        alert = session.get(Alert, alert_id)
    return alert


def get_alerts() -> List[Alert]:
    with base.get_session() as session:
        alerts = session.query(Alert).all()
    return alerts


def get_alerts_for_channel(channel: int) -> List[Alert]:
    with base.get_session() as session:
        alerts = session.query(Alert).filter_by(channel_id=channel).all()
    return alerts


def get_alerts_for_user(user_id: int, guild_id: int = None) -> List[Alert]:
    with base.get_session() as session:
        alerts = session.query(Alert).filter_by(user_id=user_id)
        if guild_id:
            alerts = alerts.filter_by(guild_id=guild_id)
        alerts = alerts.order_by(Alert.channel_id).all()
    return alerts


def get_registered_channels():
    with base.get_session() as session:
        result = session.execute(
            sqlalchemy.select(Alert.channel_id)
        )
        channels = set()
        for row in result:
            channels.add(row[0])
    return channels


if __name__ == "__main__":
    print(get_registered_channels())
