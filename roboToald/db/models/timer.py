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
