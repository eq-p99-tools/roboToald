import base64
import datetime
import hashlib
import itertools
import logging
import secrets

import sqlalchemy
import sqlalchemy.exc
from sqlalchemy import func as sqlalchemy_func
import sqlalchemy.orm
import sqlalchemy_utils
import enum

from roboToald import config
from roboToald.db import base
from roboToald import words

_log = logging.getLogger(__name__)

try:
    from geoip2fast import GeoIP2Fast

    _geoip = GeoIP2Fast()
except Exception:
    _geoip = None
    _log.warning("geoip2fast unavailable – IP country flags will be disabled")


def hash_ip(ip_address: str, length: int = 14) -> str:
    """One-way hash an IP address for safe display. Truncated SHA-256 in URL-safe Base64."""
    hash_bytes = hashlib.sha256(ip_address.encode("utf-8")).digest()
    hash_b64 = base64.urlsafe_b64encode(hash_bytes).decode("utf-8")
    return hash_b64[:length]


def ip_country_code(ip_address: str) -> str:
    """Return a lowercase 2-letter country code, ``"private"``, ``"unknown"``, or ``""``."""
    if _geoip is None:
        return ""
    try:
        result = _geoip.lookup(ip_address)
        if result.is_private:
            return "private"
        cc = result.country_code
        if cc and len(cc) == 2 and cc.isalpha():
            return cc.lower()
    except Exception:
        pass
    return "unknown"


def ip_country_flag(ip_address: str) -> str:
    """Return a flag emoji for the IP's country, lock for private, or ? for unknown."""
    cc = ip_country_code(ip_address)
    if cc == "private":
        return "\U0001f512"
    if cc == "unknown" or not cc:
        return "\u2753"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in cc.upper())


class CachedEncryptedType(sqlalchemy_utils.EncryptedType):
    cache_ok = True


# Custom exceptions for different entity types
class SSOEntityNotFoundError(sqlalchemy.exc.NoResultFound):
    """Base exception for SSO entities not found"""

    pass


class SSOAccountNotFoundError(SSOEntityNotFoundError):
    """Raised when an SSOAccount is not found"""

    pass


class SSOAccountGroupNotFoundError(SSOEntityNotFoundError):
    """Raised when an SSOAccountGroup is not found"""

    pass


class SSOAccountTagNotFoundError(SSOEntityNotFoundError):
    """Raised when an SSOAccountTag is not found"""

    pass


class SSOAccountAliasNotFoundError(SSOEntityNotFoundError):
    """Raised when an SSOAccountAlias is not found"""

    pass


class SSOAccessKeyNotFoundError(SSOEntityNotFoundError):  # unused?
    """Raised when an SSOAccessKey is not found"""

    pass


class SSORevocationNotFoundError(SSOEntityNotFoundError):  # unused?
    """Raised when an SSORevocation is not found"""

    pass


class SSOCharacterAlreadyExistsError(Exception):
    """Raised when an SSOCharacter already exists"""

    pass


class SSOTagTemporarilyEmptyError(Exception):
    """Raised when an SSOAccountTag is temporarily empty due to activity"""

    pass


class CharacterClass(enum.Enum):
    Bard = "Bard"
    Cleric = "Cleric"
    Druid = "Druid"
    Enchanter = "Enchanter"
    Magician = "Magician"
    Monk = "Monk"
    Necromancer = "Necromancer"
    Paladin = "Paladin"
    Ranger = "Ranger"
    Rogue = "Rogue"
    ShadowKnight = "ShadowKnight"
    Shaman = "Shaman"
    Warrior = "Warrior"
    Wizard = "Wizard"


account_group_mapping = sqlalchemy.Table(
    "sso_account_group_mapping",
    base.Base.metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("account_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id")),
    sqlalchemy.Column("group_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account_group.id")),
    sqlalchemy.UniqueConstraint("account_id", "group_id", name="uq_account_id_group_id"),
)


class SSOAccount(base.Base):
    """Each entry in SSOAccounts represents an EQ bot account.

    Accounts can be members of multiple groups.
    """

    __tablename__ = "sso_account"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    real_user = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    real_pass = sqlalchemy.Column(CachedEncryptedType(sqlalchemy.String(255), config.ENCRYPTION_KEY), nullable=False)

    last_login = sqlalchemy.Column(sqlalchemy.DateTime, default=datetime.datetime.min)
    last_login_by = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)

    groups = sqlalchemy.orm.relationship("SSOAccountGroup", secondary=account_group_mapping, back_populates="accounts")
    audit_logs = sqlalchemy.orm.relationship("SSOAuditLog", back_populates="account")
    tags = sqlalchemy.orm.relationship("SSOTag", back_populates="account", cascade="all, delete-orphan")
    aliases = sqlalchemy.orm.relationship("SSOAccountAlias", back_populates="account", cascade="all, delete-orphan")
    characters = sqlalchemy.orm.relationship(
        "SSOAccountCharacter", back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (sqlalchemy.UniqueConstraint("guild_id", "real_user", name="uq_guild_id_real_user"),)

    def __init__(self, guild_id, real_user, real_pass, last_login=None):
        self.guild_id = guild_id
        self.real_user = real_user.lower()
        self.real_pass = real_pass
        self.last_login = last_login or datetime.datetime.min


def create_account(guild_id: int, real_user: str, real_pass: str, group: str = None) -> SSOAccount:
    real_user = real_user.lower()
    with base.get_session() as session:
        account = SSOAccount(guild_id=guild_id, real_user=real_user, real_pass=real_pass)
        if group:
            account.groups.append(get_account_group(guild_id, group))
        session.add(account)
        session.commit()
        account = (
            session.query(SSOAccount)
            .options(
                sqlalchemy.orm.joinedload(SSOAccount.groups),
                sqlalchemy.orm.joinedload(SSOAccount.tags),
                sqlalchemy.orm.joinedload(SSOAccount.aliases),
            )
            .filter(SSOAccount.id == account.id)
            .one()
        )

        session.expunge_all()
    return account


def get_account(guild_id: int, real_user: str) -> SSOAccount:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .options(
                    sqlalchemy.orm.joinedload(SSOAccount.groups),
                    sqlalchemy.orm.joinedload(SSOAccount.characters),
                    sqlalchemy.orm.joinedload(SSOAccount.tags),
                    sqlalchemy.orm.joinedload(SSOAccount.aliases),
                )
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
            session.expunge(account)
            return account
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")


def get_account_by_id(account_id: int) -> SSOAccount:
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .options(
                    sqlalchemy.orm.joinedload(SSOAccount.groups),
                    sqlalchemy.orm.joinedload(SSOAccount.characters),
                    sqlalchemy.orm.joinedload(SSOAccount.tags),
                    sqlalchemy.orm.joinedload(SSOAccount.aliases),
                )
                .filter(SSOAccount.id == account_id)
                .one()
            )
            session.expunge(account)
            return account
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{account_id}' not found")


def _max_character_level(account: "SSOAccount") -> int:
    """Return the highest level among an account's characters (0 if unset)."""
    return max((c.level or 0 for c in account.characters), default=0)


