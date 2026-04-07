"""Tests for pure helpers in ``cmd_ds_data`` (calendar layout)."""

from __future__ import annotations

from roboToald.discord_client.commands.cmd_ds_data import combine_months, mark_date, pad_month


def test_combine_months_single_column():
    months = ["A\n1", "B\n2"]
    out = combine_months(months, num_cols=1)
    assert len(out) == 2
    assert "A" in out[0] and "B" in out[1]


def test_combine_months_two_columns():
    months = ["A\n1", "B\n2", "C\n3", "D\n4"]
    out = combine_months(months, num_cols=2)
    assert len(out) == 2
    assert "A" in out[0] and "B" in out[0]
    assert "C" in out[1] and "D" in out[1]


def test_combine_months_three_columns():
    months = ["M1\nx", "M2\ny", "M3\nz"]
    out = combine_months(months, num_cols=3)
    assert len(out) == 1
    assert "M1" in out[0] and "M2" in out[0] and "M3" in out[0]


def test_pad_month_pads_short_lines():
    raw = "ab\nabcd\nab"
    padded = pad_month(raw)
    lines = padded.splitlines()
    assert len(lines[0]) == len(lines[1]) == len(lines[2])


def test_pad_month_already_uniform():
    raw = "xx\nxx"
    assert pad_month(raw) == raw


def test_mark_date_wraps_day_in_brackets():
    cal = "  5  6  7\n 12 13 14"
    out = mark_date(cal, 13)
    assert "[13]" in out
    assert " 12 " in out or " 12" in out
