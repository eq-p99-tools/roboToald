import sqlalchemy.orm

from roboToald.db import base


class Alert(base.Base):
    __tablename__ = "alerts"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    channel_id = sqlalchemy.Column(sqlalchemy.Integer)
    user_id = sqlalchemy.Column(sqlalchemy.Integer)
    alert_regex = sqlalchemy.Column(sqlalchemy.String(255))
    alert_role = sqlalchemy.Column(sqlalchemy.Integer)
    alert_url = sqlalchemy.Column(sqlalchemy.String(100))

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


def get_alert(alert_id):
    with base.get_session() as session:
        alert = session.get(Alert, alert_id)
    return alert


def get_alerts():
    with base.get_session() as session:
        alerts = session.query(Alert).all()
    return alerts


def get_alerts_for_channel(channel):
    with base.get_session() as session:
        alerts = session.query(Alert).filter_by(channel_id=channel).all()
    return alerts


def get_alerts_for_user(user_id, guild_id=None):
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


def delete_alert(alert_id):
    with base.get_session() as session:
        alert = session.get(Alert, alert_id)
        if alert:
            session.delete(alert)
            session.commit()


if __name__ == "__main__":
    print(get_registered_channels())
