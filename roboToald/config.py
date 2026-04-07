import configparser
from typing import List
import zoneinfo

CONFIG_FILENAME = "batphone.ini"

CONF = configparser.ConfigParser()
CONF.read(CONFIG_FILENAME)

DISCORD_TOKEN = CONF.get("discord", "token")
DISCORD_OAUTH_CLIENT_ID = CONF.get("discord", "oauth_client_id", fallback=None)
DISCORD_OAUTH_CLIENT_SECRET = CONF.get("discord", "oauth_client_secret", fallback=None)
TEST_GUILDS = []
for section in CONF.sections():
    if section.startswith("guild."):
        TEST_GUILDS.append(int(section.split(".")[-1]))

SKP_STARTTIME = CONF.getint("ds", "skp_starttime", fallback=8 * 60)
SKP_BASELINE = CONF.getint("ds", "skp_baseline", fallback=46)
SKP_MINIMUM = CONF.getint("ds", "skp_minimum", fallback=1)
SKP_PLATEAU_MINUTE = CONF.getint("ds", "skp_plateau_minute", fallback=20 * 60)

QUAKE_BONUS = CONF.getint("ds", "quake_bonus", fallback=150)
OFFHOURS_START = CONF.getint("ds", "offhours_start", fallback=1 * 60)  # Default 1am ET
OFFHOURS_END = CONF.getint("ds", "offhours_end", fallback=8 * 60)  # Default 8am ET
OFFHOURS_ZONE = zoneinfo.ZoneInfo(CONF.get("ds", "offhours_zone", fallback="America/New_York"))

WAKEUP_AUDIOFILE = CONF.get("wakeup", "audiofile", fallback="wakeup.wav")

# Per-guild raid / batphone-bot settings — parsed from [raid.<guild_id>] sections
RAID_SETTINGS: dict[int, dict] = {}
for _section in CONF.sections():
    if _section.startswith("raid."):
        _gid = int(_section.split(".", 1)[1])
        RAID_SETTINGS[_gid] = {
            "database_path": CONF.get(_section, "database_path", fallback=f"data/raids_{_gid}.db"),
            "batphone_channel_id": CONF.getint(_section, "batphone_channel_id", fallback=0),
            "tracking_channel_id": CONF.getint(_section, "tracking_channel_id", fallback=0),
            "create_event_channel_id": CONF.getint(_section, "create_event_channel_id", fallback=0),
            "uploaded_events_channel_id": CONF.getint(_section, "uploaded_events_channel_id", fallback=0),
            "event_category_ids": [
                int(x.strip()) for x in CONF.get(_section, "event_category_ids", fallback="").split(",") if x.strip()
            ],
            "register_channel_id": CONF.getint(_section, "register_channel_id", fallback=0),
            "send_batphone": CONF.getboolean(_section, "send_batphone", fallback=False),
            "create_channels": CONF.getboolean(_section, "create_channels", fallback=False),
            "allowed_reload_ids": [
                x.strip() for x in CONF.get(_section, "allowed_reload_ids", fallback="").split(",") if x.strip()
            ],
            "loot_channel_id": CONF.getint(_section, "loot_channel_id", fallback=0),
            "auto_attendance": CONF.getboolean(_section, "auto_attendance", fallback=False),
        }

# Per-guild EQdkp settings — parsed from [eqdkp.<guild_id>] sections
EQDKP_SETTINGS: dict[int, dict] = {}
for _section in CONF.sections():
    if _section.startswith("eqdkp."):
        _gid = int(_section.split(".", 1)[1])
        EQDKP_SETTINGS[_gid] = {
            "url": CONF.get(_section, "url", fallback=None),
            "host": CONF.get(_section, "host", fallback=None),
            "api_key": CONF.get(_section, "api_key", fallback=None),
            "adjustment_event_id": CONF.getint(_section, "adjustment_event_id", fallback=0),
        }

# Per-guild Pushsafer settings — parsed from [pushsafer.<guild_id>] sections
PUSHSAFER_SETTINGS: dict[int, dict] = {}
for _section in CONF.sections():
    if _section.startswith("pushsafer."):
        _gid = int(_section.split(".", 1)[1])
        PUSHSAFER_SETTINGS[_gid] = {
            "private_key": CONF.get(_section, "private_key", fallback=None),
            "guest_id": CONF.get(_section, "guest_id", fallback=None),
            "title": CONF.get(_section, "title", fallback="Batphone"),
        }

