import datetime

import sqlalchemy.orm
import sqlalchemy_utils

from roboToald import config
from roboToald.db import base
from roboToald import words


account_group_mapping = sqlalchemy.Table(
    "sso_account_group_mapping",
    base.Base.metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("account_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account.id")),
    sqlalchemy.Column("group_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("sso_account_group.id")),
)


class SSOAccount(base.Base):
    """Each entry in SSOAccounts represents an EQ bot account.

    Accounts can be members of multiple groups.
    """
    __tablename__ = "sso_account"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    real_user = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    real_pass = sqlalchemy.Column(sqlalchemy_utils.EncryptedType(
        sqlalchemy.String(255), config.ENCRYPTION_KEY), nullable=False)

    last_login = sqlalchemy.Column(sqlalchemy.DateTime)

    groups = sqlalchemy.orm.relationship("SSOAccountGroup", secondary=account_group_mapping,
                                         back_populates="accounts")
    audit_logs = sqlalchemy.orm.relationship("SSOAuditLog", back_populates="account")
    tags = sqlalchemy.orm.relationship("SSOTag", back_populates="account",
                                       cascade="all, delete-orphan")
    aliases = sqlalchemy.orm.relationship("SSOAccountAlias", back_populates="account",
                                          cascade="all, delete-orphan")

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'guild_id', 'real_user', name='uq_guild_id_real_user'),
    )

    def __init__(self, guild_id, real_user, real_pass, last_login=None):
        self.guild_id = guild_id
        self.real_user = real_user
        self.real_pass = real_pass
        self.last_login = last_login


def create_account(guild_id: int, real_user: str, real_pass: str, group: str = None) -> SSOAccount:
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


def get_account(guild_id: int, real_user: str) -> SSOAccount or None:
    with base.get_session() as session:
        account = session.query(SSOAccount).options(
            sqlalchemy.orm.joinedload(SSOAccount.groups),
            sqlalchemy.orm.joinedload(SSOAccount.tags),
            sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one_or_none()
        if account:
            session.expunge(account)
    return account


def find_account_by_username(username: str, guild_id: int = None) -> SSOAccount or None:
    """Find an account by username."""
    with base.get_session() as session:
        # Try to find the account directly by real_user
        account = session.query(SSOAccount).options(
            sqlalchemy.orm.joinedload(SSOAccount.groups),
            sqlalchemy.orm.joinedload(SSOAccount.tags),
            sqlalchemy.orm.joinedload(SSOAccount.aliases)).filter(
            SSOAccount.real_user == username
        ).one_or_none()

        if account:
            session.expunge(account)
            return account

        # If not found, try to find by alias
        alias = session.query(SSOAccountAlias).options(
            sqlalchemy.orm.joinedload(SSOAccountAlias.account)).filter(
            SSOAccountAlias.alias == username
        ).one_or_none()

        if alias:
            account = alias.account
            session.expunge(account)
            return account

        tagged_accounts = session.query(SSOTag).options(
            sqlalchemy.orm.joinedload(SSOTag.account)).filter(
            SSOTag.tag == username,
            SSOTag.guild_id == guild_id
        ).all()

        if tagged_accounts:
            accounts = [tagged_account.account for tagged_account in tagged_accounts]
            # Sort accounts by last_login
            accounts.sort(key=lambda account: account.last_login, reverse=True)
            session.expunge(accounts[0])
            return accounts[0]


def list_accounts(guild_id: int, group: str = None, tag: str = None) -> list[SSOAccount]:
    with base.get_session() as session:
        query = session.query(SSOAccount).filter(SSOAccount.guild_id == guild_id)
        if group:
            query = query.join(SSOAccount.groups).filter(SSOAccountGroup.group_name == group)
        if tag:
            query = query.join(SSOAccount.tags).filter(SSOTag.tag == tag)
        query = query.options(sqlalchemy.orm.joinedload(SSOAccount.groups),
                              sqlalchemy.orm.joinedload(SSOAccount.tags),
                              sqlalchemy.orm.joinedload(SSOAccount.aliases))
        accounts = query.all()
        session.expunge_all()
    return accounts


def update_account(guild_id: int, real_user: str, password: str) -> SSOAccount:
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one()
        account.real_pass = password
        session.commit()
        session.expunge(account)
    return account


def update_last_login(account_id: int) -> None:
    """Update the last_login timestamp for an account."""
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.id == account_id
        ).one_or_none()
        if account:
            account.last_login = datetime.datetime.now()
            session.commit()


