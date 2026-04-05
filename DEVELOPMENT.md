# RoboToald Development & Deployment Guide

> **Note:** This documentation is primarily AI-generated from the source code and may contain inaccuracies. Always verify behavior against the actual implementation.

## Prerequisites

- Python 3.11+
- A Discord bot token with the following intents: `guilds`, `guild_members`, `guild_messages`, `message_content`, `guild_voice_states`
- (Optional) TLS certificate and key for the API server

## Configuration

All configuration lives in `batphone.ini`. Copy `batphone.ini.example` to `batphone.ini` and fill in the values.

### `[discord]`

| Key | Description |
|---|---|
| `token` | Discord bot token |

### `[sso]`

| Key | Default | Description |
|---|---|---|
| `encryption_key` | *(required)* | Symmetric key for encrypting stored passwords and access keys |
| `ssl_certfile` | *(none)* | Path to TLS certificate. Omit to run without TLS (use a reverse proxy). |
| `ssl_keyfile` | *(none)* | Path to TLS private key |
| `host` | `127.0.0.1` | API bind address |
| `port` | `8080` | API bind port |
| `forwarded_allow_ips` | `127.0.0.1` | Comma-separated IPs trusted for `X-Forwarded-For` |
| `inactivity_seconds` | `62` | Seconds before an account is considered inactive (for tag round-robin and session tracking) |
| `require_keys_for_dynamic_tags` | `false` | When `true`, `seb`/`trak`, `vp`, and `st` dynamic tags require the matching character key flag |
| `asyncio_default_thread_pool_max_workers` | `64` | Max workers for each event loop’s default `ThreadPoolExecutor` (`asyncio.to_thread` / default `run_in_executor`). Python’s built-in default is `min(32, cpu+4)`. |

### `[ds]`

| Key | Default | Description |
|---|---|---|
| `skp_starttime` | `480` | Camp start-time threshold in minutes |
| `skp_baseline` | `46` | Baseline points per eligible period |
| `skp_minimum` | `1` | Minimum points awarded |
| `skp_plateau_minute` | `1200` | Minute at which point curve plateaus |
| `quake_bonus` | `150` | Flat bonus points granted to active members when `/ds tod is_quake:True` |
| `offhours_start` | `60` | Off-hours start (minutes past midnight, in `offhours_zone`) |
| `offhours_end` | `480` | Off-hours end (minutes past midnight) |
| `offhours_zone` | `America/New_York` | Timezone for off-hours calculation |

### `[wakeup]`

| Key | Default | Description |
|---|---|---|
| `audiofile` | `wakeup.wav` | Audio file played in voice channel on `@everyone` trigger |

### Per-guild `[guild.<id>]`

Each Discord guild (server) gets its own section keyed by guild ID.

| Key | Type | Default | Description |
|---|---|---|---|
| `member_role` | int | `0` | Role required for raid-target subscriptions |
| `enable_random` | bool | `true` | Enable `/random` |
| `enable_timer` | bool | `true` | Enable `/timer` |
| `enable_batphone` | bool | `false` | Enable `/batphone` |
| `enable_raidtarget` | bool | `false` | Enable `/raidtarget` |
| `enable_raid` | bool | `false` | Enable raid/event commands and handlers; requires `[raid.<id>]` and `[eqdkp.<id>]` with `url` and `api_key` |
| `enable_sso` | bool | `false` | Enable `/sso` and `/sso_admin` |
| `enable_ds` | bool | `false` | Enable `/ds` |
| `sso_admin_roles` | comma-separated ints | `""` | Discord role IDs that can use `/sso_admin` |
| `ds_tod_channel` | int | `0` | Channel for DS time-of-death and timer messages |
| `tod_channel_id` | int | `0` | Text channel where the login proxy relays FTE lines and `!tod` raid death messages from EQ logs |
| `ds_schedule_channel` | int | `0` | Channel for DS late-shift availability messages |
| `ds_admin_role` | int | `0` | Role that can use `/ds adjust` and `/ds set_spawn` |
| `wakeup_channels` | `text:voice,...` | *(none)* | Pairs of text:voice channel IDs for wakeup triggers |
| `wakeup_exclusions` | comma-separated | `""` | Skip wakeup if message contains any of these strings |
| `raidtargets_endpoint` | url | *(none)* | JSON endpoint for raid target data |
| `raidtargets_authkey` | string | *(none)* | Auth key for raid targets endpoint |
| `raidtargets_soon_threshold` | int | `172800` | Seconds before a raid window opens to consider it "soon" |
| `min_client_version` | string | *(none)* | Minimum P99 Login Proxy version; older clients are rejected |
| `client_update_message` | string | *(auto)* | Custom message shown when client is too old |
| `require_log` | bool | `false` | Require `Log=TRUE` in eqclient.ini |
| `block_rustle` | bool | `false` | *(see source)* |
| `block_rustle_exempt_roles` | comma-separated ints | `""` | Roles exempt from the above |

### Per-guild `[eqdkp.<id>]` (required for raid)

Raid commands (`/event`, `/rte`, `/loot`, `/history`), `$submit`, and event-channel message handlers (`+Player`, log paste, etc.) are only enabled when **`enable_raid` is true** and this section exists with **`url`** and **`api_key`** set. Optional keys include `host` and `adjustment_event_id`.