def _login_sort_key(account: "SSOAccount", now: datetime.datetime, level_fn) -> tuple:
    """Sort key for tag-based account selection.

    Buckets last_login so that level acts as a meaningful tiebreaker:
      - < 20 min ago: 30-second buckets (higher bucket = older = preferred)
      - >= 20 min ago: all equivalent (bucket 0)
    Within a bucket, higher level wins.
    """
    age = (now - account.last_login).total_seconds()
    if age >= 1200:
        bucket = 0
    else:
        bucket = int(age // 30)
    return (-bucket, -(level_fn(account)))


def _account_eager_opts():
    return (
        sqlalchemy.orm.joinedload(SSOAccount.groups),
        sqlalchemy.orm.joinedload(SSOAccount.tags),
        sqlalchemy.orm.joinedload(SSOAccount.characters),
        sqlalchemy.orm.joinedload(SSOAccount.aliases),
    )


def find_account_by_username(username: str, guild_id: int = None, inactive_only: bool = False) -> SSOAccount or None:
    """Find an account by username, trying resolution in priority order:
    account name > character > alias > tag > dynamic tag."""
    username = username.lower()
    with base.get_session() as session:
        # Try to find the account directly by real_user
        account = (
            session.query(SSOAccount)
            .options(*_account_eager_opts())
            .filter(SSOAccount.real_user == username, SSOAccount.guild_id == guild_id)
            .one_or_none()
        )

        if account:
            session.expunge(account)
            return account

        # Try by character name (single query via join)
        account = (
            session.query(SSOAccount)
            .join(SSOAccountCharacter, SSOAccountCharacter.account_id == SSOAccount.id)
            .options(*_account_eager_opts())
            .filter(
                sqlalchemy_func.lower(SSOAccountCharacter.name) == username,
                SSOAccountCharacter.guild_id == guild_id,
            )
            .first()
        )

        if account:
            session.expunge(account)
            return account

        # Try by alias (single query via join)
        account = (
            session.query(SSOAccount)
            .join(SSOAccountAlias, SSOAccountAlias.account_id == SSOAccount.id)
            .options(*_account_eager_opts())
            .filter(SSOAccountAlias.alias == username, SSOAccountAlias.guild_id == guild_id)
            .first()
        )

        if account:
            session.expunge(account)
            return account

        # Try by traditional tag (single query, sort in Python)
        accounts = (
            session.query(SSOAccount)
            .join(SSOTag, SSOTag.account_id == SSOAccount.id)
            .options(*_account_eager_opts())
            .filter(SSOTag.tag == username, SSOTag.guild_id == guild_id)
            .all()
        )

        if accounts:
            now = datetime.datetime.now()
            if inactive_only:
                inactivity_time = now - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
                accounts = [a for a in accounts if a.last_login < inactivity_time]
            if not accounts:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")
            accounts.sort(key=lambda a: _login_sort_key(a, now, _max_character_level))
            session.expunge(accounts[0])
            return accounts[0]

        # Try by dynamic tag
        dt_zones, dt_classes = _dynamic_tags
        dt_list = _dynamic_tag_list
        if username in dt_list:
            zone_matches = [(z, lst) for z, lst in dt_zones.items() if username.startswith(z)]
            zone_matches.sort(key=lambda x: len(x[0]), reverse=True)
            class_matches = [(c, v) for c, v in dt_classes.items() if username.endswith(c)]
            class_matches.sort(key=lambda x: len(x[0]), reverse=True)
            zones = zone_matches[0][1] if zone_matches else None
            dt_zone_prefix = zone_matches[0][0] if zone_matches else None
            klass = class_matches[0][1] if class_matches else None
            if not zones or not klass:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")

            required_key_column = None
            if config.REQUIRE_KEYS_FOR_DYNAMIC_TAGS and dt_zone_prefix:
                required_key_column = DYNAMIC_TAG_KEY_REQUIREMENTS.get(dt_zone_prefix)

            characters = list_account_characters_by_class_zone(
                guild_id, klass, zones, required_key_column=required_key_column
            )
            if not characters:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")
            char_level_by_account = {c.account_id: (c.level or 0) for c in characters}
            unique_accounts = list({c.account for c in characters})
            now = datetime.datetime.now()
            unique_accounts.sort(
                key=lambda a: _login_sort_key(a, now, lambda acct: char_level_by_account.get(acct.id, 0))
            )
            if not unique_accounts:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")
            # Re-query with full eager loads (the accounts from
            # list_account_characters_by_class_zone only have the
            # account relationship, not groups/tags/characters/aliases)
            account = (
                session.query(SSOAccount)
                .options(*_account_eager_opts())
                .filter(SSOAccount.id == unique_accounts[0].id)
                .one()
            )
            session.expunge(account)
            return account


def list_accounts(guild_id: int, group: str = None, tag: str = None) -> list[SSOAccount]:
    with base.get_session() as session:
        query = session.query(SSOAccount).filter(SSOAccount.guild_id == guild_id)
        if group:
            query = query.join(SSOAccount.groups).filter(SSOAccountGroup.group_name == group)
        if tag:
            query = query.join(SSOAccount.tags).filter(SSOTag.tag == tag)
        query = query.options(
            sqlalchemy.orm.joinedload(SSOAccount.groups),
            sqlalchemy.orm.joinedload(SSOAccount.characters),
            sqlalchemy.orm.joinedload(SSOAccount.tags),
            sqlalchemy.orm.joinedload(SSOAccount.aliases),
        )
        accounts = query.all()
        session.expunge_all()
    return accounts


def get_dynamic_tags() -> (dict[str, list[str]], dict[str, CharacterClass]):
    # dynamic_tag_zones = {
    #     "vp": ["Veeshan's Peak", "Skyfire Mountains"],
    #     "st": ["Sleepers Tomb", "Eastern Wastelands"],
    #     "tov": ["Temple of Veeshan", "Western Wastes"],
    #     "dn": ["Dragon Necropolis", "Western Wastes"],
    #     "kael": ["Kael Drakkel", "The Wakening Lands"],
    #     "pog": ["Plane of Growth", "The Wakening Lands"],
    #     "thurg": ["City of Thurgadin", "Icewell Keep"],
    #     "ss": ["Skyshrine"],
    #     "fear": ["Plane of Fear", "The Feerrott"]
    # }
    dynamic_tag_zones = {
        "seb": ["sebilis", "trakanon"],
        "vp": ["veeshan", "skyfire"],
        "st": ["sleeper", "eastwastes"],
        "tov": ["templeveeshan", "westwastes"],
        "dn": ["necropolis", "westwastes"],
        "kael": ["kael", "wakening"],
        "pog": ["growthplane", "wakening"],
        "thurg": ["thurgadina", "thurgadinb"],
        "ss": ["skyshrine"],
        "fear": ["fearplane", "feerrott"],
        "vox": ["everfrost", "permafrost"],
        "naggy": ["lavastorm", "soldungb"],
    }
    dynamic_tag_zones.update(
        {
            "dain": dynamic_tag_zones["thurg"],
            "yeli": dynamic_tag_zones["ss"],
            "zlandi": dynamic_tag_zones["dn"],
            "trak": dynamic_tag_zones["seb"],
        }
    )

    dynamic_tag_classes = {
        "bar": CharacterClass.Bard,
        "brd": CharacterClass.Bard,
        "bard": CharacterClass.Bard,
        "clr": CharacterClass.Cleric,
        "cle": CharacterClass.Cleric,
        "cleric": CharacterClass.Cleric,
        "dru": CharacterClass.Druid,
        "druid": CharacterClass.Druid,
        "enc": CharacterClass.Enchanter,
        "enchanter": CharacterClass.Enchanter,
        "mag": CharacterClass.Magician,
        "mage": CharacterClass.Magician,
        "magician": CharacterClass.Magician,
        "mnk": CharacterClass.Monk,
        "mon": CharacterClass.Monk,
        "monk": CharacterClass.Monk,
        "nec": CharacterClass.Necromancer,
        "necro": CharacterClass.Necromancer,
        "necromancer": CharacterClass.Necromancer,
        "pal": CharacterClass.Paladin,
        "pld": CharacterClass.Paladin,
        "paladin": CharacterClass.Paladin,
        "ran": CharacterClass.Ranger,
        "rng": CharacterClass.Ranger,
        "ranger": CharacterClass.Ranger,
        "rog": CharacterClass.Rogue,
        "rogue": CharacterClass.Rogue,
        "sk": CharacterClass.ShadowKnight,
        "shadowknight": CharacterClass.ShadowKnight,
        "sha": CharacterClass.Shaman,
        "shm": CharacterClass.Shaman,
        "sham": CharacterClass.Shaman,
        "shaman": CharacterClass.Shaman,
        "war": CharacterClass.Warrior,
        "warrior": CharacterClass.Warrior,
        "wiz": CharacterClass.Wizard,
        "wizard": CharacterClass.Wizard,
    }
    return dynamic_tag_zones, dynamic_tag_classes


# Pre-compute once at module load since these are static
_dynamic_tags = get_dynamic_tags()
_dynamic_tag_list = frozenset(
    "{}{}".format(a, b) for a, b in itertools.product(list(_dynamic_tags[0]), list(_dynamic_tags[1]))
)

# When require_keys_for_dynamic_tags is enabled, dynamic tag resolution requires these columns True.
DYNAMIC_TAG_KEY_REQUIREMENTS: dict[str, str] = {
    "seb": "key_seb",
    "trak": "key_seb",
    "vp": "key_vp",
    "st": "key_st",
}

# Park zone key from client -> SSOAccountCharacter column name; auto-set True on zone entry.
KEY_ZONE_TO_COLUMN: dict[str, str] = {
    "sebilis": "key_seb",
    "veeshan": "key_vp",
    "sleeper": "key_st",
}

# WebSocket ``items`` / legacy ``keys`` short wire name -> SSOAccountCharacter boolean column.
WIRE_KEY_TO_ATTR: dict[str, str] = {
    "seb": "key_seb",
    "vp": "key_vp",
    "st": "key_st",
    "void": "item_void",
    "neck": "item_neck",
    "lizard": "item_lizard",
    "thurg": "item_thurg",
}


def merge_keys_and_items_message(msg: dict) -> dict:
    """Merge ``keys`` and ``items`` from an ``update_location`` payload; ``items`` wins on conflicts."""
    raw_keys = msg.get("keys")
    raw_items = msg.get("items")
    keys = raw_keys if isinstance(raw_keys, dict) else {}
    items = raw_items if isinstance(raw_items, dict) else {}
    return {**keys, **items}


def merged_wires_to_character_kwargs(merged: dict) -> dict:
    """Map merged wire dict to keyword names accepted by :func:`update_account_character`."""
    kw = {}
    for wire, attr in WIRE_KEY_TO_ATTR.items():
        if wire in merged:
            kw[attr] = merged[wire]
    return kw


def get_dynamic_tag_list():
    return _dynamic_tag_list


def update_account(guild_id: int, real_user: str, password: str) -> SSOAccount:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
            account.real_pass = password
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
        session.expunge(account)
    return account


def update_last_login(account_id: int, login_by: str | None = None) -> None:
    """Update the last_login timestamp (and optionally who logged in) for an account."""
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(SSOAccount.id == account_id).one_or_none()
        if account:
            account.last_login = datetime.datetime.now()
            if login_by is not None:
                account.last_login_by = login_by
            session.commit()


def update_last_login_and_log(
    account_id: int,
    login_by: str | None,
    username: str,
    ip_address: str,
    discord_user_id: int,
    guild_id: int,
    details: str,
    client_version: str | None = None,
) -> "SSOAuditLog":
    """Combine update_last_login + create_audit_log into a single DB session."""
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(SSOAccount.id == account_id).one_or_none()
        if account:
            account.last_login = datetime.datetime.now()
            if login_by is not None:
                account.last_login_by = login_by

        audit_log = SSOAuditLog(
            username=username,
            ip_address=ip_address,
            success=True,
            discord_user_id=discord_user_id,
            account_id=account_id,
            guild_id=guild_id,
            details=details,
            client_version=client_version,
        )
        session.add(audit_log)
        session.commit()
        session.expunge(audit_log)
    return audit_log


def delete_account(guild_id: int, real_user: str) -> None:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
            session.delete(account)
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")


class SSOAccountGroup(base.Base):
    __tablename__ = "sso_account_group"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    group_name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    role_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    accounts = sqlalchemy.orm.relationship("SSOAccount", secondary=account_group_mapping, back_populates="groups")

    __table_args__ = (sqlalchemy.UniqueConstraint("guild_id", "group_name", name="uq_guild_id_group_name"),)

    def __init__(self, guild_id, group_name, role_id):
        self.guild_id = guild_id
        self.role_id = role_id
        self.group_name = group_name


def create_account_group(guild_id: int, group_name: str, role_id: int) -> SSOAccountGroup:
    with base.get_session() as session:
        group = SSOAccountGroup(guild_id=guild_id, group_name=group_name, role_id=role_id)
        session.add(group)
        session.commit()
        group = (
            session.query(SSOAccountGroup)
            .options(sqlalchemy.orm.joinedload(SSOAccountGroup.accounts))
            .filter(SSOAccountGroup.id == group.id)
            .one()
        )
        session.expunge_all()
    return group


def get_account_group(guild_id: int, group_name: str) -> SSOAccountGroup:
    with base.get_session() as session:
        try:
            group = (
                session.query(SSOAccountGroup)
                .options(sqlalchemy.orm.joinedload(SSOAccountGroup.accounts))
                .filter(SSOAccountGroup.guild_id == guild_id, SSOAccountGroup.group_name == group_name)
                .one()
            )
            session.expunge_all()
            return group
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")


def list_account_groups(guild_id: int, role: int = None) -> list[SSOAccountGroup]:
    with base.get_session() as session:
        query = session.query(SSOAccountGroup).filter(SSOAccountGroup.guild_id == guild_id)
        if role:
            query = query.filter(SSOAccountGroup.role_id == role)
        query = query.options(sqlalchemy.orm.joinedload(SSOAccountGroup.accounts))
        groups = query.all()
        session.expunge_all()
    return groups


def update_account_group(guild_id: int, group_name: str, new_name: str) -> SSOAccountGroup:
    with base.get_session() as session:
        try:
            group = (
                session.query(SSOAccountGroup)
                .filter(SSOAccountGroup.guild_id == guild_id, SSOAccountGroup.group_name == group_name)
                .one()
            )
            group.group_name = new_name
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")
        group = (
            session.query(SSOAccountGroup)
            .options(sqlalchemy.orm.joinedload(SSOAccountGroup.accounts))
            .filter(SSOAccountGroup.id == group.id)
            .one()
        )
        session.expunge_all()
    return group


def delete_account_group(guild_id: int, group_name: str) -> None:
    with base.get_session() as session:
        try:
            group = (
                session.query(SSOAccountGroup)
                .filter(SSOAccountGroup.guild_id == guild_id, SSOAccountGroup.group_name == group_name)
                .one()
            )
            session.delete(group)
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")


def add_account_to_group(guild_id: int, group_name: str, real_user: str) -> None:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")

        try:
            group = (
                session.query(SSOAccountGroup)
                .filter(SSOAccountGroup.guild_id == guild_id, SSOAccountGroup.group_name == group_name)
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")

        account.groups.append(group)
        session.commit()


def remove_account_from_group(guild_id: int, group_name: str, real_user: str) -> None:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")

        try:
            group = (
                session.query(SSOAccountGroup)
                .filter(SSOAccountGroup.guild_id == guild_id, SSOAccountGroup.group_name == group_name)
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")

        if group not in account.groups:
            raise sqlalchemy.exc.IntegrityError(None, None, "Account is not in this group")
        account.groups.remove(group)
        session.commit()


class SSOAccessKey(base.Base):
    __tablename__ = "sso_access_key"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    discord_user_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    access_key = sqlalchemy.Column(
        CachedEncryptedType(sqlalchemy.String(255), config.ENCRYPTION_KEY), unique=True, index=True
    )

    __table_args__ = (sqlalchemy.UniqueConstraint("guild_id", "discord_user_id", name="uq_guild_id_discord_user_id"),)

    def __init__(self, guild_id, discord_user_id):
        self.guild_id = guild_id
        self.discord_user_id = discord_user_id
        self.access_key = generate_access_key()


def generate_access_key():
    parts = [
        secrets.choice(words.WORDS["verbs"]).strip().capitalize(),
        secrets.choice(words.WORDS["adjectives"]).strip().capitalize(),
        secrets.choice(words.WORDS["nouns"]).strip().capitalize(),
        secrets.choice(words.WORDS["adjectives"]).strip().capitalize(),
    ]
    return "".join(parts)


def get_access_key_by_user(guild_id: int, discord_user_id: int) -> SSOAccessKey:
    with base.get_session() as session:
        access_key = (
            session.query(SSOAccessKey)
            .filter(SSOAccessKey.guild_id == guild_id, SSOAccessKey.discord_user_id == discord_user_id)
            .one_or_none()
        )
        while access_key is None:
            # Create a new access key
            access_key = SSOAccessKey(guild_id=guild_id, discord_user_id=discord_user_id)
            try:
                session.add(access_key)
                session.commit()
                invalidate_access_key_cache()
                session.expunge(access_key)
                access_key = (
                    session.query(SSOAccessKey)
                    .filter(SSOAccessKey.guild_id == guild_id, SSOAccessKey.discord_user_id == discord_user_id)
                    .one()
                )
            except sqlalchemy.exc.IntegrityError:
                access_key = None
                session.rollback()

        session.expunge_all()
    return access_key


_access_key_cache: dict[str, SSOAccessKey] | None = None


def _load_access_key_cache() -> dict[str, SSOAccessKey]:
    """Load all access keys into an in-memory dict keyed by plaintext key.

    EncryptedType decrypts on attribute access, so after expunge the Python
    attribute holds the plaintext.  This turns every subsequent lookup from a
    full-table-scan-with-decrypt into a dict lookup.
    """
    global _access_key_cache
    with base.get_session() as session:
        all_keys = session.query(SSOAccessKey).all()
        session.expunge_all()
    _access_key_cache = {k.access_key: k for k in all_keys}
    return _access_key_cache


def invalidate_access_key_cache() -> None:
    global _access_key_cache
    _access_key_cache = None


def get_access_key_by_key(access_key: str) -> SSOAccessKey or None:
    cache = _access_key_cache if _access_key_cache is not None else _load_access_key_cache()
    return cache.get(access_key)


def reset_access_key(guild_id: int, discord_user_id: int) -> SSOAccessKey:
    with base.get_session() as session:
        access_key = (
            session.query(SSOAccessKey)
            .filter(SSOAccessKey.guild_id == guild_id, SSOAccessKey.discord_user_id == discord_user_id)
            .one_or_none()
        )
        if access_key is None:
            return get_access_key_by_user(guild_id, discord_user_id)

        access_key.access_key = generate_access_key()
        session.commit()
        invalidate_access_key_cache()
        session.expunge(access_key)
        access_key = (
            session.query(SSOAccessKey)
            .filter(SSOAccessKey.guild_id == guild_id, SSOAccessKey.discord_user_id == discord_user_id)
            .one()
        )
        session.expunge_all()
    return access_key


def delete_access_key(guild_id: int, discord_user_id: int) -> None:
    with base.get_session() as session:
        access_key = (
            session.query(SSOAccessKey)
            .filter(SSOAccessKey.guild_id == guild_id, SSOAccessKey.discord_user_id == discord_user_id)
            .one()
        )
        session.delete(access_key)
        session.commit()
        invalidate_access_key_cache()


class SSOTag(base.Base):
    __tablename__ = "sso_tag"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    tag = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    account_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id"))
    account = sqlalchemy.orm.relationship("SSOAccount", back_populates="tags")

    # Foreign key to SSOTagUIMacro
    ui_macro_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_tag_ui_macro.id"), nullable=True)
    # Relationship to SSOTagUIMacro - many tags can reference one macro
    ui_macro = sqlalchemy.orm.relationship("SSOTagUIMacro", back_populates="tags")

    __table_args__ = (sqlalchemy.UniqueConstraint("tag", "account_id", name="uq_tag_account_id"),)

    def __init__(self, guild_id, tag, account_id, ui_macro_id=None):
        self.guild_id = guild_id
        self.tag = tag
        self.account_id = account_id
        self.ui_macro_id = ui_macro_id


def tag_account(guild_id: int, real_user: str, tag: str) -> SSOTag:
    real_user = real_user.lower()
    tag = tag.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")

        tag_obj = SSOTag(guild_id=guild_id, tag=tag, account_id=account.id)
        session.add(tag_obj)
        session.commit()

        try:
            tag_obj = (
                session.query(SSOTag)
                .options(sqlalchemy.orm.joinedload(SSOTag.account))
                .filter(SSOTag.id == tag_obj.id)
                .one()
            )
            session.expunge_all()
            return tag_obj
        except sqlalchemy.exc.NoResultFound:
            # This should never happen, but just in case
            raise SSOAccountTagNotFoundError(f"Tag '{tag}' not found after creation")


def untag_account(guild_id: int, real_user: str, tag: str) -> None:
    real_user = real_user.lower()
    tag = tag.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")

        try:
            tag_obj = session.query(SSOTag).filter(SSOTag.tag == tag, SSOTag.account_id == account.id).one()
            session.delete(tag_obj)
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountTagNotFoundError(f"Tag '{tag}' not found for account '{real_user}'")


def list_tags(guild_id: int) -> dict[str, list[str]]:
    with base.get_session() as session:
        tags = (
            session.query(SSOTag)
            .options(sqlalchemy.orm.joinedload(SSOTag.account))
            .filter(SSOTag.guild_id == guild_id)
            .all()
        )
        tag_map = {}
        for tag in tags:
            if tag.tag not in tag_map:
                tag_map[tag.tag] = []
            tag_map[tag.tag].append(tag.account.real_user)
    return tag_map


def get_tag(guild_id: int, tag: str) -> list[SSOTag]:
    tag = tag.lower()
    with base.get_session() as session:
        tag_objs = (
            session.query(SSOTag)
            .options(sqlalchemy.orm.joinedload(SSOTag.account), sqlalchemy.orm.joinedload(SSOTag.ui_macro))
            .filter(SSOTag.tag == tag, SSOTag.guild_id == guild_id)
            .all()
        )
        session.expunge_all()
        return tag_objs


def update_tag(guild_id: int, tag: str, new_name: str = None, new_ui_macro_data: bytes = None) -> None:
    tag = tag.lower()
    with base.get_session() as session:
        try:
            tag_objs = session.query(SSOTag).filter(SSOTag.tag == tag, SSOTag.guild_id == guild_id).all()
            if not tag_objs:
                raise sqlalchemy.exc.NoResultFound()

            if new_name is not None:
                for tag_obj in tag_objs:
                    tag_obj.tag = new_name.lower()

            if new_ui_macro_data is not None:
                # Update or create UI macro for this tag
                macro = (
                    session.query(SSOTagUIMacro)
                    .filter(SSOTagUIMacro.tag_name == tag, SSOTagUIMacro.guild_id == guild_id)
                    .one_or_none()
                )

                if macro:
                    macro.ui_macro_data = new_ui_macro_data
                else:
                    # Create new macro
                    new_macro = SSOTagUIMacro(guild_id, tag, new_ui_macro_data)
                    session.add(new_macro)
                    session.flush()  # Get the ID of the new macro

                    # Associate all matching tags with this macro
                    for tag_obj in tag_objs:
                        tag_obj.ui_macro_id = new_macro.id

            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountTagNotFoundError(f"Tag '{tag}' not found in guild {guild_id}")


class SSOTagUIMacro(base.Base):
    __tablename__ = "sso_tag_ui_macro"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    tag_name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    ui_macro_data = sqlalchemy.Column(sqlalchemy.BLOB, nullable=False)

    # Relationship to SSOTag - one macro can be referenced by many tags
    tags = sqlalchemy.orm.relationship("SSOTag", back_populates="ui_macro")

    __table_args__ = (sqlalchemy.UniqueConstraint("tag_name", "guild_id", name="uq_tag_name_guild_id"),)

    def __init__(self, guild_id, tag_name, ui_macro_data):
        self.guild_id = guild_id
        self.tag_name = tag_name.lower()
        self.ui_macro_data = ui_macro_data


class SSOAccountAlias(base.Base):
    __tablename__ = "sso_account_alias"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    alias = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    account_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id"))
    account = sqlalchemy.orm.relationship("SSOAccount", back_populates="aliases")

    __table_args__ = (sqlalchemy.UniqueConstraint("alias", "guild_id", name="uq_alias_guild_id"),)

    def __init__(self, guild_id, alias, account_id):
        self.guild_id = guild_id
        self.alias = alias
        self.account_id = account_id


def create_account_alias(guild_id: int, real_user: str, alias: str) -> SSOAccountAlias:
    real_user = real_user.lower()
    alias = alias.lower()
    with base.get_session() as session:
        try:
            account = (
                session.query(SSOAccount)
                .filter(SSOAccount.guild_id == guild_id, SSOAccount.real_user == real_user)
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
        alias = SSOAccountAlias(guild_id=guild_id, alias=alias, account_id=account.id)
        session.add(alias)
        session.commit()
        session.expunge_all()
    return alias


def get_account_alias(guild_id: int, alias: str) -> SSOAccountAlias:
    alias = alias.lower()
    with base.get_session() as session:
        try:
            alias = (
                session.query(SSOAccountAlias)
                .filter(SSOAccountAlias.guild_id == guild_id, SSOAccountAlias.alias == alias)
                .one()
            )
            session.expunge(alias)
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountAliasNotFoundError(f"Alias '{alias}' not found in guild {guild_id}")
    return alias


def list_account_aliases(guild_id: int) -> list[SSOAccountAlias]:
    with base.get_session() as session:
        aliases = (
            session.query(SSOAccountAlias)
            .options(sqlalchemy.orm.joinedload(SSOAccountAlias.account))
            .filter(SSOAccountAlias.guild_id == guild_id)
            .all()
        )
        session.expunge_all()
    return aliases


def delete_account_alias(guild_id: int, alias: str) -> str:
    alias = alias.lower()
    with base.get_session() as session:
        try:
            alias = (
                session.query(SSOAccountAlias)
                .filter(SSOAccountAlias.guild_id == guild_id, SSOAccountAlias.alias == alias)
                .one()
            )
            account_name = alias.account.real_user
            session.delete(alias)
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountAliasNotFoundError(f"Alias '{alias}' not found in guild {guild_id}")
    return account_name


class SSORevocation(base.Base):
    __tablename__ = "sso_revocations"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    timestamp = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)

    # Expiry information
    expiry_days = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    active = sqlalchemy.Column(sqlalchemy.Boolean, default=True)

    # User information
    discord_user_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    details = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)

    __table_args__ = (sqlalchemy.Index("ix_revocation_lookup", "guild_id", "discord_user_id", "active"),)

    def __init__(
        self,
        guild_id: int,
        discord_user_id: int,
        expiry_days: int,
        active: bool = True,
        details: str = None,
        timestamp: datetime.datetime = None,
    ):
        self.guild_id = guild_id
        self.discord_user_id = discord_user_id
        self.expiry_days = expiry_days
        self.active = active
        self.details = details
        self.timestamp = timestamp or datetime.datetime.now()


# --- Revocation cache ---
# Maps (guild_id, discord_user_id) -> list of (expiry_days, timestamp) for active revocations.
# None means the cache hasn't been loaded yet.
_revocation_cache: dict[tuple[int, int], list[tuple[int, datetime.datetime]]] | None = None


def _load_revocation_cache() -> dict[tuple[int, int], list[tuple[int, datetime.datetime]]]:
    global _revocation_cache
    cache: dict[tuple[int, int], list[tuple[int, datetime.datetime]]] = {}
    with base.get_session() as session:
        rows = session.query(SSORevocation).filter(SSORevocation.active == sqlalchemy.true()).all()
        for r in rows:
            key = (r.guild_id, r.discord_user_id)
            cache.setdefault(key, []).append((r.expiry_days, r.timestamp))
    _revocation_cache = cache
    return cache


def invalidate_revocation_cache():
    global _revocation_cache
    _revocation_cache = None


def revoke_user_access(guild_id: int, discord_user_id: int, expiry_days: int, details: str = None) -> SSORevocation:
    with base.get_session() as session:
        revocation = SSORevocation(
            guild_id=guild_id, discord_user_id=discord_user_id, expiry_days=expiry_days, details=details
        )
        session.add(revocation)
        session.commit()
        session.expunge_all()
    invalidate_revocation_cache()
    return revocation


def get_user_access_revocations(
    guild_id: int, discord_user_id: int = None, active_only: bool = True
) -> list[SSORevocation]:
    with base.get_session() as session:
        revocations = session.query(SSORevocation).filter(SSORevocation.guild_id == guild_id)

        if discord_user_id is not None:
            revocations = revocations.filter(SSORevocation.discord_user_id == discord_user_id)
        if active_only:
            revocations = revocations.filter(SSORevocation.active == sqlalchemy.true())
        revocations = revocations.all()
        session.expunge_all()
    return revocations


def is_user_access_revoked(guild_id: int, discord_user_id: int) -> bool:
    cache = _revocation_cache if _revocation_cache is not None else _load_revocation_cache()
    entries = cache.get((guild_id, discord_user_id))
    if not entries:
        return False
    now = datetime.datetime.now()
    for expiry_days, timestamp in entries:
        if expiry_days == 0:
            return True
        elif now < timestamp + datetime.timedelta(days=expiry_days):
            return True
    return False


def remove_access_revocation(guild_id: int, discord_user_id: int) -> None:
    with base.get_session() as session:
        revocations = (
            session.query(SSORevocation)
            .filter(
                SSORevocation.guild_id == guild_id,
                SSORevocation.discord_user_id == discord_user_id,
                SSORevocation.active == sqlalchemy.true(),
            )
            .all()
        )
        for revocation in revocations:
            revocation.active = False
        session.commit()
    invalidate_revocation_cache()


class SSOAuditLog(base.Base):
    """Audit log for SSO authentication attempts through the API."""

    __tablename__ = "sso_audit_log"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    timestamp = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)

    # Request information
    ip_address = sqlalchemy.Column(sqlalchemy.String(45), nullable=True)  # IPv6 can be up to 45 chars
    username = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)

    # Result information
    success = sqlalchemy.Column(sqlalchemy.Boolean, default=False)
    # if discord user lookup succeeded:
    discord_user_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)
    # if account lookup succeeded:
    account_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id"), nullable=True)
    account = sqlalchemy.orm.relationship("SSOAccount", back_populates="audit_logs")
    # allow clearing rate limit
    rate_limit = sqlalchemy.Column(sqlalchemy.Boolean, default=True)

    # Additional information
    details = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)
    client_version = sqlalchemy.Column(sqlalchemy.String(32), nullable=True)

    __table_args__ = (sqlalchemy.Index("ix_audit_rate_limit", "ip_address", "success", "timestamp"),)

    def __init__(
        self,
        username,
        ip_address=None,
        success=False,
        discord_user_id=None,
        account_id=None,
        guild_id=None,
        details=None,
        rate_limit=True,
        timestamp=None,
        client_version=None,
    ):
        self.username = username
        self.ip_address = ip_address
        self.success = success
        self.discord_user_id = discord_user_id
        self.account_id = account_id
        self.guild_id = guild_id
        self.details = details
        self.rate_limit = rate_limit
        self.client_version = client_version
        self.timestamp = timestamp or datetime.datetime.now()


