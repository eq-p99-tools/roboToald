import datetime
from typing import List, Tuple, Dict, Optional

import sqlalchemy
import sqlalchemy.orm

from roboToald import constants
from roboToald.db import base


class PointsAudit(base.Base):
    __tablename__ = "points_audit"

    id = sqlalchemy.Column(
        sqlalchemy.Integer, primary_key=True, autoincrement=True)
    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer)
    event = sqlalchemy.Column(sqlalchemy.Enum(constants.Event))
    time = sqlalchemy.Column(sqlalchemy.DateTime)
    active = sqlalchemy.Column(sqlalchemy.Boolean, default=True)
    start_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)

    def __init__(self, user_id: int, guild_id: int, event: constants.Event,
                 time: datetime.datetime, active: bool = True,
                 start_id: int = None):
        self.user_id = user_id
        self.guild_id = guild_id
        self.event = event
        self.time = time
        self.active = active
        self.start_id = start_id


def get_event(event_id: int) -> Optional[PointsAudit]:
    with base.get_session() as session:
        event = session.query(PointsAudit).filter_by(id=event_id).one_or_none()
    return event


def get_events_for_member(user_id: int, guild_id: int) -> list[PointsAudit]:
    with base.get_session() as session:
        events = session.query(PointsAudit).filter_by(
            user_id=user_id, guild_id=guild_id).all()
    return events


def get_last_event(user_id: int, guild_id: int) -> Optional[PointsAudit]:
    # Check for latest event for user+guild
    with base.get_session() as session:
        last_event = session.query(PointsAudit)
        last_event = last_event.filter_by(user_id=user_id, guild_id=guild_id)
        last_event = last_event.order_by(sqlalchemy.desc(PointsAudit.time))
        last_event = last_event.first()
    return last_event


def get_active_events(
        guild_id: int, include_0: bool = False) -> list[PointsAudit]:
    with base.get_session() as session:
        active_events = session.query(PointsAudit)
        active_events = active_events.filter_by(guild_id=guild_id, active=True)
        if not include_0:
            active_events = active_events.filter(PointsAudit.user_id != 0)
        active_events = active_events.all()
    return active_events


def get_events_since_time(
        guild_id: int, start_time: datetime.datetime) -> List[PointsAudit]:
    with base.get_session() as session:
        event_list = session.query(PointsAudit)
        event_list = event_list.filter_by(guild_id=guild_id)
        event_list = event_list.filter(PointsAudit.user_id != 0)
        event_list = event_list.filter(PointsAudit.time > start_time)
        event_list = event_list.all()
    return event_list


def get_event_pairs(events: List[PointsAudit]
                    ) -> Dict[datetime.datetime, datetime.datetime]:
    event_pairs: Dict[datetime.datetime, datetime.datetime] = {}
    for event in events:
        if event.time in event_pairs.keys() or event.time in event_pairs.values():
            continue
        if event.active:
            # Event with no pair means ongoing
            event_pairs[event.time] = datetime.datetime.max
            continue
        if event.start_id:
            matched_event = get_event(event.start_id)
            event_pairs[matched_event.time] = event.time
            continue
        else:
            with base.get_session() as session:
                matched_event = session.query(PointsAudit).filter_by(
                    start_id=event.id).one_or_none()
            event_pairs[event.time] = matched_event.time
            continue
    return event_pairs


def get_event_pairs_split_members(
        events: List[PointsAudit]
) -> Dict[int, Dict[datetime.datetime, datetime.datetime]]:
    event_pairs: Dict[int, Dict[datetime.datetime, datetime.datetime]] = {}
    now = datetime.datetime.now()
    for event in events:
        if event.user_id not in event_pairs:
            event_pairs[event.user_id] = {}
        if event.time in event_pairs.keys() or event.time in event_pairs.values():
            continue
        if event.active:
            # Event with no pair means ongoing (use now+10m to be safe)
            event_pairs[event.user_id][event.time] = (
                    now + datetime.timedelta(minutes=10)
            )
            continue
        if event.start_id:
            matched_event = get_event(event.start_id)
            event_pairs[event.user_id][matched_event.time] = event.time
            continue
        else:
            with base.get_session() as session:
                matched_event = session.query(PointsAudit).filter_by(
                    start_id=event.id).one_or_none()
            if matched_event:
                event_pairs[event.user_id][event.time] = matched_event.time
            else:
                event_pairs[event.user_id][event.time] = now
            continue
    return event_pairs


def get_last_pop_time() -> datetime.datetime:
    with base.get_session() as session:
        last_pop = session.query(PointsAudit).filter_by(
            event=constants.Event.POP
        ).order_by(sqlalchemy.desc(PointsAudit.time)).limit(1).one_or_none()
    if last_pop:
        return last_pop.time.astimezone()
    return (datetime.datetime.now() -
            datetime.timedelta(hours=18)).astimezone()


