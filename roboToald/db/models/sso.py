import datetime
import itertools

import sqlalchemy
import sqlalchemy.exc
from sqlalchemy import func as sqlalchemy_func
import sqlalchemy.orm
import sqlalchemy_utils
import enum

from roboToald import config
from roboToald.db import base
from roboToald import words


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
    real_pass = sqlalchemy.Column(CachedEncryptedType(
        sqlalchemy.String(255), config.ENCRYPTION_KEY), nullable=False)

    last_login = sqlalchemy.Column(sqlalchemy.DateTime, default=datetime.datetime.min)
    last_login_by = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)

    groups = sqlalchemy.orm.relationship("SSOAccountGroup", secondary=account_group_mapping,
                                         back_populates="accounts")
    audit_logs = sqlalchemy.orm.relationship("SSOAuditLog", back_populates="account")
    tags = sqlalchemy.orm.relationship("SSOTag", back_populates="account",
                                       cascade="all, delete-orphan")
    aliases = sqlalchemy.orm.relationship("SSOAccountAlias", back_populates="account",
                                          cascade="all, delete-orphan")
    characters = sqlalchemy.orm.relationship("SSOAccountCharacter", back_populates="account",
                                             cascade="all, delete-orphan")

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'guild_id', 'real_user', name='uq_guild_id_real_user'),
    )

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
        account = session.query(SSOAccount).options(
            sqlalchemy.orm.joinedload(SSOAccount.groups),
            sqlalchemy.orm.joinedload(SSOAccount.tags),
            sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
            SSOAccount.id == account.id).one()

        session.expunge_all()
    return account


