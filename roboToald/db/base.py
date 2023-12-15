import contextlib

import sqlalchemy
import sqlalchemy.orm

from roboToald import exceptions

Base = sqlalchemy.orm.declarative_base()


class MyBase:
    __use_quota__ = False

    def store(self):
        with get_session() as session:
            if self.__use_quota__:
                num_objects = session.query(
                    self.__class__).filter_by(user_id=self.user_id).count()
                if num_objects > 5:
                    raise exceptions.QuotaExceeded()
            local_object = session.merge(self)
            session.add(local_object)
            session.commit()

    def delete(self) -> None:
        with get_session() as session:
            local_object = session.merge(self)
            session.delete(local_object)
            session.commit()


# get_engine returns a Singleton engine object
def get_engine(store={}) -> sqlalchemy.engine.Engine:
    if not store:
        store['engine'] = sqlalchemy.create_engine(
            "sqlite:///alerts.db", echo=False, future=True)
        Base.metadata.create_all(store['engine'])
    return store['engine']


@contextlib.contextmanager
def get_session(autocommit=False) -> sqlalchemy.orm.Session:
    with sqlalchemy.orm.Session(
            get_engine(), autocommit=autocommit) as SESSION:
        yield SESSION