def get_event_pairs_since_last_pop(
        guild_id: int
) -> Dict[int, Dict[datetime.datetime, datetime.datetime]]:
    last_pop_time = get_last_pop_time()
    events = get_events_since_time(guild_id, last_pop_time)
    event_pairs = get_event_pairs_split_members(events)
    return event_pairs


def get_competitive_windows(
        guild_id: int, start_time: datetime.datetime,
        end_time: datetime.datetime
) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    with base.get_session() as session:
        # Get the windows that started or ended within our time period
        events_query = session.query(PointsAudit)
        events_query = events_query.filter_by(user_id=0, guild_id=guild_id)
        events_query = events_query.filter(PointsAudit.event != constants.Event.POP)
        events_query = events_query.filter(PointsAudit.time >= start_time)
        events_query = events_query.filter(PointsAudit.time <= end_time)
        active_events: List[PointsAudit] = events_query.all()
        # Add in the currently active window no matter when it started
        events_query = session.query(PointsAudit)
        events_query = events_query.filter_by(
            user_id=0, guild_id=guild_id, active=True)
        active_events.extend(events_query.all())

    event_pairs = get_event_pairs(active_events)

    windows = []
    for start, end in event_pairs.items():
        windows.append((start.astimezone(),
                        end.replace(tzinfo=start.astimezone().tzinfo)))

    return windows


def start_event(start: PointsAudit) -> None:
    with base.get_session() as session:
        session.add(start)
        session.commit()


def close_event(start: PointsAudit, end: PointsAudit) -> None:
    with base.get_session() as session:
        session.add(session.merge(start))
        session.add(end)
        session.commit()


def update_event(event: PointsAudit) -> None:
    with base.get_session() as session:
        session.add(session.merge(event))
        session.commit()


class PointsEarned(base.Base, base.MyBase):
    __use_quota__ = False
    __tablename__ = "points_earned"

    id = sqlalchemy.Column(
        sqlalchemy.Integer, primary_key=True, autoincrement=True)
    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer)
    points = sqlalchemy.Column(sqlalchemy.Integer)
    time = sqlalchemy.Column(sqlalchemy.DateTime)
    notes = sqlalchemy.Column(sqlalchemy.Text)
    adjustor = sqlalchemy.Column(sqlalchemy.Integer)

    def __init__(self, user_id: int, guild_id: int, points: int,
                 time: datetime.datetime, notes: str = None,
                 adjustor: int = None):
        self.user_id = user_id
        self.guild_id = guild_id
        self.points = points
        self.time = time
        self.notes = notes
        self.adjustor = adjustor


def get_points_earned(guild_id: int) -> List[sqlalchemy.engine.row.Row]:
    with base.get_session() as session:
        earned = session.query(
            PointsEarned.user_id,
            sqlalchemy.func.sum(PointsEarned.points).label('points')
        )
        earned = earned.group_by(PointsEarned.user_id)
        earned = earned.filter_by(guild_id=guild_id)
        earned = earned.filter(PointsEarned.user_id != 0)
        earned = earned.order_by(sqlalchemy.desc(PointsEarned.points))
        earned = earned.all()
    return earned


def get_points_earned_by_member(user_id: int, guild_id: int) -> list[PointsEarned]:
    with base.get_session() as session:
        earned = session.query(PointsEarned).filter_by(
            user_id=user_id, guild_id=guild_id).all()
    return earned


class PointsSpent(base.Base, base.MyBase):
    __use_quota__ = False
    __tablename__ = "points_spent"

    id = sqlalchemy.Column(
        sqlalchemy.Integer, primary_key=True, autoincrement=True)
    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer)
    points = sqlalchemy.Column(sqlalchemy.Integer)
    time = sqlalchemy.Column(sqlalchemy.DateTime)

    def __init__(self, user_id: int, guild_id: int, points: int,
                 time: datetime.datetime):
        self.user_id = user_id
        self.guild_id = guild_id
        self.points = points
        self.time = time


def get_points_spent(guild_id: int) -> list[PointsSpent]:
    with base.get_session() as session:
        spent = session.query(PointsSpent).filter_by(
            guild_id=guild_id).order_by(sqlalchemy.asc(PointsSpent.time)).all()
    return spent


def get_points_spent_by_member(user_id: int, guild_id: int) -> list[PointsSpent]:
    with base.get_session() as session:
        spent = session.query(PointsSpent).filter_by(
            user_id=user_id, guild_id=guild_id).all()
    return spent
