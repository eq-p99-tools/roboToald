import contextlib

import sqlalchemy
import sqlalchemy.orm

Base = sqlalchemy.orm.declarative_base()


# get_engine returns a Singleton engine object
def get_engine(store={}):
    if not store:
        store['engine'] = sqlalchemy.create_engine(
            "sqlite:///alerts.db", echo=False, future=True)
        Base.metadata.create_all(store['engine'])
    return store['engine']


@contextlib.contextmanager
def get_session(autocommit=False):
    with sqlalchemy.orm.Session(
            get_engine(), autocommit=autocommit) as SESSION:
        yield SESSION