def create_audit_log(
    username,
    ip_address=None,
    success=False,
    discord_user_id=None,
    account_id=None,
    guild_id=None,
    details=None,
    rate_limit=True,
    client_version=None,
) -> SSOAuditLog:
    """Create an audit log entry for an SSO authentication attempt."""
    with base.get_session() as session:
        audit_log = SSOAuditLog(
            username=username,
            ip_address=ip_address,
            success=success,
            discord_user_id=discord_user_id,
            account_id=account_id,
            guild_id=guild_id,
            details=details,
            rate_limit=rate_limit,
            client_version=client_version,
        )
        session.add(audit_log)
        session.commit()
        session.expunge(audit_log)
    return audit_log


def get_audit_logs_for_user_id(discord_user_id: int, limit=100, offset=0, include_list=False) -> list[SSOAuditLog]:
    """Get audit logs for a specific Discord user ID."""
    with base.get_session() as session:
        logs = session.query(SSOAuditLog).filter(SSOAuditLog.discord_user_id == discord_user_id)
        if not include_list:
            logs = logs.filter(SSOAuditLog.username != "list_accounts")
        logs = logs.order_by(SSOAuditLog.timestamp.desc()).limit(limit).offset(offset).all()
        session.expunge_all()
    return logs


def get_audit_logs(
    limit=100, offset=0, guild_id=None, username=None, success=None, since=None, include_list=False, until=None
) -> list[SSOAuditLog]:
    """
    Get audit logs with optional filtering.

    Note: For failed authentication attempts, the guild_id field might be NULL in the database.
    When filtering by guild_id, we need to consider this special case.
    """
    with base.get_session() as session:
        query = session.query(SSOAuditLog).options(
            sqlalchemy.orm.joinedload(SSOAuditLog.account).joinedload(SSOAccount.aliases)
        )

        # Apply filters if provided
        if guild_id:
            query = query.filter(SSOAuditLog.guild_id == guild_id)
        if username:
            query = query.filter(SSOAuditLog.username == username)
        if success is not None:
            query = query.filter(SSOAuditLog.success == success)
        if since:
            query = query.filter(SSOAuditLog.timestamp >= since)
        if until:
            query = query.filter(SSOAuditLog.timestamp <= until)
        if not include_list:
            query = query.filter(SSOAuditLog.username != "list_accounts")
            query = query.filter(SSOAuditLog.username != "update_location")
            query = query.filter(SSOAuditLog.username != "heartbeat")

        # Don't include acknowledged (rate limit removed) entries
        query = query.filter(SSOAuditLog.rate_limit != sqlalchemy.false())

        # Order by timestamp descending (newest first)
        query = query.order_by(SSOAuditLog.timestamp.desc())

        # Apply pagination
        query = query.limit(limit).offset(offset)

        logs = query.all()
        session.expunge_all()
    return logs