# Google Sheets settings (shared, not per-guild)
GOOGLE_SHEETS_CONFIG_FILE = CONF.get("google_sheets", "config_file", fallback=None)
GOOGLE_SHEETS_SPREADSHEET_ID = CONF.get("google_sheets", "spreadsheet_id", fallback=None)

ENCRYPTION_KEY = CONF.get("sso", "encryption_key")
API_CERTFILE = CONF.get("sso", "ssl_certfile", fallback=None)
API_KEYFILE = CONF.get("sso", "ssl_keyfile", fallback=None)
API_PORT = CONF.getint("sso", "port", fallback=8080)
API_HOST = CONF.get("sso", "host", fallback="127.0.0.1")
FORWARDED_ALLOW_IPS = CONF.get("sso", "forwarded_allow_ips", fallback="127.0.0.1")
FORWARDED_ALLOW_IPS = [ip.strip() for ip in FORWARDED_ALLOW_IPS.split(",")]
SSO_INACTIVITY_SECONDS = CONF.getint("sso", "inactivity_seconds", fallback=62)
RATE_LIMIT_MAX_ATTEMPTS = CONF.getint("sso", "rate_limit_max_attempts", fallback=10)
RATE_LIMIT_WINDOW_MINUTES = CONF.getint("sso", "rate_limit_window_minutes", fallback=30)
AUDIT_RETENTION_DAYS = CONF.getint("sso", "audit_retention_days", fallback=180)
AUDIT_ARCHIVE_DIR = CONF.get("sso", "audit_archive_dir", fallback="audit_archives")
DASHBOARD_BASE_URL = CONF.get("sso", "dashboard_base_url", fallback=None)
DASHBOARD_SUPER_ADMINS: set[int] = {
    int(x.strip()) for x in CONF.get("sso", "dashboard_super_admins", fallback="").split(",") if x.strip()
}
REQUIRE_KEYS_FOR_DYNAMIC_TAGS = CONF.getboolean("sso", "require_keys_for_dynamic_tags", fallback=False)
# Default asyncio thread pool for asyncio.to_thread / run_in_executor (Python default is min(32, cpu+4)).
ASYNCIO_DEFAULT_THREAD_POOL_MAX_WORKERS = CONF.getint("sso", "asyncio_default_thread_pool_max_workers", fallback=64)