def delete_account(guild_id: int, real_user: str) -> None:
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one()
        session.delete(account)
        session.commit()


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
        group = session.query(SSOAccountGroup).options(
            sqlalchemy.orm.joinedload(SSOAccountGroup.accounts)).filter(
            SSOAccountGroup.guild_id == guild_id,
            SSOAccountGroup.group_name == group_name).one()
        session.expunge_all()
    return group


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
        group = session.query(SSOAccountGroup).filter(
            SSOAccountGroup.guild_id == guild_id,
            SSOAccountGroup.group_name == group_name).one()
        group.group_name = new_name
        session.commit()
        group = session.query(SSOAccountGroup).options(
            sqlalchemy.orm.joinedload(SSOAccountGroup.accounts)).filter(
            SSOAccountGroup.id == group.id).one()
        session.expunge_all()
    return group


def delete_account_group(guild_id: int, group_name: str) -> None:
    with base.get_session() as session:
        group = session.query(SSOAccountGroup).filter(
            SSOAccountGroup.guild_id == guild_id,
            SSOAccountGroup.group_name == group_name).one()
        session.delete(group)
        session.commit()


def add_account_to_group(guild_id: int, group_name: str, real_user: str) -> None:
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one()
        group = session.query(SSOAccountGroup).filter(
            SSOAccountGroup.guild_id == guild_id,
            SSOAccountGroup.group_name == group_name).one()
        account.groups.append(group)
        session.commit()


def remove_account_from_group(guild_id: int, group_name: str, real_user: str) -> None:
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one()
        group = session.query(SSOAccountGroup).filter(
            SSOAccountGroup.guild_id == guild_id,
            SSOAccountGroup.group_name == group_name).one()
        account.groups.remove(group)
        session.commit()


class SSOAccessKey(base.Base):
    __tablename__ = "sso_access_key"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    guild_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)

    discord_user_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    access_key = sqlalchemy.Column(sqlalchemy_utils.EncryptedType(
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

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            'tag', 'account_id', name='uq_tag_account_id'),
    )

    def __init__(self, guild_id, tag, account_id):
        self.guild_id = guild_id
        self.tag = tag
        self.account_id = account_id


def tag_account(guild_id: int, real_user: str, tag: str) -> SSOTag or None:
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one_or_none()
        if account is None:
            return None
        tag = SSOTag(guild_id=guild_id, tag=tag, account_id=account.id)
        session.add(tag)
        session.commit()
        tag = session.query(SSOTag).options(
            sqlalchemy.orm.joinedload(SSOTag.account)).filter(
            SSOTag.id == tag.id).one()
        session.expunge_all()
    return tag


def untag_account(guild_id: int, real_user: str, tag: str) -> None:
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one()
        tag = session.query(SSOTag).filter(
            SSOTag.tag == tag,
            SSOTag.account_id == account.id).one()
        session.delete(tag)
        session.commit()


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
    with base.get_session() as session:
        account = session.query(SSOAccount).filter(
            SSOAccount.guild_id == guild_id,
            SSOAccount.real_user == real_user).one()
        alias = SSOAccountAlias(guild_id=guild_id, alias=alias, account_id=account.id)
        session.add(alias)
        session.commit()
        session.expunge_all()
    return alias


def get_account_alias(guild_id: int, alias: str) -> SSOAccountAlias:
    with base.get_session() as session:
        alias = session.query(SSOAccountAlias).filter(
            SSOAccountAlias.guild_id == guild_id,
            SSOAccountAlias.alias == alias).one()
        session.expunge(alias)
    return alias