def get_account(guild_id: int, real_user: str) -> SSOAccount:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = session.query(SSOAccount).options(
                sqlalchemy.orm.joinedload(SSOAccount.groups),
                sqlalchemy.orm.joinedload(SSOAccount.characters),
                sqlalchemy.orm.joinedload(SSOAccount.tags),
                sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
            session.expunge(account)
            return account
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")


def get_account_by_id(account_id: int) -> SSOAccount:
    with base.get_session() as session:
        try:
            account = session.query(SSOAccount).options(
                sqlalchemy.orm.joinedload(SSOAccount.groups),
                sqlalchemy.orm.joinedload(SSOAccount.characters),
                sqlalchemy.orm.joinedload(SSOAccount.tags),
                sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
                SSOAccount.id == account_id).one()
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


def find_account_by_username(username: str, guild_id: int = None, inactive_only: bool = False) -> SSOAccount or None:
    username = username.lower()
    """Find an account by username."""
    with base.get_session() as session:
        # Try to find the account directly by real_user
        account = session.query(SSOAccount).options(
            sqlalchemy.orm.joinedload(SSOAccount.groups),
            sqlalchemy.orm.joinedload(SSOAccount.tags),
            sqlalchemy.orm.joinedload(SSOAccount.characters),
            sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
            SSOAccount.real_user == username,
            SSOAccount.guild_id == guild_id
        ).one_or_none()

        if account:
            session.expunge(account)
            return account

        # If not found, try to find by character name
        character = session.query(SSOAccountCharacter).options(
            sqlalchemy.orm.joinedload(SSOAccountCharacter.account)).filter(
            sqlalchemy_func.lower(SSOAccountCharacter.name) == username.lower(),
            SSOAccountCharacter.guild_id == guild_id
        ).one_or_none()

        if character:
            account = session.query(SSOAccount).options(
                sqlalchemy.orm.joinedload(SSOAccount.groups),
                sqlalchemy.orm.joinedload(SSOAccount.tags),
                sqlalchemy.orm.joinedload(SSOAccount.characters),
                sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
                SSOAccount.id == character.account_id
            ).one_or_none()
            session.expunge(account)
            return account

        # If not found, try to find by alias
        alias = session.query(SSOAccountAlias).options(
            sqlalchemy.orm.joinedload(SSOAccountAlias.account)).filter(
            SSOAccountAlias.alias == username,
            SSOAccountAlias.guild_id == guild_id
        ).one_or_none()

        if alias:
            account = session.query(SSOAccount).options(
                sqlalchemy.orm.joinedload(SSOAccount.groups),
                sqlalchemy.orm.joinedload(SSOAccount.tags),
                sqlalchemy.orm.joinedload(SSOAccount.characters),
                sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
                SSOAccount.id == alias.account_id
            ).one_or_none()
            session.expunge(account)
            return account

        # If not found, try to find by traditional tag
        tagged_accounts = session.query(SSOTag).options(
            sqlalchemy.orm.joinedload(SSOTag.account)).filter(
            SSOTag.tag == username,
            SSOTag.guild_id == guild_id
        ).all()

        if tagged_accounts:
            now = datetime.datetime.now()
            if inactive_only:
                inactivity_time = now - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
                accounts = [tagged_account.account for tagged_account in tagged_accounts
                            if tagged_account.account.last_login < inactivity_time]
            else:
                accounts = [tagged_account.account for tagged_account in tagged_accounts]
            if not accounts:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")
            accounts.sort(key=lambda a: _login_sort_key(a, now, _max_character_level))
            account = session.query(SSOAccount).options(
                sqlalchemy.orm.joinedload(SSOAccount.groups),
                sqlalchemy.orm.joinedload(SSOAccount.tags),
                sqlalchemy.orm.joinedload(SSOAccount.characters),
                sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
                SSOAccount.id == accounts[0].id
            ).one_or_none()
            session.expunge(account)
            return account

        # If not found, try to find by dynamic tag
        if username in get_dynamic_tag_list():
            dynamic_tags_tuple = get_dynamic_tags()
            dynamic_tag_zones: dict[str, list[str]] = dynamic_tags_tuple[0]
            dynamic_tag_classes: dict[str, CharacterClass] = dynamic_tags_tuple[1]

            # Figure out which zone/class the username is
            zones = None
            klass = None
            for dt_zone, dt_zones in dynamic_tag_zones.items():
                if username.startswith(dt_zone):
                    zones = dt_zones
                    break
            for dt_class, dt_classes in dynamic_tag_classes.items():
                if username.endswith(dt_class):
                    klass = dt_classes
                    break
            if not zones or not klass:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")

            # Get the account
            characters = list_account_characters_by_class_zone(guild_id, klass, zones)
            if not characters:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")
            # Build account_id -> character level mapping (one class per account)
            char_level_by_account = {c.account_id: (c.level or 0) for c in characters}
            accounts = list({c.account for c in characters})
            now = datetime.datetime.now()
            accounts.sort(key=lambda a: _login_sort_key(
                a, now, lambda acct: char_level_by_account.get(acct.id, 0)))
            if not accounts:
                raise SSOTagTemporarilyEmptyError(f"Tag '{username}' is temporarily empty")
            return accounts[0]


def list_accounts(guild_id: int, group: str = None, tag: str = None) -> list[SSOAccount]:
    with base.get_session() as session:
        query = session.query(SSOAccount).filter(SSOAccount.guild_id == guild_id)
        if group:
            query = query.join(SSOAccount.groups).filter(SSOAccountGroup.group_name == group)
        if tag:
            query = query.join(SSOAccount.tags).filter(SSOTag.tag == tag)
        query = query.options(sqlalchemy.orm.joinedload(SSOAccount.groups),
                              sqlalchemy.orm.joinedload(SSOAccount.characters),
                              sqlalchemy.orm.joinedload(SSOAccount.tags),
                              sqlalchemy.orm.joinedload(SSOAccount.aliases))
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
    dynamic_tag_zones.update({
        "dain": dynamic_tag_zones['thurg'],
        "yeli": dynamic_tag_zones['ss'],
        "zlandi": dynamic_tag_zones['dn'],
    })

    dynamic_tag_classes = {
        'bar': CharacterClass.Bard,
        'brd': CharacterClass.Bard,
        'bard': CharacterClass.Bard,
        'clr': CharacterClass.Cleric,
        'cle': CharacterClass.Cleric,
        'cleric': CharacterClass.Cleric,
        'dru': CharacterClass.Druid,
        'druid': CharacterClass.Druid,
        'enc': CharacterClass.Enchanter,
        'enchanter': CharacterClass.Enchanter,
        'mag': CharacterClass.Magician,
        'mage': CharacterClass.Magician,
        'magician': CharacterClass.Magician,
        'mnk': CharacterClass.Monk,
        'mon': CharacterClass.Monk,
        'monk': CharacterClass.Monk,
        'nec': CharacterClass.Necromancer,
        'necro': CharacterClass.Necromancer,
        'necromancer': CharacterClass.Necromancer,
        'pal': CharacterClass.Paladin,
        'pld': CharacterClass.Paladin,
        'paladin': CharacterClass.Paladin,
        'ran': CharacterClass.Ranger,
        'rng': CharacterClass.Ranger,
        'ranger': CharacterClass.Ranger,
        'rog': CharacterClass.Rogue,
        'rogue': CharacterClass.Rogue,
        'sk': CharacterClass.ShadowKnight,
        'shadowknight': CharacterClass.ShadowKnight,
        'sha': CharacterClass.Shaman,
        'shm': CharacterClass.Shaman,
        'sham': CharacterClass.Shaman,
        'shaman': CharacterClass.Shaman,
        'war': CharacterClass.Warrior,
        'warrior': CharacterClass.Warrior,
        'wiz': CharacterClass.Wizard,
        'wizard': CharacterClass.Wizard,
    }
    return dynamic_tag_zones, dynamic_tag_classes


def get_dynamic_tag_list():
    dt_zones, dt_classes = get_dynamic_tags()
    dt_list = ["{}{}".format(a, b) for a, b in itertools.product(list(dt_zones), list(dt_classes))]
    return dt_list


def update_account(guild_id: int, real_user: str, password: str) -> SSOAccount:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = session.query(SSOAccount).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
            account.real_pass = password
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
        session.expunge(account)
    return account


def update_last_login(account_id: int, login_by: str | None = None) -> None:
    """Update the last_login timestamp (and optionally who logged in) for an account."""
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.id == account_id
        ).one_or_none()
        if account:
            account.last_login = datetime.datetime.now()
            if login_by is not None:
                account.last_login_by = login_by
            session.commit()