### Per-guild `[raid.<id>]`

Defines raid SQLite path, event categories, batphone channel, etc. See `batphone.ini.example`.

## Running

### Standalone

```bash
pip install -r requirements.txt
python batphone.py
```

On startup, the bot:
1. Initializes the SQLite database and runs any pending Alembic migrations.
2. Starts the FastAPI/uvicorn API server in a background thread.
3. Starts the Discord client (blocking).

### Docker

A `Dockerfile` and `docker-compose.yml` are provided. Mount `batphone.ini` and the database file into the container.

## Architecture

```
batphone.py (entry point)
    ├── db.base.initialize_database()    # SQLite + Alembic migrations
    ├── api.server.run_api_server()      # FastAPI in background thread
    │   ├── POST /auth                   # SSO login
    │   ├── WS /ws/accounts              # Real-time account data
    │   └── (deprecated HTTP endpoints)
    └── discord_client.DISCORD_CLIENT.run()
        ├── on_ready                     # Restore timers, DS state, subscriptions
        ├── on_message                   # Alert matching, wakeup triggers
        ├── on_button_click              # BUTTON_LISTENERS (prefix match on custom_id)
        └── slash commands               # /sso, /sso_admin, /ds, /batphone, /timer, /raidtarget, /random
```

The API server and Discord client share the same process. The API server runs on uvicorn in a daemon thread; the Discord client runs on the main thread. They communicate through the database and the `ws_manager.notify_guild()` call which pushes real-time updates to WebSocket clients.

## Directory Structure

```
roboToald/
├── batphone.py                         # Entry point
├── batphone.ini                        # Configuration (not committed)
├── batphone.ini.example                # Configuration template
├── requirements.txt                    # Python dependencies
├── alembic.ini                         # Alembic config
├── Dockerfile / docker-compose.yml
├── scripts/
│   └── import_accounts.py              # Bulk CSV import for SSO accounts
├── migrations/                         # Alembic migrations
│   ├── env.py
│   └── versions/
├── erd/                                # Database schema documentation
│   ├── sso_schema.md
│   ├── points_schema.md
│   ├── alert_schema.md
│   ├── timer_schema.md
│   └── subscription_schema.md
└── roboToald/                          # Main package
    ├── config.py                       # Reads batphone.ini
    ├── constants.py                    # Enums, timezone map
    ├── exceptions.py
    ├── utils.py
    ├── api/
    │   ├── server.py                   # FastAPI routes + WebSocket endpoint
    │   └── websocket.py                # WebSocket connection manager, delta protocol
    ├── db/
    │   ├── base.py                     # SQLite engine, session factory
    │   ├── migrations.py               # Alembic upgrade/stamp/create helpers
    │   └── models/
    │       ├── sso.py                  # SSO models + all helper functions
    │       ├── points.py               # Points models
    │       ├── alert.py                # Alert model
    │       ├── timer.py                # Timer model
    │       └── subscription.py         # Subscription model
    ├── discord_client/
    │   ├── __init__.py                 # Event handlers (on_ready, on_button_click)
    │   ├── base.py                     # Bot setup, on_message handler
    │   └── commands/
    │       ├── __init__.py             # BUTTON_LISTENERS registry
    │       ├── cmd_sso.py              # /sso and /sso_admin
    │       ├── cmd_ds.py               # /ds
    │       ├── cmd_ds_data.py          # /ds data subcommands
    │       ├── cmd_batphone.py         # /batphone
    │       ├── cmd_timer.py            # /timer
    │       ├── cmd_raidtarget.py       # /raidtarget
    │       └── cmd_random.py           # /random
    ├── raidtargets/
    │   └── rt_data.py                  # Raid target JSON parsing
    ├── alert_services/
    │   └── squadcast.py                # SquadCast webhook integration
    ├── wakeup/
    │   └── wakeup.py                   # Voice channel wakeup on @everyone
    └── words/                          # Word lists for access key generation
        ├── adjectives.list
        ├── nouns.list
        └── verbs.list
```

## Database

The bot uses SQLite (file: `alerts.db`) managed with Alembic for schema migrations. On startup, `base.initialize_database()` runs any pending migrations automatically.

Schema documentation with Mermaid ER diagrams:

- [SSO Schema](erd/sso_schema.md) -- accounts, groups, tags, aliases, characters, sessions, revocations, audit logs
- [Points Schema](erd/points_schema.md) -- Drusella Sathir camp-time tracking
- [Alert Schema](erd/alert_schema.md) -- BatPhone alerts
- [Timer Schema](erd/timer_schema.md) -- countdown timers
- [Subscription Schema](erd/subscription_schema.md) -- raid-window subscriptions

## API

See [README_API.md](README_API.md) for the full API reference (REST + WebSocket).

## Contributing

- When changing database models, create an Alembic migration: `alembic revision --autogenerate -m "description"`
- When changing models, update the corresponding schema doc in `erd/`.
- When changing API endpoints or the WebSocket protocol, update `README_API.md`.
- When adding or changing Discord commands, update the command reference in `README.md`.
- When changing configuration keys, update the config tables in this file.
