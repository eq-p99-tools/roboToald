"""Tests for Character.klass_name property."""

from roboToald.db.raid_models.character import Character


def test_klass_name_from_title():
    c = Character(name="Test", klass="Virtuoso")
    assert c.klass_name == "BRD"


def test_klass_name_from_class():
    c = Character(name="Test", klass="Warrior")
    assert c.klass_name == "WAR"


def test_klass_name_empty():
    c = Character(name="Test", klass=None)
    assert c.klass_name == ""


def test_klass_name_oracle():
    c = Character(name="Test", klass="Oracle")
    assert c.klass_name == "SHM"


def test_klass_name_arch_mage():
    c = Character(name="Test", klass="Arch Mage")
    assert c.klass_name == "MAG"
