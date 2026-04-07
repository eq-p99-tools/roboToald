import sqlalchemy as sa

from roboToald.db.raid_base import RaidBase

CLASS_SHORT = {
    "Bard": "BRD",
    "Cleric": "CLR",
    "Druid": "DRU",
    "Enchanter": "ENC",
    "Magician": "MAG",
    "Monk": "MNK",
    "Necromancer": "NEC",
    "Paladin": "PAL",
    "Ranger": "RNG",
    "Rogue": "ROG",
    "Shadow Knight": "SHD",
    "Shaman": "SHM",
    "Warrior": "WAR",
    "Wizard": "WIZ",
    "": "",
}

TITLE_TO_CLASS = {
    "Minstrel": "Bard",
    "Troubadour": "Bard",
    "Virtuoso": "Bard",
    "Vicar": "Cleric",
    "Templar": "Cleric",
    "High Priest": "Cleric",
    "Wanderer": "Druid",
    "Preserver": "Druid",
    "Hierophant": "Druid",
    "Illusionist": "Enchanter",
    "Beguiler": "Enchanter",
    "Phantasmist": "Enchanter",
    "Elementalist": "Magician",
    "Conjurer": "Magician",
    "Arch Mage": "Magician",
    "Disciple": "Monk",
    "Master": "Monk",
    "Grandmaster": "Monk",
    "Heretic": "Necromancer",
    "Defiler": "Necromancer",
    "Warlock": "Necromancer",
    "Cavalier": "Paladin",
    "Knight": "Paladin",
    "Crusader": "Paladin",
    "Pathfinder": "Ranger",
    "Outrider": "Ranger",
    "Warder": "Ranger",
    "Rake": "Rogue",
    "Blackguard": "Rogue",
    "Assassin": "Rogue",
    "Reaver": "Shadow Knight",
    "Revenant": "Shadow Knight",
    "Grave Lord": "Shadow Knight",
    "Mystic": "Shaman",
    "Luminary": "Shaman",
    "Oracle": "Shaman",
    "Champion": "Warrior",
    "Myrmidon": "Warrior",
    "Warlord": "Warrior",
    "Channeler": "Wizard",
    "Evoker": "Wizard",
    "Sorcerer": "Wizard",
}


class Character(RaidBase):
    __tablename__ = "characters"

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)
    eqdkp_member_id = sa.Column(sa.Integer)
    eqdkp_main_id = sa.Column(sa.Text)
    eqdkp_user_id = sa.Column(sa.Text)
    klass = sa.Column(sa.Text)

    @property
    def klass_name(self) -> str:
        raw = str(self.klass) if self.klass else ""
        base_class = TITLE_TO_CLASS.get(raw, raw)
        return CLASS_SHORT.get(base_class, "")
