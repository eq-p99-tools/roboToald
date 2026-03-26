# RoboToald

> **Note:** This documentation is primarily AI-generated from the source code and may contain inaccuracies. Always verify behavior against the actual implementation.

RoboToald is a Discord bot for EverQuest guild management. It provides single sign-on (SSO) for shared game accounts, Drusella Sathir camp-time point tracking, raid alerts (BatPhones), timers, and raid-window subscription notifications.

## SSO System

The SSO system lets guild members log in to shared EverQuest accounts through the [P99 Login Proxy](https://p99loginproxy.net) without knowing the real credentials. Access is controlled by Discord roles.

### Core Concepts

- **Account** -- a real EQ login (username + password). Credentials are stored encrypted.
- **Group** -- links a Discord role to a set of accounts. Members with that role can access the accounts in the group.
- **Tag** -- a label applied to one or more accounts. Logging in with a tag picks the least-recently-used inactive account (round-robin).
- **Alias** -- an alternative name for a single account.
- **Character** -- a character name, class, bind/park location, and level tied to an account. You can log in by character name.
- **Dynamic Tag** -- a computed zone+class tag (e.g. `vpclr`, `stenc`). Logging in with a dynamic tag finds an inactive character of the matching class parked in the matching zone.
- **Access Key** -- a per-user secret generated via `/sso access get`. Used as the password in the login proxy.

### User Workflow

1. Run `/sso access get` to receive your access key (visible only to you).
2. Enter the access key as the password in the P99 Login Proxy.
3. In EverQuest, enter an account name, alias, tag, character name, or dynamic tag as the username.
4. Type literally any text as the password.

### Admin Workflow

Admins (users with roles listed in `sso_admin_roles`) manage the SSO system via `/sso_admin`:

1. **Create groups** linked to Discord roles (`/sso_admin group create`).
2. **Create accounts** with real credentials (`/sso_admin account create`), optionally assigning to a group.
3. **Add characters** to accounts (`/sso_admin character add`).
4. **Tag accounts** for round-robin login (`/sso_admin tag add`).
5. **Create aliases** for convenience (`/sso_admin alias create`).

## Drusella Sathir Points

Tracks camp time for the Drusella Sathir raid encounter. Members earn points based on how long they camp, and spend points to purchase urn drops.

- `/ds start` / `/ds stop` -- clock in/out of a camp session (supports backdating).
- `/ds tod` -- record a Drusella Sathir death (time of death).
- `/ds urn` -- record an urn purchase (spends points).
- `/ds points` -- check your point balance.
- `/ds status` -- see who is currently camping and the next expected spawn.
- `/ds audit` -- view point transaction history for a member.
- `/ds set_spawn` / `/ds adjust` -- admin-only overrides.

Points scale with time until next spawn, with configurable baseline and plateau.

### Data Commands

- `/ds data calendar` -- urn purchase calendar.
- `/ds data purchases` -- urn purchase history.
- `/ds data overview` -- historical camp overview.

## BatPhones (Alerts)

Register webhook-based alerts that fire when a message in a channel matches a regex pattern.

- `/batphone register` -- create an alert (channel, regex filter, webhook URL, optional role ping).
- `/batphone list` -- list your registered alerts.
- `/batphone help` -- setup tutorial (SquadCast integration).

When a matching message appears, the bot forwards it to the configured webhook URL and optionally pings the specified role.

## Timers

Simple one-time or repeating countdown timers.

- `/timer start` -- create a timer (name, duration, optional delay/repeat/timestamp).
- `/timer list` -- list active timers.
- `/timer show` -- show details for a timer.
- `/timer stop` -- cancel a timer.

## Raid-Window Subscriptions

Subscribe to raid target windows and get DM notifications when a window opens or is approaching.

- `/raidtarget subscribe` -- subscribe with a configurable lead time.
- `/raidtarget unsubscribe` -- unsubscribe.
- `/raidtarget subscriptions` -- list your subscriptions.

Subscriptions expire after 30 days and can be refreshed via the button on the notification.

## Command Reference

### `/sso` (user)

| Subcommand | Description |
|---|---|
| `help` | Usage tutorial |
| `access get` | Get your access key |
| `access reset` | Reset your access key |
| `account show <name>` | Show account details |
| `account list [group] [tag]` | List accounts you can access |
| `tag list` | List all tags |
| `tag show <tag>` | Show tag details |
| `group show <name>` | Show group details |
| `group list [role]` | List groups |
| `alias list` | List aliases |
| `character list [username]` | List characters |
| `reconcile` | Event-channel audit |

### `/sso_admin` (admin)

| Subcommand | Description |
|---|---|
| `help` | Admin setup tutorial |
| `account create / update / delete` | Manage accounts |
| `account list_no_characters` | Accounts missing characters |
| `group create / delete` | Manage groups |
| `group add / remove` | Add/remove accounts from groups |
| `tag add / remove / update` | Manage tags (incl. UI macros) |
| `alias create / delete` | Manage aliases |
| `character add / remove` | Manage characters |
| `audit account / user / failed / statistics` | Audit logs |
| `revocation add / list / remove` | Revoke/restore user access |
| `reset_rate_limit` | Clear rate limit for an IP |

### `/ds`

| Subcommand | Description |
|---|---|
| `start / stop` | Clock in/out of camp |
| `status` | Current camp status |
| `points [player]` | Point balance |
| `tod [is_quake]` | Record DS death (optional quake bonus) |
| `urn` | Record urn purchase |
| `adjust` | Adjust points (admin) |
| `set_spawn` | Override spawn time (admin) |
| `audit` | Audit logs |
| `data calendar` | Urn purchase calendar |
| `data purchases` | Purchase history |
| `data overview` | Camp overview |

### `/batphone`

| Subcommand | Description |
|---|---|
| `help` | Setup tutorial |
| `register` | Register a webhook alert |
| `list` | List your alerts |

### `/timer`

| Subcommand | Description |
|---|---|
| `start` | Start a timer |
| `list` | List timers |
| `show` | Show timer details |
| `stop` | Stop a timer |

### `/raidtarget`

| Subcommand | Description |
|---|---|
| `subscribe` | Subscribe to a raid target |
| `unsubscribe` | Unsubscribe |
| `subscriptions` | List your subscriptions (DM includes Refresh / Unsubscribe buttons) |

When a raid window is within your lead time, the bot DMs you with window times, how long until the subscription expires, and the same Refresh / Unsubscribe buttons. Button actions use encoded `custom_id` values (`action:target:guild_id`).

### `/lookup`

| Subcommand | Description |
|---|---|
| `user <member>` | List EQDKP characters for a Discord user (with race/class and DKP) |
| `character <name>` | Look up a character on EQDKP (shows linked Discord user, race/class, DKP, and all characters) |

Available in guilds with an `[eqdkp.<guild_id>]` section in `batphone.ini`.

### `/random`

| Parameter | Description |
|---|---|
| `end` (default 100), `start` (default 0) | Random integer in range |

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for setup, configuration, architecture, and contributing guidelines.
