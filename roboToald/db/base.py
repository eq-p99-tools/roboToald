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


def initialize_database(run_migrations=True):
    """Initialize the database and optionally run migrations.
    
    This function should be called during application startup to ensure
    the database schema is properly set up and up to date.
    """
    # Create tables if they don't exist
    get_engine()
    print("Database tables created if they didn't exist")
    
    # Run migrations if requested
    if run_migrations:
        try:
            # Import here to avoid circular imports
            from roboToald.db.migrations import upgrade_database
            upgrade_database()
        except ImportError as e:
            print("Alembic migrations not available. Skipping schema migrations.")
        except Exception as e:
            print(f"Error running database migrations: {e}")


@contextlib.contextmanager
def get_session(autocommit=False) -> sqlalchemy.orm.Session:
    with sqlalchemy.orm.Session(
            get_engine(), autocommit=autocommit) as SESSION:
        yield SESSION
