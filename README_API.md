# RoboToald API Reference

> **Note:** This documentation is primarily AI-generated from the source code and may contain inaccuracies. Always verify behavior against the actual implementation.

The API serves the [P99 SSO Login Proxy](https://p99loginproxy.net) client. It provides authentication for shared EQ accounts and real-time account data streaming.

**The WebSocket (`/ws/accounts`) is the primary interface.** The login proxy connects via WebSocket for account listing, heartbeats, location updates, login authentication, and real-time delta pushes. `POST /auth` remains available as a fallback HTTP endpoint; newer clients perform login authentication over the WebSocket via `login_auth` messages. The only other public HTTP route is `GET /` (health check). Account listing, heartbeats, and location updates are WebSocket-only.

## Concepts

### Access Keys

Each Discord user in a guild has a unique access key -- a random multi-word passphrase (e.g. `ConcentrateRedundantCollar`) generated from word lists (verb + adjective + noun, 14-24 characters). The key is stored encrypted in the database, bound to exactly one `(guild_id, discord_user_id)` pair. It serves as the authentication credential for all API operations.

### Account Tree

The primary data structure returned by the API is the `account_tree` -- a dictionary keyed by account username, containing everything the client needs to know about each accessible account:

```json
{
  "<real_user>": {
    "aliases": ["string", ...],
    "tags": ["string", ...],
    "characters": {
      "<character_name>": {
        "class": "Cleric",
        "bind": "zone_key_or_null",
        "park": "zone_key_or_null",
        "level": 60,
        "keys": {
          "seb": true,
          "vp": null,
          "st": false
        }
      }
    },
    "last_login": "2025-01-15T03:22:00+00:00",
    "last_login_by": "DiscordDisplayName",
    "active_character": "CharName_or_null"
  }
}
```

Field details:

| Field | Type | Description |
|---|---|---|
| `aliases` | `string[]` | Alternative names that resolve to this account |
| `tags` | `string[]` | Tag names this account belongs to (shared across multiple accounts for round-robin) |
| `characters` | `object` | Map of character name to character details |
| `characters.*.class` | `string` | `CharacterClass` enum value: `Bard`, `Cleric`, `Druid`, `Enchanter`, `Magician`, `Monk`, `Necromancer`, `Paladin`, `Ranger`, `Rogue`, `ShadowKnight`, `Shaman`, `Warrior`, `Wizard` |
| `characters.*.bind` | `string?` | Zone key where the character is bound (null if unknown) |
| `characters.*.park` | `string?` | Zone key where the character is parked (null if unknown) |
| `characters.*.level` | `int?` | Character level (null if unknown) |
| `characters.*.keys` | `object` | `seb`, `vp`, `st`: each `true` (has key), `false` (confirmed no), or `null` (unknown) |
| `last_login` | `string?` | ISO 8601 UTC timestamp of last login. Null if never logged in. Accounts with `last_login` before epoch year 2 are treated as never-logged-in. |
| `last_login_by` | `string?` | Discord display name of the user who last logged in |
| `active_character` | `string?` | Character name from the most recent active heartbeat session, or null if no active session |

### Dynamic Tags

Dynamic tags are computed zone+class combinations not stored in the database. They are the Cartesian product of zone prefixes and class suffixes:

**Zone prefixes** (each maps to one or more internal zone keys):

| Prefix | Zone keys |
|---|---|
| `seb` | `sebilis`, `trakanon` |
| `trak` | (same as `seb`) |
| `vp` | `veeshan`, `skyfire` |
| `st` | `sleeper`, `eastwastes` |
| `tov` | `templeveeshan`, `westwastes` |
| `dn` | `necropolis`, `westwastes` |
| `kael` | `kael`, `wakening` |
| `pog` | `growthplane`, `wakening` |
| `thurg` | `thurgadina`, `thurgadinb` |
| `ss` | `skyshrine` |
| `fear` | `fearplane`, `feerrott` |
| `vox` | `everfrost`, `permafrost` |
| `naggy` | `lavastorm`, `soldungb` |
| `dain` | (same as `thurg`) |
| `yeli` | (same as `ss`) |
| `zlandi` | (same as `dn`) |

**Class suffixes** (multiple suffixes map to the same class):

| Suffixes | Class |
|---|---|
| `bar`, `brd`, `bard` | Bard |
| `clr`, `cle`, `cleric` | Cleric |
| `dru`, `druid` | Druid |
| `enc`, `enchanter` | Enchanter |
| `mag`, `mage`, `magician` | Magician |
| `mnk`, `mon`, `monk` | Monk |
| `nec`, `necro`, `necromancer` | Necromancer |
| `pal`, `pld`, `paladin` | Paladin |
| `ran`, `rng`, `ranger` | Ranger |
| `rog`, `rogue` | Rogue |
| `sk`, `shadowknight` | ShadowKnight |
| `sha`, `shm`, `sham`, `shaman` | Shaman |
| `war`, `warrior` | Warrior |
| `wiz`, `wizard` | Wizard |

Example: `vpclr` = Cleric parked in Veeshan's Peak or Skyfire Mountains.

When `require_keys_for_dynamic_tags` is `true` in `[sso]` in `batphone.ini` (default `false`), dynamic tag resolution for `seb`/`trak`, `vp`, and `st` prefixes additionally requires the matching character key flag (`key_seb`, `key_vp`, or `key_st`) to be `true`. Other zone prefixes are unchanged.

### Inactivity Threshold

An account is considered "inactive" if its `last_login` is older than `inactivity_seconds` (default 62 seconds) ago. This is used by tag and dynamic tag resolution to avoid assigning an account that is currently in use. The login proxy sends heartbeats at a shorter interval to keep the session alive.

### RBAC Model

Access is determined by Discord roles:

```
User's Discord Roles
    -> SSOAccountGroup (where role_id matches any user role)
    -> account_group_mapping (junction table)
    -> SSOAccount
```

The check is a single query: join `account_group_mapping` with `SSOAccountGroup`, filter by `account_id IN (requested_ids)` and `role_id IN (user_role_ids)` and `guild_id = guild_id`. The returned set of account IDs is the accessible subset.

### Session Tracking

Heartbeats create or extend `SSOCharacterSession` rows. A session is a contiguous series of heartbeats for the same character. If no heartbeat arrives within `inactivity_seconds`, the session is considered ended and a new heartbeat starts a new session. The most recent active session per account determines the `active_character` field in the account tree.

When a heartbeat arrives, any active sessions for the same Discord user on *different* accounts are expired (their `last_seen` is set to the inactivity threshold). This ensures a user shows as active on only one account at a time.

---

## `POST /auth`

Authenticate with an access key and receive real EQ credentials. This is called by the login proxy when EverQuest connects to the login server.

### Request

```
POST /auth
Content-Type: application/json
X-Client-Version: 1.2.0       (optional, compared against guild min_client_version)
```

```json
{
  "username": "string",
  "password": "string",
  "client_settings": {
    "log_enabled": true,
    "rustle_present": false
  }
```

| Field | Type | Required | Description |
|---|---|---|---|
| `username` | `string` | yes | Account name, alias, tag, character name, or dynamic tag |
| `password` | `string` | yes | The user's access key |
| `client_settings` | `object?` | no | Client state for guild policy enforcement. Older clients that omit this entirely are allowed through (use `min_client_version` to close this loophole). |
| `client_settings.log_enabled` | `bool` | no | Whether EQ logging is enabled |
| `client_settings.rustle_present` | `bool` | no | *(internal use)* |

### Authentication Flow

The server processes the request in this order:

1. **Rate limit check.** Count failed attempts from client IP (from `request.client.host` -- note: `/auth` does not read `X-Forwarded-For`, unlike other endpoints) in the last 30 minutes. If >= 20, reject with 401.

2. **Access key lookup.** Look up `password` in `SSOAccessKey` table. If not found, log an audit entry and reject with 401.

3. **Client version check.** If the guild has `min_client_version` set, compare `X-Client-Version` header (defaults to `0.0.0` if absent) using semver-ish parsing (dot-separated integers; pre-release suffix sorts below release). If below minimum, reject with 422 and the `client_update_message` (or a default message).

4. **Client settings validation.** If `client_settings` is present, check guild policies:
   - If `require_log` is set and `log_enabled` is `false`: reject with 422.
   - If `block_rustle` is set and `rustle_present` is `true` (and user lacks exempt roles): reject with 422.

5. **Username resolution.** Resolve `username` to an account by trying each method in order:
   1. Direct account name (`SSOAccount.real_user`, case-insensitive)
   2. Character name (`SSOAccountCharacter.name`, case-insensitive)
   3. Alias (`SSOAccountAlias.alias`)
   4. Tag (`SSOTag.tag`) -- if multiple accounts share the tag, filter to inactive accounts only (see Inactivity Threshold), then sort by a bucketed login-age key with character level as tiebreaker. If all tagged accounts are active, raise 410.
   5. Dynamic tag -- parse zone prefix and class suffix, query for characters of the matching class whose `bind_location` or `park_location` is in the zone key set, joined to accounts with `last_login` older than the inactivity threshold. Sort by the same login-age + level key. If no matches, raise 410.
   - If no method resolves, reject with 400.

6. **RBAC check.** Verify the Discord user has access to the resolved account (see RBAC Model above). If not, log an audit entry and reject with 401.

7. **Success.** Update `last_login` and `last_login_by` on the account. Notify all WebSocket clients for the guild (triggers delta pushes). Log a success audit entry. Return the real credentials.

### Tag Sort Algorithm

When a tag or dynamic tag matches multiple accounts, the selection algorithm is:

1. Filter to inactive accounts only (last_login older than `inactivity_seconds`).
2. Compute a sort key for each account: `(-bucket, -max_character_level)` where:
   - If the account was logged in less than 20 minutes ago: `bucket = age_seconds // 30` (higher = older = preferred)
   - If the account was logged in 20+ minutes ago: `bucket = 0` (all equivalent)
3. Sort ascending (lowest sort key = most preferred = oldest login, then highest level as tiebreaker).
4. Pick the first account.

### Response

**200 OK:**
```json
{
  "real_user": "actual_username",
  "real_pass": "actual_password"
}
```

**400 Bad Request:** `{"detail": "Character not found"}` -- username could not be resolved to any account.

**401 Unauthorized:** `{"detail": "Authentication failed"}` -- invalid access key, access denied, rate limited, or revoked. All failures return the identical body to prevent information leakage.

**410 Gone:** `{"detail": "Tag is empty (possibly temporarily, due to inactivity requirements)"}` -- tag or dynamic tag resolved but all matching accounts are currently active.

**422 Unprocessable Entity:** `{"detail": "<human-readable reason>"}` -- client version too old, or client settings fail guild policy. The `detail` explains what the user needs to fix.

### Side Effects

On success:
- `SSOAccount.last_login` set to current time
- `SSOAccount.last_login_by` set to the Discord user's display name in the guild
- `SSOAuditLog` entry created with `success=True`
- WebSocket delta push triggered for all clients in the guild

On failure:
- `SSOAuditLog` entry created with `success=False` and the failure reason (except for "account not found" which is not logged)

---

## `WS /ws/accounts`

WebSocket endpoint for real-time account data. This is the primary interface for the login proxy after initial authentication.

### Connection Protocol

```
1. Client connects to ws[s]://<host>:<port>/ws/accounts
2. Server accepts the WebSocket connection
3. Client sends auth message (must arrive within 15 seconds)
4. Server validates credentials and guild policies
5. Server sends full_state message
6. Bidirectional message exchange begins (heartbeats, location updates, pings, deltas)
```

### Auth Message (client -> server)

Must be the first message, sent within 15 seconds of connection. Must be valid JSON.

```json
{
  "type": "auth",
  "access_key": "string",
  "client_version": "1.2.1",
  "client_settings": {
    "log_enabled": true,
    "rustle_present": false
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `string` | yes | Must be `"auth"` |
| `access_key` | `string` | yes | The user's access key |
| `client_version` | `string` | no | Client version for `min_client_version` enforcement (defaults to `"unknown"` for logging, `"0.0.0"` for comparison) |
| `client_settings` | `object?` | no | Same semantics as `POST /auth` |

### Auth Validation

1. Parse JSON. If unparseable or times out (>15s), close with 4001.
2. Check `type` is `"auth"` and `access_key` is present. If not, close with 4002.
3. Look up access key. If invalid, close with 4003.
4. Wait for Discord client to be ready (up to 30 seconds). If still not ready, close with 4004.
5. Check `min_client_version`. If below minimum, close with 4010.
6. Validate `client_settings` against guild policies. If rejected, close with 4011.

Before closing, the server sends an error message: `{"type": "error", "detail": "<reason>"}`.

### Full State (server -> client, on successful auth)

Sent immediately after successful authentication. Contains the complete set of accounts the user can access.

```json
{
  "type": "full_state",
  "account_tree": { ... },
  "count": 42,
  "dynamic_tag_zones": ["vp", "st", "tov", ...],
  "dynamic_tag_classes": ["bar", "brd", "bard", "clr", ...]
}
```

| Field | Type | Description |
|---|---|---|
| `type` | `string` | Always `"full_state"` |
| `account_tree` | `object` | See Account Tree section above |
| `count` | `int` | Number of accounts in the tree |
| `dynamic_tag_zones` | `string[]` | Available zone prefixes for dynamic tags |
| `dynamic_tag_classes` | `string[]` | Available class suffixes for dynamic tags |

The `account_tree` is filtered to only accounts the user has access to via RBAC. The full tree for a guild may contain accounts the user cannot see.

### Client -> Server Messages

All messages are JSON objects with a `type` field. Unknown types are silently ignored.

#### Ping

```json
{"type": "ping"}
```

Server replies with `{"type": "pong"}`.

#### Heartbeat

Updates `last_login` on the character's account and records/extends a session. Triggers a delta push to all WebSocket clients in the guild.

```json
{
  "type": "heartbeat",
  "character_name": "CharName"
}
```

Side effects:
- `SSOAccount.last_login` and `last_login_by` updated
- `SSOCharacterSession` created or extended (extends if a session exists with `last_seen` within the inactivity threshold)
- Active sessions for this Discord user on other accounts are expired
- Delta push to all guild clients

If `character_name` is missing or doesn't resolve to an account, the message is silently ignored (no error sent).

#### Update Location

Updates a character's bind/park location and level. Also updates `last_login`, records a session, and triggers a delta push.

```json
{
  "type": "update_location",
  "character_name": "CharName",
  "bind_location": "zone_key",
  "park_location": "zone_key",
  "level": 60,
  "keys": { "seb": true, "vp": false, "st": false }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `character_name` | `string` | yes | Character to update |
| `bind_location` | `string?` | no | New bind zone key (only updated if present) |
| `park_location` | `string?` | no | New park zone key (only updated if present) |
| `level` | `int?` | no | New level (only updated if present and non-null) |
| `keys` | `object?` | no | Zone key flags from inventory parsing (only sent when present). Each field is optional; if omitted for a key, that column is not updated. |

When `keys` is present, each boolean field maps to `SSOAccountCharacter.key_seb`, `key_vp`, or `key_st` (Sebilis, Veeshan's Peak, Sleeper's Tomb). `true`/`false` updates the column; `null` or missing sub-field leaves that column unchanged.

Side effects (same as heartbeat, plus):
- `SSOAccountCharacter.bind_location`, `park_location`, and/or `level` updated
- If `keys` is present, `key_seb` / `key_vp` / `key_st` updated per the rules above

RBAC is checked: the message is silently ignored if the user doesn't have access to the character's account.

#### Login Auth

Performs the same credential lookup as `POST /auth` but over the existing WebSocket connection, avoiding a new TCP/TLS handshake per login. The access key, rate limiting, revocation, client version, and client settings are already validated at WebSocket connection time. The server only performs account resolution, RBAC check, and audit logging.

```json
{
  "type": "login_auth",
  "request_id": "unique_string",
  "username": "alias_or_tag_or_character"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `string` | yes | Must be `"login_auth"` |
| `request_id` | `string` | yes | Client-generated unique ID for correlating the response |
| `username` | `string` | yes | Account name, alias, tag, character name, or dynamic tag to resolve |

The server replies with a `login_auth_response` message (see below).

### Server -> Client Messages

#### Ping

Sent every 30 seconds as an application-level keepalive:

```json
{"type": "ping"}
```

The client should reply with `{"type": "pong"}` (optional but recommended).

#### Pong

Reply to a client ping:

```json
{"type": "pong"}
```

#### Login Auth Response

Reply to a `login_auth` request. Contains either the encrypted credentials or an error. The real password is never sent in plaintext; instead the server DES-CBC encrypts the credentials and returns a base64-encoded blob the client splices directly into the login packet.

**Success:**
```json
{
  "type": "login_auth_response",
  "request_id": "same_as_request",
  "real_user": "actual_username",
  "encrypted_credentials": "<base64-encoded DES-CBC ciphertext>"
}
```

**Error:**
```json
{
  "type": "login_auth_response",
  "request_id": "same_as_request",
  "error": "human-readable reason",
  "status": 401
}
```

| Field | Type | Description |
|---|---|---|
| `request_id` | `string` | Echoed from the request for correlation |
| `real_user` | `string?` | Real EQ account name (present on success, for logging/display) |
| `encrypted_credentials` | `string?` | Base64-encoded DES-CBC ciphertext of `username\0password\0` (present on success) |
| `error` | `string?` | Error detail (present on failure) |
| `status` | `int?` | HTTP-equivalent status code: 400 (character not found), 401 (auth failed / access denied), 410 (tag temporarily empty) |

Side effects on success are the same as `POST /auth`: `last_login` updated, audit log entry created, delta push triggered.

#### Delta

Sent whenever account data changes for the guild (triggered by logins, heartbeats, location updates, or admin actions via Discord commands). Only includes changes the user has access to see.

```json
{
  "type": "delta",
  "changes": [ ... ]
}
```

Each change object has an `action` and `entity` (always `"account"`):

**`add`** -- a new account appeared (e.g. user gained a role granting access, or admin created an account):

```json
{
  "action": "add",
  "entity": "account",
  "account": "real_user",
  "data": {
    "aliases": [...],
    "tags": [...],
    "characters": {...},
    "last_login": "...",
    "last_login_by": "...",
    "active_character": "..."
  }
}
```

**`remove`** -- an account was removed from the user's view:

```json
{
  "action": "remove",
  "entity": "account",
  "account": "real_user"
}
```

**`update`** -- one or more fields changed on an existing account:

```json
{
  "action": "update",
  "entity": "account",
  "account": "real_user",
  "fields": { ... }
}
```

The `fields` object only contains changed fields. Each field type has its own diff format:

**Scalar fields** (`last_login`, `last_login_by`, `active_character`) -- the new value:

```json
{
  "fields": {
    "last_login": "2025-01-15T03:22:00+00:00",
    "last_login_by": "DisplayName",
    "active_character": "CharName"
  }
}
```

**Set fields** (`aliases`, `tags`) -- additions and removals:

```json
{
  "fields": {
    "aliases": {"add": ["new_alias"], "remove": ["old_alias"]},
    "tags": {"add": [], "remove": ["removed_tag"]}
  }
}
```

**Dict field** (`characters`) -- additions, removals, and updates:

```json
{
  "fields": {
    "characters": {
      "add": {"NewChar": {"class": "Cleric", "bind": null, "park": null, "level": null}},
      "remove": ["DeletedChar"],
      "update": {"ExistingChar": {"class": "Cleric", "bind": "zone", "park": "zone", "level": 60}}
    }
  }
}
```

Each sub-key in `characters` is only present if there are changes of that type. Updated characters include the full character object (not a partial diff).

#### Delta Computation

The server maintains a `last_sent_state` for each WebSocket connection. When a notification fires, it:

1. Queries all accounts for the guild.
2. Filters to the accounts accessible by this connection's Discord user.
3. Builds a new `account_tree`.
4. Computes the diff between `last_sent_state` and the new tree.
5. If there are changes, sends the delta and updates `last_sent_state`.

If there are no changes for a particular connection, no message is sent.

#### Error

Sent before closing the connection due to a server-side issue:

```json
{"type": "error", "detail": "reason string"}
```

### Close Codes

| Code | Meaning |
|---|---|
| `4001` | Auth timeout (>15s) or unparseable JSON payload |
| `4002` | First message was not `{"type": "auth", "access_key": "..."}` |
| `4003` | Access key not found in database |
| `4004` | Discord client not ready after 30s wait (server still initializing) |
| `4010` | Client version below guild `min_client_version` |
| `4011` | Client settings rejected by guild policy (`require_log`, `block_rustle`) |

---

## HTTP endpoints (non-WebSocket)

### `GET /`

Health check.

```json
{"status": "ok", "service": "RoboToald API", "message": "API server is running"}
```

Returns `"status": "warning"` if the Discord client hasn't been injected yet.

`POST /auth` is documented earlier in this file; it remains the HTTP fallback for credential resolution.

---

## Authentication and Authorization

### IP Resolution

- `POST /auth` uses the first value of `X-Forwarded-For` when the connecting client is a trusted proxy (`forwarded_allow_ips` in `batphone.ini`); otherwise `request.client.host`.
- WebSocket connections use `websocket.client.host` (the immediate TCP peer; `X-Forwarded-For` is not applied to WebSocket in this server).
- Configure `forwarded_allow_ips` in `batphone.ini` to control which proxy IPs uvicorn trusts for `X-Forwarded-For` on HTTP requests.

### Rate Limiting

Rate limiting is based on failed authentication attempts per IP address:

- **Threshold:** 20 failed attempts
- **Window:** 30 minutes (rolling)
- **Counting:** Only counts failures where `rate_limit != False` and `account_id IS NOT NULL` (plus legacy rows where `username = 'list_accounts'` from the removed HTTP list endpoint, if any remain in the window)
- **Response:** Same `401 Unauthorized` as any other auth failure (no `429` status code, to avoid information leakage)
- **Clearing:** An admin can clear the rate limit for an IP via `/sso_admin reset_rate_limit`, which sets `rate_limit = False` on all failed audit entries for that IP

### Revocation

User access can be revoked via `/sso_admin revocation add`. The API checks `SSORevocation` table for active revocations before allowing access. Revocations can be permanent (`expiry_days = 0`) or time-limited.

### Client Version Enforcement

When `min_client_version` is configured for a guild:
- `POST /auth`: compares `X-Client-Version` header (defaults to `0.0.0`) against minimum. Rejects with 422.
- WebSocket: compares `client_version` field in auth message (defaults to `0.0.0`) against minimum. Closes with 4010.

Version comparison is semver-ish: split on `.`, compare as integers. Pre-release suffixes (e.g. `1.2.0-rc1`) sort below the release they're attached to.

### Logging Requirement

When `require_log` is set for a guild, clients that report `log_enabled: false` in `client_settings` are rejected (HTTP 422 / WS close 4011). Clients that omit `client_settings` entirely are allowed through for backward compatibility.

### Audit Logging

Every authentication attempt is logged to `SSOAuditLog` with: timestamp, IP address, username attempted, success/failure, Discord user ID (if key was valid), guild ID, account ID (if resolved), rate_limit flag, and a detail string explaining the outcome.