def delete_account(guild_id: int, real_user: str) -> None:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = session.query(SSOAccount).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
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

    accounts = sqlalchemy.orm.relationship("SSOAccount", secondary=account_group_mapping,
                                           back_populates="groups")

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'guild_id', 'group_name', name='uq_guild_id_group_name'),
    )

    def __init__(self, guild_id, group_name, role_id):
        self.guild_id = guild_id
        self.role_id = role_id
        self.group_name = group_name


def create_account_group(guild_id: int, group_name: str, role_id: int) -> SSOAccountGroup:
    with base.get_session() as session:
        group = SSOAccountGroup(guild_id=guild_id, group_name=group_name, role_id=role_id)
        session.add(group)
        session.commit()
        group = session.query(SSOAccountGroup).options(
            sqlalchemy.orm.joinedload(SSOAccountGroup.accounts)).filter(
            SSOAccountGroup.id == group.id).one()
        session.expunge_all()
    return group


def get_account_group(guild_id: int, group_name: str) -> SSOAccountGroup:
    with base.get_session() as session:
        try:
            group = session.query(SSOAccountGroup).options(
                sqlalchemy.orm.joinedload(SSOAccountGroup.accounts)).filter(
                SSOAccountGroup.guild_id == guild_id,
                SSOAccountGroup.group_name == group_name).one()
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
            group = session.query(SSOAccountGroup).filter(
                SSOAccountGroup.guild_id == guild_id,
                SSOAccountGroup.group_name == group_name).one()
            group.group_name = new_name
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")
        group = session.query(SSOAccountGroup).options(
            sqlalchemy.orm.joinedload(SSOAccountGroup.accounts)).filter(
            SSOAccountGroup.id == group.id).one()
        session.expunge_all()
    return group


def delete_account_group(guild_id: int, group_name: str) -> None:
    with base.get_session() as session:
        try:
            group = session.query(SSOAccountGroup).filter(
                SSOAccountGroup.guild_id == guild_id,
                SSOAccountGroup.group_name == group_name).one()
            session.delete(group)
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")


def add_account_to_group(guild_id: int, group_name: str, real_user: str) -> None:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = session.query(SSOAccount).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
            
        try:
            group = session.query(SSOAccountGroup).filter(
                SSOAccountGroup.guild_id == guild_id,
                SSOAccountGroup.group_name == group_name).one()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountGroupNotFoundError(f"Group '{group_name}' not found in guild {guild_id}")
            
        account.groups.append(group)
        session.commit()


