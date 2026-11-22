# RoboToald API: Reference Server Notes

> **Note:** This documentation is primarily AI-generated from the source code and may contain inaccuracies. Always verify behavior against the actual implementation.

**Implementing a compatible SSO backend, or looking for message shapes?**
The wire contract and implementer guide live in the P99 Login Proxy repo:
- **Wire shapes (normative):** [`schemas/ws-protocol.schema.json`](https://github.com/eq-p99-tools/p99-login-proxy/blob/rust/schemas/ws-protocol.schema.json) + [`schemas/fixtures/`](https://github.com/eq-p99-tools/p99-login-proxy/tree/rust/schemas/fixtures). This repo keeps no copy; `tests/test_ws_protocol_schema.py` loads them from a p99-login-proxy checkout.
- **Implementer guide:** [`docs/backend-protocol.md`](https://github.com/eq-p99-tools/p99-login-proxy/blob/rust/docs/backend-protocol.md): endpoints, every message and its fields, error and close codes, credential crypto, username resolution, dynamic tags, size caps, checklists.

This file covers only how roboToald implements and operates that protocol: storage, configuration, Discord integration, and admin routes. Prefer the schema and guide on any wire question.

The API serves the [P99 SSO Login Proxy](https://p99loginproxy.net). The WebSocket (`/ws/accounts`) is the primary interface; `POST /auth` remains as an HTTP fallback, and `GET /` is a health check. `POST /list_accounts`, `/heartbeat` and `/update_location` return 404 and log a deprecation warning.

## Access keys

Each Discord user in a guild has a unique access key: a random multi-word passphrase (e.g. `ConcentrateRedundantCollar`) generated from word lists (verb + adjective + noun, 14-24 characters). The key is stored encrypted in the database, bound to exactly one `(guild_id, discord_user_id)` pair, and is the credential for all API operations.

## Account tree internals

`build_account_tree` in `roboToald/api/websocket.py` builds the `account_tree` sent in `full_state` and diffed into `delta` (field list in the guide). Implementation details:

- Account keys are `SSOAccount.real_user`, stored lowercased.
- `characters.*.items` comes from the `key_*` / `item_*` columns on `SSOAccountCharacter` (`WIRE_KEY_TO_ATTR` in `db/models/sso.py`).
- Legacy `characters.*.keys` is emitted while `INCLUDE_LEGACY_KEYS_ON_ACCOUNT_TREE` in `api/websocket.py` is `True`.
- `group_roles` resolves the role IDs on the account's `SSOAccountGroup` rows to Discord role names; empty when roles cannot be resolved.
- `owned` / `shared` compare the viewer's Discord user ID with `owner_discord_user_id` and `SSOAccountUserShare` rows.
- Per-field "last updated" timestamps for keys and items (`*_updated_at` columns) are stored only in the database and never sent.
- Login notes are `SSOAccount.notes` and `SSOAccountCharacter.notes` (at most `NOTES_MAX_LENGTH` = 500 characters, trimmed, blank stored as `NULL`), edited with `/sso_owner ... notes_set` or the dashboard.

### Admin Dashboard Management API

The Discord OAuth-protected dashboard includes admin-only HTMX routes under `/admin/manage/*`. These routes are not public client APIs; they require the signed `admin_session` cookie issued by `/admin/callback`, a per-session CSRF token for every mutating request, and a `guild_id` that is within the logged-in admin's authorized SSO guilds.

Read partials render HTML fragments:

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/manage/partials/accounts` | Account management table and create/update/delete controls |
| `GET` | `/admin/manage/partials/groups` | SSO group management table |
| `GET` | `/admin/manage/partials/tags` | Account tag management table |
| `GET` | `/admin/manage/partials/aliases` | Account alias management table |
| `GET` | `/admin/manage/partials/characters` | Character management table |
| `GET` | `/admin/manage/partials/character_form` | Per-character edit form |
| `GET` | `/admin/manage/partials/shares` | Direct account share management table |

Mutating routes mirror `/sso_admin` operations for accounts, groups, tags, aliases, characters, and shares. Successful mutations call `ws_manager.notify_guild(guild_id, immediate=True)` so connected login-proxy clients receive fresh account deltas, and write an `SSOAuditLog` entry with `rate_limit=False` and `details` prefixed with `dashboard:`.

## Username resolution configuration

Resolution order, tag pick order and the dynamic tag tables are in the guide. roboToald specifics:

- Implemented by `find_account_by_username` in `db/models/sso.py`; the dynamic tag prefix and suffix maps come from `get_dynamic_tags`.
- `inactivity_seconds` (default 62) in `[sso]` in `batphone.ini` sets the inactivity threshold used by tag and dynamic tag resolution.
- `require_keys_for_dynamic_tags` in `[sso]` (default `false`): when `true`, the `seb`/`trak`, `vp` and `st` prefixes also require the matching `key_seb`, `key_vp` or `key_st` flag to be `true`.

### RBAC model

Access is determined by Discord roles:

```
User's Discord Roles
    -> SSOAccountGroup (where role_id matches any user role)
    -> account_group_mapping (junction table)
    -> SSOAccount
```

The check is a single query: join `account_group_mapping` with `SSOAccountGroup`, filter by `account_id IN (requested_ids)` and `role_id IN (user_role_ids)` and `guild_id = guild_id`. The returned set of account IDs is the accessible subset. Account owners, users with a direct share, and admin roles also have access.

### Session tracking

Heartbeats (and `update_location`) create or extend `SSOCharacterSession` rows. A session is a contiguous series of heartbeats for the same character. If no heartbeat arrives within `inactivity_seconds`, the session ends and the next heartbeat starts a new one. The most recent active session per account determines `active_character` in the account tree.

When a heartbeat arrives, any active sessions for the same Discord user on *different* accounts are expired (their `last_seen` is set to the inactivity threshold), so a user shows as active on only one account at a time.

---

## `POST /auth` implementation

`authenticate` in `roboToald/api/server.py`; credential resolution is shared with WebSocket `login_auth` through `_perform_login_auth`. Wire format and status codes are in the guide.

Processing order:

1. **Rate limit** (see Rate limiting below).
2. **Access key lookup** in `SSOAccessKey`. Not found: audit entry, 401.
3. **SSO enabled**: guild `enable_sso` in `batphone.ini`. Disabled: audit entry (`SSO disabled`), 401.
4. **Revocation** (`SSORevocation`). Revoked: audit entry, 401.
5. **Client version** against guild `min_client_version` (from `X-Client-Version`). Too old: 422 with `client_update_message` or a default message.
6. **Client settings** against guild `require_log` / `block_rustle` (users with exempt roles skip `block_rustle`). Rejected: 422.
7. **Username resolution** (`find_account_by_username(..., inactive_only=True)`).
8. **RBAC check**. Denied: audit entry (`Access denied`), 401.
9. **Success**: `last_login` / `last_login_by` updated, success audit entry, `ws_manager.notify_guild(guild_id, immediate=True)`.

"Character not found" (400) and empty tags (410) are not audited.

---

## `WS /ws/accounts` implementation

`websocket_accounts` and the `_ws_handle_*` functions in `roboToald/api/server.py`; connection management and deltas in `roboToald/api/websocket.py`.

### Auth phase

After the `auth` message: IP rate limit and key lookup (close 4003), wait up to 30s for the Discord client (close 4004), revocation (4003), guild `enable_sso` (4003, audited as `SSO disabled (WebSocket)`), `min_client_version` (4010), `client_settings` policy (4011). An invalid key writes an `Invalid access key (WebSocket)` audit entry. Each close is preceded by `{"type": "error", "detail": ...}` (`_ws_close`).

### Delta push timing

Each connection keeps `last_sent_state`. On a guild notification the server rebuilds each connection's RBAC-filtered tree, diffs it with `compute_diff`, and sends a `delta` only when something changed.

Bursts of `notify_guild` triggers (heartbeats, location and inventory updates) are **debounced** per guild (`WS_NOTIFY_DEBOUNCE_SEC`, about 3 seconds) into a single push. Successful SSO logins, Discord admin commands and dashboard changes push **immediately**.

`update_location` schedules a notification whenever the character exists and is accessible, because it also refreshes `last_login` and the session. `update_inventory` schedules one only when a stored column changed. `update_spellbook` never does.

### Message handlers

| Message | Handler effect |
|---|---|
| `heartbeat` | `heartbeat_and_session`: updates `SSOAccount.last_login` / `last_login_by`, creates or extends `SSOCharacterSession`, expires the user's sessions on other accounts |
| `update_location` | Same as `heartbeat`, then `update_account_character` with the present fields; `items` / `keys` merged by `merge_keys_and_items_message` and mapped by `merged_wires_to_character_kwargs`; `mark_key_from_park_zone` may set a key from the park zone |
| `update_inventory` | `parse_inventory_text` (`roboToald/inventory_parser.py`; tracked names in `INVENTORY_TRACKED_ITEMS` / `INVENTORY_COUNTED_ITEMS`, cap `MAX_INVENTORY_TEXT_BYTES`) then `update_account_character` with the full snapshot. Does not touch `last_login` or sessions. |
| `update_spellbook` | `parse_spellbook_text` (`roboToald/spellbook_parser.py`; caps `MAX_SPELLBOOK_TEXT_BYTES`, `MAX_SPELLBOOK_ENTRIES`, `MAX_SPELL_LEVEL`, `SPELL_NAME_MAX_LEN`) then `replace_character_spells`: deletes the character's `SSOCharacterSpell` rows, inserts one per spell (`spell_name`, `level`), sets `SSOAccountCharacter.spellbook_updated_at` |
| `fte` / `mob_death` | Skew check, reporter gate, `_tod_dedup`, then a post to the guild's `tod_channel_id` (below) |
| `login_auth` | `_perform_login_auth`, then `_des_encrypt_credentials` and `login_notes_for_account` on success |

All handlers ignore unknown or inaccessible characters and never reply, except `login_auth` and `ping`.

Any other message type is ignored without a reply, including `faction_hits`: roboToald does not store faction data.

#### Raid TOD relay (`fte`, `mob_death`)

`_verify_eq_log_time_skew` parses `eq_log_time` and compares it with the API host clock (naive local time): more than 24 hours apart is rejected; otherwise only minute and second are compared around the hour and must be within 60 seconds. Failures are dropped with a warning in the API log.

The reporter gate (`user_has_any_character_access`) requires the connected user to have access to at least one SSO character in the guild; `character_name` itself is logged but not access-checked, so local-only characters can report.

- `fte` posts `**FTE**: <mob> engages <player>! <t:…:T>`.
- `mob_death` posts `!tod <mob>, <M/D HH:MM:SS>`.

Both timestamps take **month, day and hour** from the current time in US Eastern (`America/New_York`) and **minute and second** from the parsed EQ log line.

##### Auto-attendance proposal

If `auto_attendance = true` is set in the guild's `[raid.<guild_id>]` config and EQdkp is configured, a valid `mob_death` that passes deduplication also triggers an auto-attendance suggestion posted to each open event channel whose target matches the mob name.

**Matching `mob` to raid targets:** The bot resolves the `mob` string to a `Target` row with `resolve_target` (same helper as slash commands). It first tries the usual “query is a substring of the stored name” match; if that finds nothing, it tries the reverse (the incoming string contains the stored `Target.name` or a `TargetAlias` name), preferring the longest match. That covers EQ log lines that use full mob names (e.g. `Dozekar the Cursed`) while the database stores short names (e.g. `dozekar`). For odd cases, add a **`TargetAlias`** row with the exact substring you need.

The suggestion is based on **SSO character session history** for the event window (`Event.created_at` → death time). Only users whose total session overlap with that window meets the minimum presence threshold are included:

> `threshold = min(event_duration_seconds × 0.5, 120)`

i.e. at least 50% of the event duration, or at least 2 minutes — whichever requirement is lower.

For each qualifying Discord user, the bot looks up their EQDKP characters (cached in memory for 1 hour). The character with the most overlap time becomes the "online character":

- If the online character belongs to the user in EQDKP, the line is `+<online_char>`.
- Otherwise (shared/bot account), the line is `+<eqdkp_char> on <online_char>`.

The suggestion message is posted to the event channel with **Apply** and **Ignore** buttons. The +lines are formatted as a copy-pasteable code block so a raid lead can also paste a subset manually. Clicking **Apply** inserts the Attendee records (with full EQDKP validation and deduplication matching `+Player` manual adds). Clicking **Ignore** dismisses the suggestion.

### Ping loop

`_ws_ping_loop` sends `{"type": "ping"}` every `WS_PING_INTERVAL` (30) seconds after a random initial delay, so connections opened together (for example after a restart) do not ping on the same tick.

---

## Authentication and authorization operations

### IP resolution

- `POST /auth` uses the first value of `X-Forwarded-For` when the connecting client is a trusted proxy (`forwarded_allow_ips` in `batphone.ini`); otherwise `request.client.host`.
- WebSocket connections use `websocket.client.host` (the immediate TCP peer; `X-Forwarded-For` is not applied to WebSocket in this server).
- Configure `forwarded_allow_ips` in `batphone.ini` to control which proxy IPs uvicorn trusts for `X-Forwarded-For` on HTTP requests.

### Rate limiting

Rate limiting is based on failed authentication attempts per IP address:

- **Threshold:** `rate_limit_max_attempts` (config fallback **10**; see `batphone.ini` `[sso]`)
- **Window:** `rate_limit_window_minutes` (config fallback **30**, rolling)
- **Counting:** Failed audit rows for the IP where `success` is false and `rate_limit != False` (`count_failed_attempts`, no `account_id` filter)
- **Response:** Same `401 Unauthorized` / close 4003 as any other auth failure (no `429` status code, to avoid information leakage)
- **Clearing:** An admin can clear the rate limit for an IP via `/sso_admin reset_rate_limit`, which sets `rate_limit = False` on all failed audit entries for that IP

### Revocation

User access can be revoked via `/sso_admin revocation add`. The API checks the `SSORevocation` table for active revocations before allowing access. Revocations can be permanent (`expiry_days = 0`) or time-limited.

### Client version enforcement

Set `min_client_version` (and optionally `client_update_message`) for a guild. `POST /auth` compares the `X-Client-Version` header and rejects with 422; the WebSocket compares `auth.client_version` and closes with 4010. A missing version compares as `0.0.0`. See `_parse_version` in `api/server.py`.

### Client settings policies

- `require_log`: clients that report `log_enabled: false` in `client_settings` are rejected (HTTP 422 / WS close 4011).
- `block_rustle`: clients that report `rustle_present: true` are rejected unless the user has an exempt role.

Clients that omit `client_settings` entirely are allowed through for backward compatibility; use `min_client_version` to close that gap.

### Audit logging

Every authentication attempt is logged to `SSOAuditLog` with: timestamp, IP address, username attempted, success/failure, Discord user ID (if key was valid), guild ID, account ID (if resolved), rate_limit flag, client version, and a detail string explaining the outcome.
