import contextlib

import sqlalchemy
import sqlalchemy.orm

from roboToald import config

RaidBase = sqlalchemy.orm.declarative_base()

_engines: dict[int, sqlalchemy.engine.Engine] = {}


def _db_path(guild_id: int) -> str:
    return config.get_raid_setting(guild_id, "database_path") or f"data/raids_{guild_id}.db"


def get_raid_engine(guild_id: int) -> sqlalchemy.engine.Engine:
    if guild_id not in _engines:
        _engines[guild_id] = sqlalchemy.create_engine(
            f"sqlite:///{_db_path(guild_id)}", echo=False, future=True,
        )
    return _engines[guild_id]


def initialize_raid_database(guild_id: int, run_migrations=True):
    """Initialize a guild's raid database and optionally run migrations.

    Detects three possible states:
    - Fresh DB (no tables): create_all() + stamp head
    - Pre-Alembic DB (app tables exist, no alembic_version): stamp head
    - Normal DB (alembic_version exists): upgrade head
    """
    engine = get_raid_engine(guild_id)

    if not run_migrations:
        RaidBase.metadata.create_all(engine)
        return

    try:
        from roboToald.db.raid_migrations import upgrade_raid_database, stamp_raid_database
    except ImportError:
        print("Alembic not available for raid DB — falling back to create_all().")
        RaidBase.metadata.create_all(engine)
        return

    db_path = _db_path(guild_id)

    inspector = sqlalchemy.inspect(engine)
    table_names = inspector.get_table_names()
    has_alembic = "raid_alembic_version" in table_names
    has_app_tables = "events" in table_names

    if not has_app_tables:
        print(f"Fresh raid database detected ({db_path}) — creating tables and stamping head.")
        RaidBase.metadata.create_all(engine)
        stamp_raid_database(db_path=db_path)
    elif not has_alembic:
        print(f"Pre-Alembic raid database detected ({db_path}) — stamping head.")
        stamp_raid_database(db_path=db_path)
    else:
        print(f"Running raid Alembic migrations ({db_path})...")
        upgrade_raid_database(db_path=db_path)

    print(f"Raid database schema is up to date ({db_path}).")


@contextlib.contextmanager
def get_raid_session(guild_id: int, autocommit=False) -> sqlalchemy.orm.Session:
    with sqlalchemy.orm.Session(get_raid_engine(guild_id), autocommit=autocommit) as session:
        yield session