def remove_account_from_group(guild_id: int, group_name: str, real_user: str) -> None:
    real_user = real_user.lower()
    with base.get_session() as session:
        try:
            account = session.query(SSOAccount).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
            
        try:
            group = session.query(SSOAccountGroup).filter(
                SSOAccountGroup.guild_id == guild_id,
                SSOAccountGroup.group_name == group_name).one()
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
    access_key = sqlalchemy.Column(CachedEncryptedType(
        sqlalchemy.String(255), config.ENCRYPTION_KEY), unique=True, index=True)

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'guild_id', 'discord_user_id',
            name='uq_guild_id_discord_user_id'),
    )

    def __init__(self, guild_id, discord_user_id):
        self.guild_id = guild_id
        self.discord_user_id = discord_user_id
        self.access_key = generate_access_key()


def generate_access_key():
    # Generate a random access key
    passkey = ""
    tries = 0
    while 14 > len(passkey) < 24:
        tries += 1
        verb = words.get_verb().capitalize()
        adjective = words.get_adjective().capitalize()
        noun = words.get_noun().capitalize()
        passkey = f"{verb}{adjective}{noun}"
        if tries > 10:
            break
    return passkey


def get_access_key_by_user(guild_id: int, discord_user_id: int) -> SSOAccessKey:
    with base.get_session() as session:
        access_key = session.query(SSOAccessKey).filter(
            SSOAccessKey.guild_id == guild_id,
            SSOAccessKey.discord_user_id == discord_user_id).one_or_none()
        while access_key is None:
            # Create a new access key
            access_key = SSOAccessKey(guild_id=guild_id, discord_user_id=discord_user_id)
            try:
                session.add(access_key)
                session.commit()
                session.expunge(access_key)
                access_key = session.query(SSOAccessKey).filter(
                    SSOAccessKey.guild_id == guild_id,
                    SSOAccessKey.discord_user_id == discord_user_id).one()
            except sqlalchemy.exc.IntegrityError:
                access_key = None
                session.rollback()

        session.expunge_all()
    return access_key


def get_access_key_by_key(access_key: str) -> SSOAccessKey or None:
    with base.get_session() as session:
        access_key_obj = session.query(SSOAccessKey).filter(
            SSOAccessKey.access_key == access_key).one_or_none()
        if access_key_obj:
            session.expunge(access_key_obj)
    return access_key_obj


def reset_access_key(guild_id: int, discord_user_id: int) -> SSOAccessKey:
    with base.get_session() as session:
        access_key = session.query(SSOAccessKey).filter(
            SSOAccessKey.guild_id == guild_id,
            SSOAccessKey.discord_user_id == discord_user_id).one_or_none()
        if access_key is None:
            return get_access_key_by_user(guild_id, discord_user_id)

        access_key.access_key = generate_access_key()
        session.commit()
        session.expunge(access_key)
        access_key = session.query(SSOAccessKey).filter(
            SSOAccessKey.guild_id == guild_id,
            SSOAccessKey.discord_user_id == discord_user_id).one()
        session.expunge_all()
    return access_key


def delete_access_key(guild_id: int, discord_user_id: int) -> None:
    with base.get_session() as session:
        access_key = session.query(SSOAccessKey).filter(
            SSOAccessKey.guild_id == guild_id,
            SSOAccessKey.discord_user_id == discord_user_id).one()
        session.delete(access_key)
        session.commit()


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

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'tag', 'account_id', name='uq_tag_account_id'),
    )

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
            account = session.query(SSOAccount).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
            
        tag_obj = SSOTag(guild_id=guild_id, tag=tag, account_id=account.id)
        session.add(tag_obj)
        session.commit()
        
        try:
            tag_obj = session.query(SSOTag).options(
                sqlalchemy.orm.joinedload(SSOTag.account)).filter(
                SSOTag.id == tag_obj.id).one()
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
            account = session.query(SSOAccount).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountNotFoundError(f"Account '{real_user}' not found in guild {guild_id}")
            
        try:
            tag_obj = session.query(SSOTag).filter(
                SSOTag.tag == tag,
                SSOTag.account_id == account.id).one()
            session.delete(tag_obj)
            session.commit()
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountTagNotFoundError(f"Tag '{tag}' not found for account '{real_user}'")