def count_failed_attempts(ip_address: str, minutes: int = 60) -> int:
    """
    Count the number of failed authentication attempts from an IP address within a time period.

    Args:
        ip_address: The IP address to check
        minutes: The number of minutes to look back (default: 60)

    Returns:
        The number of failed attempts
    """
    if not ip_address:
        return 0

    with base.get_session() as session:
        # Calculate the time threshold
        time_threshold = datetime.datetime.now() - datetime.timedelta(minutes=minutes)

        # Count failed attempts
        count = (
            session.query(SSOAuditLog)
            .filter(
                SSOAuditLog.ip_address == ip_address,
                SSOAuditLog.success == sqlalchemy.false(),
                SSOAuditLog.timestamp >= time_threshold,
                SSOAuditLog.rate_limit != sqlalchemy.false(),
            )
            .count()
        )

        return count


def get_rate_limited_ips(max_attempts: int = 20, minutes: int = 30) -> list[tuple[str, int]]:
    """Return (ip_address, failure_count) pairs for all currently rate-limited IPs."""
    with base.get_session() as session:
        time_threshold = datetime.datetime.now() - datetime.timedelta(minutes=minutes)
        rows = (
            session.query(
                SSOAuditLog.ip_address,
                sqlalchemy.func.count(SSOAuditLog.id),
            )
            .filter(
                SSOAuditLog.success == sqlalchemy.false(),
                SSOAuditLog.timestamp >= time_threshold,
                SSOAuditLog.rate_limit != sqlalchemy.false(),
            )
            .group_by(SSOAuditLog.ip_address)
            .having(sqlalchemy.func.count(SSOAuditLog.id) >= max_attempts)
            .all()
        )
    return rows


