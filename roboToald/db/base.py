import contextlib
import logging

import sqlalchemy
import sqlalchemy.event
import sqlalchemy.orm

from roboToald import exceptions

logger = logging.getLogger(__name__)

Base = sqlalchemy.orm.declarative_base()


class MyBase:
    __use_quota__ = False

    def store(self):
        with get_session() as session:
            if self.__use_quota__:
                num_objects = session.query(self.__class__).filter_by(user_id=self.user_id).count()
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
        engine = sqlalchemy.create_engine(
            "sqlite:///data/alerts.db",
            echo=False,
            future=True,
            connect_args={"timeout": 30},
        )
        sqlalchemy.event.listen(engine, "connect", _set_sqlite_pragmas)
        store["engine"] = engine
    return store["engine"]


def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def initialize_database(run_migrations=True):
    """Initialize the database and optionally run migrations.

    Detects three possible states:
    - Fresh DB (no tables): create_all() + stamp head
    - Pre-Alembic DB (app tables exist, no alembic_version): stamp head
    - Normal DB (alembic_version exists): upgrade head
    """
    engine = get_engine()

    if not run_migrations:
        Base.metadata.create_all(engine)
        return

    try:
        from roboToald.db.migrations import upgrade_database, stamp_database
    except ImportError:
        logger.info("Alembic not available — falling back to create_all().")
        Base.metadata.create_all(engine)
        return

    inspector = sqlalchemy.inspect(engine)
    table_names = inspector.get_table_names()
    has_alembic = "alembic_version" in table_names
    has_app_tables = "sso_account" in table_names

    if not has_app_tables:
        logger.info("Fresh database detected — creating tables and stamping head.")
        Base.metadata.create_all(engine)
        stamp_database()
    elif not has_alembic:
        logger.info("Pre-Alembic database detected — stamping head.")
        stamp_database()
    else:
        logger.info("Running Alembic migrations...")
        upgrade_database()

    logger.info("Database schema is up to date.")


@contextlib.contextmanager
def get_session(autocommit=False) -> sqlalchemy.orm.Session:
    with sqlalchemy.orm.Session(get_engine(), autocommit=autocommit) as SESSION:
        yield SESSION
