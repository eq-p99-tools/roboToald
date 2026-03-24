"""Tests for DKP calculator. Port of Ruby target_spec.rb / TrackingDkpCalculator."""

from roboToald.raid.dkp_calculator import dkp_from_duration


def test_26_hours():
    """1 day 2 hours at default rate of 4 per hour = 104 DKP."""
    duration = 26 * 3600
    assert dkp_from_duration(4, duration) == 104


def test_4_hours():
    """4 hours at rate 4 = 16 DKP."""
    assert dkp_from_duration(4, 4 * 3600) == 16


def test_3_hours_15_minutes():
    """3h15m at rate 4 = 13 DKP."""
    assert dkp_from_duration(4, 3 * 3600 + 15 * 60) == 13


def test_4_hours_15_minutes():
    """4h15m at rate 4 = 17 DKP."""
    assert dkp_from_duration(4, 4 * 3600 + 15 * 60) == 17


def test_4_hours_30_minutes():
    """4h30m at rate 4 = 18 DKP."""
    assert dkp_from_duration(4, 4 * 3600 + 30 * 60) == 18


def test_4_hours_45_minutes():
    """4h45m at rate 4 = 19 DKP."""
    assert dkp_from_duration(4, 4 * 3600 + 45 * 60) == 19


def test_zero_duration():
    assert dkp_from_duration(4, 0) == 0


def test_negative_duration():
    assert dkp_from_duration(4, -100) == 0


def test_sub_hour():
    """30 minutes at rate 6 = 3 DKP."""
    assert dkp_from_duration(6, 30 * 60) == 3


def test_exactly_one_hour():
    assert dkp_from_duration(10, 3600) == 10