def clear_rate_limit(ip_address: str) -> int:
    with base.get_session() as session:
        updated = (
            session.query(SSOAuditLog)
            .filter(
                SSOAuditLog.ip_address == ip_address,
                SSOAuditLog.success == sqlalchemy.false(),
                SSOAuditLog.rate_limit != sqlalchemy.false(),
            )
            .update({SSOAuditLog.rate_limit: False})
        )
        session.commit()
        return updated


def is_ip_rate_limited(ip_address: str, max_attempts: int = 20, minutes: int = 30) -> bool:
    """
    Check if an IP address should be rate limited based on failed login attempts.

    Args:
        ip_address: The IP address to check
        max_attempts: Maximum number of allowed failed attempts
        minutes: The number of minutes to look back

    Returns:
        True if the IP should be rate limited, False otherwise
    """
    if not ip_address:
        return False

    failed_attempts = count_failed_attempts(ip_address, minutes)
    return failed_attempts >= max_attempts


class SSOAccountCharacter(base.Base):
    """Maps character name/class pairs to SSO accounts."""

    __tablename__ = "sso_account_character"
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    name = sqlalchemy.Column(sqlalchemy.String(64), nullable=False)
    klass = sqlalchemy.Column(sqlalchemy.Enum(CharacterClass), nullable=False)

    bind_location = sqlalchemy.Column(sqlalchemy.String(64), nullable=True)
    park_location = sqlalchemy.Column(sqlalchemy.String(64), nullable=True)
    level = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)

    key_seb = sqlalchemy.Column(sqlalchemy.Boolean, nullable=True)
    key_vp = sqlalchemy.Column(sqlalchemy.Boolean, nullable=True)
    key_st = sqlalchemy.Column(sqlalchemy.Boolean, nullable=True)

    item_void = sqlalchemy.Column(sqlalchemy.Boolean, nullable=True)
    item_neck = sqlalchemy.Column(sqlalchemy.Boolean, nullable=True)
    item_lizard = sqlalchemy.Column(sqlalchemy.Boolean, nullable=True)
    item_thurg = sqlalchemy.Column(sqlalchemy.Boolean, nullable=True)

    account_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id"), nullable=False)
    account = sqlalchemy.orm.relationship("SSOAccount", back_populates="characters")

    __table_args__ = (sqlalchemy.UniqueConstraint("name", "guild_id", name="uq_name_guild"),)


