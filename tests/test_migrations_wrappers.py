"""Basic tests for Alembic wrapper modules (config wiring, not full migration runs)."""

from __future__ import annotations

from pathlib import Path

from roboToald.db import migrations as app_migrations
from roboToald.db import raid_migrations


def test_package_root_points_at_roboToald_package():
    root = app_migrations._package_root()
    assert (root / "alembic.ini").is_file()
    assert (root / "migrations").is_dir()


def test_get_alembic_config_sets_script_location():
    cfg = app_migrations.get_alembic_config()
    script = cfg.get_main_option("script_location")
    assert script is not None
    assert Path(script).name == "migrations"


def test_upgrade_database_invokes_alembic_upgrade(monkeypatch):
    called = []

    def fake_upgrade(cfg, rev):
        called.append((cfg.get_main_option("script_location"), rev))

    monkeypatch.setattr(app_migrations.command, "upgrade", fake_upgrade)
    app_migrations.upgrade_database()
    assert called and called[0][1] == "head"


def test_get_raid_alembic_config_sqlite_url(tmp_path):
    db = tmp_path / "raid.db"
    cfg = raid_migrations.get_raid_alembic_config(str(db))
    assert cfg.get_main_option("sqlalchemy.url") == f"sqlite:///{db}"
    assert Path(cfg.get_main_option("script_location")).name == "raid_migrations"


def test_upgrade_raid_database_invokes_upgrade(monkeypatch, tmp_path):
    db = tmp_path / "r.db"
    called = []

    def fake_upgrade(cfg, rev):
        called.append((cfg.get_main_option("sqlalchemy.url"), rev))

    monkeypatch.setattr(raid_migrations.command, "upgrade", fake_upgrade)
    raid_migrations.upgrade_raid_database(str(db))
    assert called[0][0] == f"sqlite:///{db}"
    assert called[0][1] == "head"