def list_tags(guild_id: int) -> dict[str, list[str]]:
    with base.get_session() as session:
        tags = session.query(SSOTag).options(
            sqlalchemy.orm.joinedload(SSOTag.account)).filter(
            SSOTag.guild_id == guild_id).all()
        tag_map = {}
        for tag in tags:
            if tag.tag not in tag_map:
                tag_map[tag.tag] = []
            tag_map[tag.tag].append(tag.account.real_user)
    return tag_map


def get_tag(guild_id: int, tag: str) -> list[SSOTag]:
    tag = tag.lower()   
    with base.get_session() as session:
        tag_objs = session.query(SSOTag).options(
            sqlalchemy.orm.joinedload(SSOTag.account),
            sqlalchemy.orm.joinedload(SSOTag.ui_macro)).filter(
            SSOTag.tag == tag,
            SSOTag.guild_id == guild_id).all()
        session.expunge_all()
        return tag_objs


def update_tag(guild_id: int, tag: str, new_name: str = None, new_ui_macro_data: bytes = None) -> None:
    tag = tag.lower()   
    with base.get_session() as session:
        try:
            tag_objs = session.query(SSOTag).filter(
                SSOTag.tag == tag,
                SSOTag.guild_id == guild_id).all()
            if not tag_objs:
                raise sqlalchemy.exc.NoResultFound()
                
            if new_name is not None:
                for tag_obj in tag_objs:
                    tag_obj.tag = new_name.lower()
                    
            if new_ui_macro_data is not None:
                # Update or create UI macro for this tag
                macro = session.query(SSOTagUIMacro).filter(
                    SSOTagUIMacro.tag_name == tag,
                    SSOTagUIMacro.guild_id == guild_id).one_or_none()
                
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

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'tag_name', 'guild_id', name='uq_tag_name_guild_id'),
    )

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

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'alias', 'guild_id', name='uq_alias_guild_id'),
    )

    def __init__(self, guild_id, alias, account_id):
        self.guild_id = guild_id
        self.alias = alias
        self.account_id = account_id


def create_account_alias(guild_id: int, real_user: str, alias: str) -> SSOAccountAlias:
    real_user = real_user.lower()
    alias = alias.lower()
    with base.get_session() as session:
        try:
            account = session.query(SSOAccount).filter(
                SSOAccount.guild_id == guild_id,
                SSOAccount.real_user == real_user).one()
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
            alias = session.query(SSOAccountAlias).filter(
                SSOAccountAlias.guild_id == guild_id,
                SSOAccountAlias.alias == alias).one()
            session.expunge(alias)
        except sqlalchemy.exc.NoResultFound:
            raise SSOAccountAliasNotFoundError(f"Alias '{alias}' not found in guild {guild_id}")
    return alias


def list_account_aliases(guild_id: int) -> list[SSOAccountAlias]:
    with base.get_session() as session:
        aliases = session.query(SSOAccountAlias).options(
            sqlalchemy.orm.joinedload(SSOAccountAlias.account)).filter(
            SSOAccountAlias.guild_id == guild_id).all()
        session.expunge_all()
    return aliases


def delete_account_alias(guild_id: int, alias: str) -> str:
    alias = alias.lower()
    with base.get_session() as session:
        try:
            alias = session.query(SSOAccountAlias).filter(
                SSOAccountAlias.guild_id == guild_id,
                SSOAccountAlias.alias == alias).one()
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

    def __init__(self, guild_id: int, discord_user_id: int, expiry_days: int, active: bool = True, details: str = None, timestamp: datetime.datetime = None):
        self.guild_id = guild_id
        self.discord_user_id = discord_user_id
        self.expiry_days = expiry_days
        self.active = active
        self.details = details
        self.timestamp = timestamp or datetime.datetime.now()


def revoke_user_access(guild_id: int, discord_user_id: int, expiry_days: int, details: str = None) -> SSORevocation:
    with base.get_session() as session:
        revocation = SSORevocation(guild_id=guild_id, discord_user_id=discord_user_id, expiry_days=expiry_days, details=details)
        session.add(revocation)
        session.commit()
        session.expunge_all()
    return revocation