def add_account_character(guild_id: int, real_user: str, name: str, klass: CharacterClass) -> SSOAccountCharacter:
    """Add a character/class to an account."""
    account = find_account_by_username(real_user, guild_id)
    if not account:
        raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
    with base.get_session() as session:
        try:
            character = SSOAccountCharacter(
                account_id=account.id,
                name=name,
                klass=klass,
                guild_id=guild_id,
            )
            session.add(character)
            session.commit()
        except sqlalchemy.exc.IntegrityError:
            raise SSOCharacterAlreadyExistsError(f"Character '{name}' already exists in guild {guild_id}")

        character = session.query(SSOAccountCharacter).filter(SSOAccountCharacter.id == character.id).one()

        session.expunge_all()
    return character


def list_account_characters(guild_id: int, real_user: str = None) -> [SSOAccountCharacter]:
    with base.get_session() as session:
        characters = session.query(SSOAccountCharacter).filter_by(guild_id=guild_id)
        if real_user:
            account = find_account_by_username(real_user, guild_id)
            if not account:
                raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
            characters = characters.filter_by(account_id=account.id)
        characters = characters.options(sqlalchemy.orm.joinedload(SSOAccountCharacter.account))
        characters = characters.all()
        session.expunge_all()
    return characters


def list_account_characters_by_class_zone(
    guild_id: int,
    klass: CharacterClass = None,
    zone: str = None,
    required_key_column: str | None = None,
) -> [SSOAccountCharacter]:
    with base.get_session() as session:
        characters = (
            session.query(SSOAccountCharacter)
            .filter_by(guild_id=guild_id)
            .options(sqlalchemy.orm.joinedload(SSOAccountCharacter.account))
        )
        if klass:
            characters = characters.filter_by(klass=klass)
        if zone:
            characters = characters.filter(
                sqlalchemy.or_(SSOAccountCharacter.bind_location.in_(zone), SSOAccountCharacter.park_location.in_(zone))
            )
        if required_key_column:
            key_col = getattr(SSOAccountCharacter, required_key_column)
            characters = characters.filter(key_col.is_(True))
        # Join with accounts
        characters = characters.join(SSOAccount, SSOAccount.id == SSOAccountCharacter.account_id)
        #  exclude accounts with a recent last_login
        inactivity_time = datetime.datetime.now() - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
        characters = characters.filter(SSOAccount.last_login < inactivity_time)
        characters = characters.all()
        session.expunge_all()
    return characters


