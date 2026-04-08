"""Unit tests for pure helpers in ``roboToald.api.server``."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from starlette.requests import Request

from roboToald import config
from roboToald.api import server


def test_parse_version_release_vs_prerelease():
    assert server._parse_version("1.2.3") > server._parse_version("1.2.3-rc1")
    assert server._parse_version("2.0.0") > server._parse_version("1.9.9")


def test_parse_version_non_numeric_segment():
    assert server._parse_version("1.x.3") == (1, 0, 3, 1)


def test_get_client_ip_forwarded_for():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.1, 10.0.0.1")],
        "client": ("127.0.0.1", 12345),
    }
    req = Request(scope)
    assert server._get_client_ip(req) == "203.0.113.1"


def test_get_client_ip_fallback():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("198.51.100.2", 443),
    }
    req = Request(scope)
    assert server._get_client_ip(req) == "198.51.100.2"


def test_validate_client_settings_missing_ok():
    assert server._validate_client_settings(None, guild_id=1) is None


def test_validate_client_settings_require_log(monkeypatch):
    gid = 90001
    monkeypatch.setitem(config.GUILD_SETTINGS, gid, {"require_log": True})
    err = server._validate_client_settings({"log_enabled": False}, guild_id=gid)
    assert err is not None
    assert "Log" in err


def test_validate_client_settings_block_rustle(monkeypatch):
    gid = 90002
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        gid,
        {"block_rustle": True, "block_rustle_exempt_roles": [10, 20]},
    )
    err = server._validate_client_settings({"rustle_present": True}, guild_id=gid, user_role_ids=[99])
    assert err is not None


def test_validate_client_settings_rustle_exempt(monkeypatch):
    gid = 90003
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        gid,
        {"block_rustle": True, "block_rustle_exempt_roles": [10, 20]},
    )
    assert server._validate_client_settings({"rustle_present": True}, guild_id=gid, user_role_ids=[10]) is None


def test_parse_eq_log_time():
    s = "Fri Mar 06 11:13:03 2026"
    dt = server._parse_eq_log_time(s)
    assert dt == datetime.datetime(2026, 3, 6, 11, 13, 3)


def test_parse_eq_log_time_invalid():
    assert server._parse_eq_log_time("not a date") is None


def test_combine_est_now_with_log_minute_second_preserves_est_clock():
    """ToD/FTE use Eastern now + log min:sec; log hour/date are ignored."""
    est = ZoneInfo("America/New_York")
    now_est = datetime.datetime(2026, 6, 15, 22, 30, 15, tzinfo=est)
    parsed_naive = datetime.datetime(2020, 1, 1, 3, 17, 45)
    combined = server._combine_est_now_with_log_minute_second(now_est, parsed_naive)
    assert combined == datetime.datetime(2026, 6, 15, 22, 17, 45, tzinfo=est)


def test_combine_est_now_with_log_minute_second_timestamp_independent_of_host_tz():
    """Aware Eastern instant: .timestamp() does not depend on process default TZ."""
    est = ZoneInfo("America/New_York")
    now_est = datetime.datetime(2026, 1, 10, 14, 0, 0, tzinfo=est)
    parsed_naive = datetime.datetime(1999, 7, 4, 23, 5, 9)
    combined = server._combine_est_now_with_log_minute_second(now_est, parsed_naive)
    expected = datetime.datetime(2026, 1, 10, 14, 5, 9, tzinfo=est)
    assert combined == expected
    assert int(combined.timestamp()) == int(expected.timestamp())


@freeze_time("2026-03-06T11:13:03")
def test_verify_eq_log_time_skew_accepts_matching_minute_second():
    eq_time = "Fri Mar 06 11:13:03 2026"
    assert server._verify_eq_log_time_skew(eq_time, "test_evt", 1) is not None


@freeze_time("2026-03-08T11:13:03")
def test_verify_eq_log_time_skew_rejects_over_24h_calendar():
    eq_time = "Fri Mar 06 11:13:03 2026"
    assert server._verify_eq_log_time_skew(eq_time, "test_evt", 1) is None


def test_des_encrypt_credentials_length_and_padding():
    out = server._des_encrypt_credentials("user", "pass")
    assert len(out) % 8 == 0
    assert len(out) >= 8


def test_des_encrypt_credentials_deterministic():
    a = server._des_encrypt_credentials("a", "b")
    b = server._des_encrypt_credentials("a", "b")
    assert a == b


def test_tod_dedup_suppresses_duplicate(monkeypatch):
    monkeypatch.setattr(server, "TOD_DEDUP_SECONDS", 60)
    server._tod_recent.clear()
    assert server._tod_dedup(1, "death", "Dragon") is False
    assert server._tod_dedup(1, "death", "Dragon") is True
    server._tod_recent.clear()


def test_tod_dedup_different_mob(monkeypatch):
    monkeypatch.setattr(server, "TOD_DEDUP_SECONDS", 60)
    server._tod_recent.clear()
    assert server._tod_dedup(1, "death", "A") is False
    assert server._tod_dedup(1, "death", "B") is False
    server._tod_recent.clear()


def test_session_context_log():
    s = server._session_context_log("g1", "u1", "1.0.0", "10.0.0.1")
    assert "g1" in s and "u1" in s and "1.0.0" in s and "10.0.0.1" in s