def get_user_access_revocations(guild_id: int, discord_user_id: int = None, active_only: bool = True) -> list[SSORevocation]:
    with base.get_session() as session:
        revocations = session.query(SSORevocation).filter(
            SSORevocation.guild_id == guild_id)

        if discord_user_id is not None:
            revocations = revocations.filter(
                SSORevocation.discord_user_id == discord_user_id)
        if active_only:
            revocations = revocations.filter(
                SSORevocation.active == True)
        revocations = revocations.all()
        session.expunge_all()
    return revocations


def is_user_access_revoked(guild_id: int, discord_user_id: int) -> bool:
    with base.get_session() as session:
        revocations = session.query(SSORevocation).filter(
            SSORevocation.guild_id == guild_id,
            SSORevocation.discord_user_id == discord_user_id,
            SSORevocation.active == True).all()
        session.expunge_all()
        for revocation in revocations:
            if revocation.expiry_days == 0:
                return True
            elif datetime.datetime.now() < revocation.timestamp + datetime.timedelta(days=revocation.expiry_days):
                return True
    return False


def remove_access_revocation(guild_id: int, discord_user_id: int) -> None:
    with base.get_session() as session:
        revocations = session.query(SSORevocation).filter(
            SSORevocation.guild_id == guild_id,
            SSORevocation.discord_user_id == discord_user_id,
            SSORevocation.active == True).all()
        for revocation in revocations:
            revocation.active = False
        session.commit()


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

    def __init__(self, username, ip_address=None, success=False, discord_user_id=None, 
                 account_id=None, guild_id=None, details=None, rate_limit=True, timestamp=None):
        self.username = username
        self.ip_address = ip_address
        self.success = success
        self.discord_user_id = discord_user_id
        self.account_id = account_id
        self.guild_id = guild_id
        self.details = details
        self.rate_limit = rate_limit
        self.timestamp = timestamp or datetime.datetime.now()


def create_audit_log(username, ip_address=None, success=False, discord_user_id=None, 
                     account_id=None, guild_id=None, details=None, rate_limit=True) -> SSOAuditLog:
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
            rate_limit=rate_limit
        )
        session.add(audit_log)
        session.commit()
        session.expunge(audit_log)
    return audit_log


def get_audit_logs_for_user_id(discord_user_id: int, limit=100, offset=0, include_list=False) -> list[SSOAuditLog]:
    """Get audit logs for a specific Discord user ID."""
    with base.get_session() as session:
        logs = session.query(SSOAuditLog).filter(
            SSOAuditLog.discord_user_id == discord_user_id
        )
        if not include_list:
            logs = logs.filter(SSOAuditLog.username != "list_accounts")
        logs = logs.order_by(SSOAuditLog.timestamp.desc()).limit(limit).offset(offset).all()
        session.expunge_all()
    return logs


def get_audit_logs(limit=100, offset=0, guild_id=None, username=None, success=None, 
                   since=None, include_list=False, until=None) -> list[SSOAuditLog]:
    """
    Get audit logs with optional filtering.
    
    Note: For failed authentication attempts, the guild_id field might be NULL in the database.
    When filtering by guild_id, we need to consider this special case.
    """
    with base.get_session() as session:
        query = session.query(SSOAuditLog).options(
            sqlalchemy.orm.joinedload(SSOAuditLog.account).joinedload(SSOAccount.aliases))
        
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
        query = query.filter(SSOAuditLog.rate_limit != False)
        
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
        count = session.query(SSOAuditLog).filter(
            SSOAuditLog.ip_address == ip_address,
            SSOAuditLog.success == False,
            SSOAuditLog.timestamp >= time_threshold,
            sqlalchemy.or_(
                SSOAuditLog.account_id.isnot(None),
                SSOAuditLog.username == "list_accounts"
            ),
            SSOAuditLog.rate_limit != False
        ).count()
        
        return count


def clear_rate_limit(ip_address: str) -> int:
    with base.get_session() as session:
        updated = session.query(SSOAuditLog).filter(
            SSOAuditLog.ip_address == ip_address,
            SSOAuditLog.success == False,
            SSOAuditLog.rate_limit != False
        ).update({SSOAuditLog.rate_limit: False})
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

    account_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id"), nullable=False)
    account = sqlalchemy.orm.relationship("SSOAccount", back_populates="characters")

    __table_args__ = (
        sqlalchemy.UniqueConstraint("name", "guild_id", name="uq_name_guild"),
    )


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
        except sqlalchemy.exc.IntegrityError as e:
            raise SSOCharacterAlreadyExistsError(f"Character '{name}' already exists in guild {guild_id}")

        character = session.query(SSOAccountCharacter).filter(
            SSOAccountCharacter.id == character.id).one()

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