WAKEUP_CHANNELS = {}
GUILD_SETTINGS = {}
for guild in TEST_GUILDS:
    GUILD_SETTINGS[guild] = {
        "member_role": CONF.getint(f"guild.{guild}", "member_role", fallback=0),
        "enable_random": CONF.getboolean(f"guild.{guild}", "enable_random", fallback=True),
        "enable_timer": CONF.getboolean(f"guild.{guild}", "enable_timer", fallback=True),
        "enable_batphone": CONF.getboolean(f"guild.{guild}", "enable_batphone", fallback=False),
        "enable_raidtarget": CONF.getboolean(f"guild.{guild}", "enable_raidtarget", fallback=False),
        "enable_sso": CONF.getboolean(f"guild.{guild}", "enable_sso", fallback=False),
        "sso_admin_roles": [int(x) for x in CONF.get(f"guild.{guild}", "sso_admin_roles", fallback="0").split(",")],
        "enable_raid": CONF.getboolean(f"guild.{guild}", "enable_raid", fallback=False),
        "enable_ds": CONF.getboolean(f"guild.{guild}", "enable_ds", fallback=False),
        "ds_tod_channel": CONF.getint(f"guild.{guild}", "ds_tod_channel", fallback=0),
        "tod_channel_id": CONF.getint(f"guild.{guild}", "tod_channel_id", fallback=0),
        "ds_schedule_channel": CONF.getint(f"guild.{guild}", "ds_schedule_channel", fallback=0),
        "ds_admin_role": CONF.getint(f"guild.{guild}", "ds_admin_role", fallback=0),
        "wakeup_channels": CONF.get(f"guild.{guild}", "wakeup_channels", fallback=None),
        "wakeup_exclusions": CONF.get(f"guild.{guild}", "wakeup_exclusions", fallback=None),
        "min_client_version": CONF.get(f"guild.{guild}", "min_client_version", fallback=None),
        "client_update_message": CONF.get(f"guild.{guild}", "client_update_message", fallback=None),
        "require_log": CONF.getboolean(f"guild.{guild}", "require_log", fallback=False),
        "block_rustle": CONF.getboolean(f"guild.{guild}", "block_rustle", fallback=False),
        "block_rustle_exempt_roles": [
            int(x) for x in CONF.get(f"guild.{guild}", "block_rustle_exempt_roles", fallback="").split(",") if x.strip()
        ],
        "raidtargets_endpoint": CONF.get(f"guild.{guild}", "raidtargets_endpoint", fallback=None),
        "raidtargets_authkey": CONF.get(f"guild.{guild}", "raidtargets_authkey", fallback=None),
        "raidtargets_soon_threshold": CONF.getint(
            f"guild.{guild}", "raidtargets_soon_threshold", fallback=48 * 60 * 60
        ),
    }
    if GUILD_SETTINGS[guild]["wakeup_channels"]:
        for x in GUILD_SETTINGS[guild]["wakeup_channels"].split(","):
            text_channel, voice_channel = x.split(":")
            WAKEUP_CHANNELS[int(text_channel)] = int(voice_channel)
    if GUILD_SETTINGS[guild]["wakeup_exclusions"]:
        GUILD_SETTINGS[guild]["wakeup_exclusions"] = [
            x.strip().lower() for x in GUILD_SETTINGS[guild]["wakeup_exclusions"].split(",")
        ]
    else:
        GUILD_SETTINGS[guild]["wakeup_exclusions"] = []
    # for item in CONF.items(f"guild.{guild}"):
    #     GUILD_SETTINGS[guild][item[0]] = item[1]


def get_tod_channel_id(guild_id: int) -> int:
    """Discord text channel ID for FTE / raid TOD relay from the login proxy (0 = disabled)."""
    return GUILD_SETTINGS.get(guild_id, {}).get("tod_channel_id", 0)


def get_member_role(guild_id: int) -> int:
    return GUILD_SETTINGS[guild_id].get("member_role")


def get_wakeup_exclusions(guild_id: int) -> List[str]:
    return GUILD_SETTINGS[guild_id].get("wakeup_exclusions", [])


def eqdkp_is_configured(guild_id: int) -> bool:
    """True if [eqdkp.<guild_id>] has both url and api_key (required for raid features)."""
    s = EQDKP_SETTINGS.get(guild_id) or {}
    return bool(s.get("url") and s.get("api_key"))


def guilds_for_command(command_name: str) -> List[int]:
    guild_list = []
    for guild_entry in GUILD_SETTINGS:
        if not GUILD_SETTINGS[guild_entry].get(f"enable_{command_name}", False):
            continue
        if command_name == "raid" and not eqdkp_is_configured(guild_entry):
            continue
        guild_list.append(guild_entry)
    return guild_list


def get_raidtargets_endpoint(guild_id: int) -> str | None:
    return GUILD_SETTINGS.get(guild_id, {}).get("raidtargets_endpoint")


def get_raidtargets_authkey(guild_id: int) -> str | None:
    return GUILD_SETTINGS.get(guild_id, {}).get("raidtargets_authkey")


def get_raidtargets_soon_threshold(guild_id: int) -> int:
    return GUILD_SETTINGS.get(guild_id, {}).get("raidtargets_soon_threshold", 48 * 60 * 60)


def raid_guild_ids() -> List[int]:
    """Guild IDs with [raid.<id>], enable_raid, and EQdkp (url + api_key) configured."""
    return [
        gid
        for gid in RAID_SETTINGS
        if GUILD_SETTINGS.get(gid, {}).get("enable_raid", False) and eqdkp_is_configured(gid)
    ]


def get_raid_setting(guild_id: int, key: str):
    return RAID_SETTINGS.get(guild_id, {}).get(key)


def get_eqdkp_setting(guild_id: int, key: str):
    return EQDKP_SETTINGS.get(guild_id, {}).get(key)


def get_pushsafer_setting(guild_id: int, key: str):
    return PUSHSAFER_SETTINGS.get(guild_id, {}).get(key)