def list_account_aliases(guild_id: int) -> list[SSOAccountAlias]:
    with base.get_session() as session:
        aliases = session.query(SSOAccountAlias).options(
            sqlalchemy.orm.joinedload(SSOAccountAlias.account)).filter(
            SSOAccountAlias.guild_id == guild_id).all()
        session.expunge_all()
    return aliases


def delete_account_alias(guild_id: int, alias: str) -> None:
    with base.get_session() as session:
        alias = session.query(SSOAccountAlias).filter(
            SSOAccountAlias.guild_id == guild_id,
            SSOAccountAlias.alias == alias).one()
        session.delete(alias)
        session.commit()


class SSOAuditLog(base.Base):
    """Audit log for SSO authentication attempts through the API."""
    __tablename__ = "sso_audit_log"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    timestamp = sqlalchemy.Column(sqlalchemy.DateTime, default=sqlalchemy.sql.func.now())
    
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

    # Additional information
    details = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)

    def __init__(self, username, ip_address=None, success=False, discord_user_id=None, 
                 account_id=None, guild_id=None, details=None):
        self.username = username
        self.ip_address = ip_address
        self.success = success
        self.discord_user_id = discord_user_id
        self.account_id = account_id
        self.guild_id = guild_id
        self.details = details


def create_audit_log(username, ip_address=None, success=False, discord_user_id=None, 
                     account_id=None, guild_id=None, details=None) -> SSOAuditLog:
    """Create an audit log entry for an SSO authentication attempt."""
    with base.get_session() as session:
        audit_log = SSOAuditLog(
            username=username,
            ip_address=ip_address,
            success=success,
            discord_user_id=discord_user_id,
            account_id=account_id,
            guild_id=guild_id,
            details=details
        )
        session.add(audit_log)
        session.commit()
        session.expunge(audit_log)
    return audit_log


def get_audit_logs_for_user_id(discord_user_id: int, limit=100, offset=0) -> list[SSOAuditLog]:
    """Get audit logs for a specific Discord user ID."""
    with base.get_session() as session:
        logs = session.query(SSOAuditLog).filter(
            SSOAuditLog.discord_user_id == discord_user_id
        ).order_by(SSOAuditLog.timestamp.desc()).limit(limit).offset(offset).all()
        session.expunge_all()
    return logs


def get_audit_logs(limit=100, offset=0, guild_id=None, username=None, success=None, 
                   since=None) -> list[SSOAuditLog]:
    """
    Get audit logs with optional filtering.
    
    Note: For failed authentication attempts, the guild_id field might be NULL in the database.
    When filtering by guild_id, we need to consider this special case.
    """
    with base.get_session() as session:
        query = session.query(SSOAuditLog).options(
            sqlalchemy.orm.joinedload(SSOAuditLog.account))
        
        # Apply filters if provided
        if guild_id:
            query = query.filter(SSOAuditLog.guild_id == guild_id)
        if username:
            query = query.filter(SSOAuditLog.username == username)
        if success is not None:
            query = query.filter(SSOAuditLog.success == success)
        if since:
            query = query.filter(SSOAuditLog.timestamp >= since)
            
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
            SSOAuditLog.timestamp >= time_threshold
        ).count()
        
        return count


def is_ip_rate_limited(ip_address: str, max_attempts: int = 10, minutes: int = 60) -> bool:
    """
    Check if an IP address should be rate limited based on failed login attempts.
    
    Args:
        ip_address: The IP address to check
        max_attempts: Maximum number of allowed failed attempts (default: 10)
        minutes: The number of minutes to look back (default: 60)
        
    Returns:
        True if the IP should be rate limited, False otherwise
    """
    if not ip_address:
        return False
        
    failed_attempts = count_failed_attempts(ip_address, minutes)
    return failed_attempts >= max_attempts