def list_account_characters_by_class_zone(guild_id: int, klass: CharacterClass = None, zone: str = None) -> [SSOAccountCharacter]:
    with base.get_session() as session:
        characters = session.query(SSOAccountCharacter).filter_by(guild_id=guild_id).options(
            sqlalchemy.orm.joinedload(SSOAccountCharacter.account)
        )
        if klass:
            characters = characters.filter_by(klass=klass)
        if zone:
            characters = characters.filter(
                sqlalchemy.or_(SSOAccountCharacter.bind_location.in_(zone),
                               SSOAccountCharacter.park_location.in_(zone)))
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
        character = session.query(SSOAccountCharacter).filter_by(
            name=name, guild_id=guild_id
        ).first()
        if not character:
            return False
        session.delete(character)
        session.commit()
    return True


def update_account_character(guild_id: int, name: str, klass: CharacterClass = None,
                             bind_location: str = None, park_location: str = None,
                             level: int = None) -> bool:
    with base.get_session() as session:
        character = session.query(SSOAccountCharacter).filter_by(
            name=name, guild_id=guild_id
        ).first()
        if not character:
            return False
        if klass:
            character.klass = klass
        if bind_location:
            character.bind_location = bind_location
        if park_location:
            character.park_location = park_location
        if level is not None:
            character.level = level
        session.commit()
    return True


def find_account_by_character(guild_id: int, name: str) -> SSOAccount | None:
    with base.get_session() as session:
        try:
            character = session.query(SSOAccountCharacter).filter_by(
                name=name, guild_id=guild_id
            ).options(sqlalchemy.orm.joinedload(SSOAccountCharacter.account)).one()
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


def record_heartbeat_session(guild_id: int, account_id: int,
                             character_name: str, discord_user_id: int) -> None:
    """Record a heartbeat, extending an active session or creating a new one."""
    now = datetime.datetime.now()
    threshold = now - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
    with base.get_session() as session:
        active = session.query(SSOCharacterSession).filter(
            SSOCharacterSession.guild_id == guild_id,
            SSOCharacterSession.character_name == character_name,
            SSOCharacterSession.last_seen >= threshold,
        ).first()
        if active:
            active.last_seen = now
            active.discord_user_id = discord_user_id
        else:
            session.add(SSOCharacterSession(
                guild_id=guild_id,
                account_id=account_id,
                character_name=character_name,
                discord_user_id=discord_user_id,
                first_seen=now,
                last_seen=now,
            ))
        session.commit()


def get_active_characters(guild_id: int) -> dict[int, str]:
    """Return a mapping of account_id -> character_name for currently active sessions."""
    threshold = datetime.datetime.now() - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
    with base.get_session() as session:
        rows = session.query(
            SSOCharacterSession.account_id,
            SSOCharacterSession.character_name,
        ).filter(
            SSOCharacterSession.guild_id == guild_id,
            SSOCharacterSession.last_seen >= threshold,
        ).order_by(SSOCharacterSession.last_seen.desc()).all()
    seen: dict[int, str] = {}
    for account_id, character_name in rows:
        seen.setdefault(account_id, character_name)
    return seen


def get_sessions_in_range(guild_id: int, start: datetime.datetime,
                          end: datetime.datetime) -> list[SSOCharacterSession]:
    """Return sessions overlapping [start, end] with eager-loaded account + aliases."""
    with base.get_session() as session:
        sessions = session.query(SSOCharacterSession).options(
            sqlalchemy.orm.joinedload(SSOCharacterSession.account)
            .joinedload(SSOAccount.aliases)
        ).filter(
            SSOCharacterSession.guild_id == guild_id,
            SSOCharacterSession.first_seen <= end,
            SSOCharacterSession.last_seen >= start,
        ).order_by(SSOCharacterSession.first_seen).all()
        session.expunge_all()
    return sessions