def remove_account_character(guild_id: int, name: str) -> bool:
    """Remove a character/class from an account."""
    with base.get_session() as session:
        character = session.query(SSOAccountCharacter).filter_by(name=name, guild_id=guild_id).first()
        if not character:
            return False
        session.delete(character)
        session.commit()
    return True


def update_account_character(
    guild_id: int,
    name: str,
    klass: CharacterClass = None,
    bind_location: str = None,
    park_location: str = None,
    level: int = None,
    key_seb: bool | None = None,
    key_vp: bool | None = None,
    key_st: bool | None = None,
    item_void: bool | None = None,
    item_neck: bool | None = None,
    item_lizard: bool | None = None,
    item_thurg: bool | None = None,
) -> bool:
    """Update character fields. Returns True if the character existed and any field changed."""
    with base.get_session() as session:
        character = session.query(SSOAccountCharacter).filter_by(name=name, guild_id=guild_id).first()
        if not character:
            return False
        changed = False
        if klass:
            if character.klass != klass:
                character.klass = klass
                changed = True
        if bind_location:
            if character.bind_location != bind_location:
                character.bind_location = bind_location
                changed = True
        if park_location:
            if character.park_location != park_location:
                character.park_location = park_location
                changed = True
        if level is not None:
            if character.level != level:
                character.level = level
                changed = True
        if key_seb is not None:
            if character.key_seb != key_seb:
                character.key_seb = key_seb
                changed = True
        if key_vp is not None:
            if character.key_vp != key_vp:
                character.key_vp = key_vp
                changed = True
        if key_st is not None:
            if character.key_st != key_st:
                character.key_st = key_st
                changed = True
        if item_void is not None:
            if character.item_void != item_void:
                character.item_void = item_void
                changed = True
        if item_neck is not None:
            if character.item_neck != item_neck:
                character.item_neck = item_neck
                changed = True
        if item_lizard is not None:
            if character.item_lizard != item_lizard:
                character.item_lizard = item_lizard
                changed = True
        if item_thurg is not None:
            if character.item_thurg != item_thurg:
                character.item_thurg = item_thurg
                changed = True
        if changed:
            session.commit()
        return changed


def mark_key_from_park_zone(guild_id: int, name: str, park_zone_key: str | None) -> bool:
    """If park_zone_key is a keyed zone, set the corresponding key column to True.

    Returns True if a key column was set to True (was not already True).
    """
    if not park_zone_key:
        return False
    column = KEY_ZONE_TO_COLUMN.get(park_zone_key)
    if not column:
        return False
    with base.get_session() as session:
        character = session.query(SSOAccountCharacter).filter_by(name=name, guild_id=guild_id).first()
        if not character:
            return False
        if getattr(character, column):
            return False
        setattr(character, column, True)
        session.commit()
    return True


def set_character_item(guild_id: int, name: str, wire_key: str, value: bool | None) -> bool:
    """Set one tracked wire flag (zone keys + inventory items) to True, False, or None. Returns False if not found."""
    column = WIRE_KEY_TO_ATTR.get(wire_key)
    if not column:
        return False
    with base.get_session() as session:
        character = session.query(SSOAccountCharacter).filter_by(name=name, guild_id=guild_id).first()
        if not character:
            return False
        setattr(character, column, value)
        session.commit()
    return True


def set_character_zone_key(guild_id: int, name: str, key: str, value: bool | None) -> bool:
    """Set one zone key column (seb, vp, st) to True, False, or None (unknown). Returns False if not found."""
    return set_character_item(guild_id, name, key, value)


def find_account_by_character(guild_id: int, name: str) -> SSOAccount | None:
    with base.get_session() as session:
        try:
            character = (
                session.query(SSOAccountCharacter)
                .filter_by(name=name, guild_id=guild_id)
                .options(sqlalchemy.orm.joinedload(SSOAccountCharacter.account))
                .one()
            )
        except sqlalchemy.exc.NoResultFound:
            return None
        except sqlalchemy.exc.MultipleResultsFound:
            return None
        session.expunge_all()
    return character.account


class SSOCharacterSession(base.Base):
    """Tracks contiguous heartbeat sessions for characters.

    A new row is created when a heartbeat arrives and no recent session exists
    (i.e. last_seen is older than the inactivity threshold).  Subsequent
    heartbeats extend the existing session by updating last_seen.
    """

    __tablename__ = "sso_character_session"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    account_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id"), nullable=False)
    character_name = sqlalchemy.Column(sqlalchemy.String(64), nullable=False)
    discord_user_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    first_seen = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    last_seen = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)

    account = sqlalchemy.orm.relationship("SSOAccount")


def record_heartbeat_session(guild_id: int, account_id: int, character_name: str, discord_user_id: int) -> None:
    """Record a heartbeat, extending an active session or creating a new one."""
    now = datetime.datetime.now()
    threshold = now - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
    with base.get_session() as session:
        active = (
            session.query(SSOCharacterSession)
            .filter(
                SSOCharacterSession.guild_id == guild_id,
                SSOCharacterSession.character_name == character_name,
                SSOCharacterSession.last_seen >= threshold,
            )
            .first()
        )
        if active:
            active.last_seen = now
            active.discord_user_id = discord_user_id
        else:
            session.add(
                SSOCharacterSession(
                    guild_id=guild_id,
                    account_id=account_id,
                    character_name=character_name,
                    discord_user_id=discord_user_id,
                    first_seen=now,
                    last_seen=now,
                )
            )
        session.commit()


def expire_other_sessions(guild_id: int, discord_user_id: int, keep_account_id: int) -> int:
    """Expire active sessions for a user on all accounts except keep_account_id.
    Returns the number of sessions expired."""
    threshold = datetime.datetime.now() - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
    expired_time = threshold - datetime.timedelta(seconds=1)
    with base.get_session() as session:
        count = (
            session.query(SSOCharacterSession)
            .filter(
                SSOCharacterSession.guild_id == guild_id,
                SSOCharacterSession.discord_user_id == discord_user_id,
                SSOCharacterSession.account_id != keep_account_id,
                SSOCharacterSession.last_seen >= threshold,
            )
            .update({SSOCharacterSession.last_seen: expired_time})
        )
        session.commit()
    return count


def get_active_characters(guild_id: int) -> dict[int, str]:
    """Return a mapping of account_id -> character_name for currently active sessions."""
    threshold = datetime.datetime.now() - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
    with base.get_session() as session:
        rows = (
            session.query(
                SSOCharacterSession.account_id,
                SSOCharacterSession.character_name,
            )
            .filter(
                SSOCharacterSession.guild_id == guild_id,
                SSOCharacterSession.last_seen >= threshold,
            )
            .order_by(SSOCharacterSession.last_seen.desc())
            .all()
        )
    seen: dict[int, str] = {}
    for account_id, character_name in rows:
        seen.setdefault(account_id, character_name)
    return seen


def get_sessions_in_range(guild_id: int, start: datetime.datetime, end: datetime.datetime) -> list[SSOCharacterSession]:
    """Return sessions overlapping [start, end] with eager-loaded account + aliases."""
    with base.get_session() as session:
        sessions = (
            session.query(SSOCharacterSession)
            .options(
                sqlalchemy.orm.joinedload(SSOCharacterSession.account).joinedload(SSOAccount.aliases),
                sqlalchemy.orm.joinedload(SSOCharacterSession.account).joinedload(SSOAccount.characters),
            )
            .filter(
                SSOCharacterSession.guild_id == guild_id,
                SSOCharacterSession.first_seen <= end,
                SSOCharacterSession.last_seen >= start,
            )
            .order_by(SSOCharacterSession.first_seen)
            .all()
        )
        session.expunge_all()
    return sessions


def archive_old_records(retention_days: int = 90, archive_dir: str = "audit_archives") -> tuple[int, int]:
    """Export audit logs and character sessions older than *retention_days* to
    CSV files, then delete them from the database.

    Returns (audit_count, session_count) of archived rows.
    """
    import csv
    import logging
    import os

    logger = logging.getLogger(__name__)
    cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)

    audit_count = 0
    session_count = 0

    with base.get_session() as session:
        old_audits = (
            session.query(SSOAuditLog)
            .filter(
                SSOAuditLog.timestamp < cutoff,
            )
            .order_by(SSOAuditLog.timestamp)
            .all()
        )

        old_sessions = (
            session.query(SSOCharacterSession)
            .filter(
                SSOCharacterSession.last_seen < cutoff,
            )
            .order_by(SSOCharacterSession.first_seen)
            .all()
        )

        if not old_audits and not old_sessions:
            return 0, 0

        os.makedirs(archive_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        if old_audits:
            path = os.path.join(archive_dir, f"audit_log_{ts}.csv")
            audit_cols = [
                "id",
                "timestamp",
                "ip_address",
                "username",
                "success",
                "discord_user_id",
                "guild_id",
                "account_id",
                "rate_limit",
                "details",
            ]
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(audit_cols)
                for row in old_audits:
                    writer.writerow(
                        [
                            row.id,
                            row.timestamp,
                            row.ip_address,
                            row.username,
                            row.success,
                            row.discord_user_id,
                            row.guild_id,
                            row.account_id,
                            row.rate_limit,
                            row.details,
                        ]
                    )
            audit_count = len(old_audits)
            audit_ids = [row.id for row in old_audits]
            session.query(SSOAuditLog).filter(
                SSOAuditLog.id.in_(audit_ids),
            ).delete(synchronize_session="fetch")
            logger.info("Archived %d audit log rows to %s", audit_count, path)

        if old_sessions:
            path = os.path.join(archive_dir, f"character_session_{ts}.csv")
            session_cols = [
                "id",
                "guild_id",
                "account_id",
                "character_name",
                "discord_user_id",
                "first_seen",
                "last_seen",
            ]
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(session_cols)
                for row in old_sessions:
                    writer.writerow(
                        [
                            row.id,
                            row.guild_id,
                            row.account_id,
                            row.character_name,
                            row.discord_user_id,
                            row.first_seen,
                            row.last_seen,
                        ]
                    )
            session_count = len(old_sessions)
            sess_ids = [row.id for row in old_sessions]
            session.query(SSOCharacterSession).filter(
                SSOCharacterSession.id.in_(sess_ids),
            ).delete(synchronize_session="fetch")
            logger.info(
                "Archived %d character session rows to %s",
                session_count,
                path,
            )

        session.commit()

    return audit_count, session_count
