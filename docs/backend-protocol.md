# SSO Proxy Backend Protocol (Agent Implementer Spec)

Normative wire contract for a backend compatible with **P99 Login Proxy** (`p99-login-proxy`).  
Reference implementation: **robotoald** (`roboToald/api/server.py`, `roboToald/api/websocket.py`).

Language: **MUST** / **SHOULD** / **MAY**.  
Labels: **[proxy-required]** = current proxy breaks or skips SSO without it. **[reference]** = robotoald behavior; not strictly required for a minimal compatible backend unless marked proxy-required.

---

## 0. Agent brief

### Goal
Implement an HTTP + WebSocket API such that an unmodified P99 Login Proxy can: authenticate with an access key, receive an account name cache, request encrypted EQ credentials on login, and push heartbeat/location/FTE/death telemetry.

### Non-goals
- Speaking SOE/EQ UDP login protocol (proxy ↔ EQEmu only).
- Discord admin UX, dashboard cookies, slash commands (**[reference]** management plane).
- Matching robotoald’s Discord RBAC storage model exactly — only the **wire outcomes** matter for proxy compatibility.

### Canonical sources of truth (in order)
1. This document (implementer contract).
2. `schemas/ws-protocol.schema.json` + `schemas/fixtures/{inbound,outbound}/` — message envelope schema.
3. Proxy client: `p99_sso_login_proxy/ws_client.py`, `server.py` (SSO gate), `login_protocol.py` (DES).
4. Reference server: `roboToald/api/server.py`, `websocket.py`, `db/models/sso.py`.
5. `README_API.md` — narrative only; **do not trust over code** (known stale claims exist).

### Ordered implementation checklist
1. `GET /` health JSON.
2. `WS /ws/accounts`: accept → require `auth` ≤15s → validate key → send `full_state` → app-level `ping`/~30s.
3. Handle client: `pong`, `login_auth`, `heartbeat`, `update_location` (ignore unknown `type`).
4. `login_auth_response` with Base64 DES-CBC credentials (test vector below).
5. Push `delta` on account-tree changes (shape in §5).
6. Username resolution + access control such that only authorized names appear in `account_tree` and succeed `login_auth`.
7. Optionally `POST /auth` (HTTP plaintext fallback; **not** used by current proxy).
8. Optionally `fte` / `mob_death` (proxy sends; silent drop is OK for login compatibility).
9. Verify with §12.

---

## 1. Roles and topology

```
EQ Client --UDP SOE--> Login Proxy --WSS JSON--> SSO Backend
                           |
                           +--UDP--> EQEmu login server (rewritten credentials)
```

| Actor | Responsibility |
|---|---|
| Backend | Access-key auth, account tree, credential issue, telemetry ingest |
| Proxy | WS client, name-set SSO gating, DES splice into SOE Login packet |
| EQ client / login server | Out of scope |

Current proxy uses **WebSocket only** for SSO login (`login_auth`). It never calls `POST /auth`.

---

## 2. Transport

### Endpoints

| Method | Path | Proxy uses? | Notes |
|---|---|---|---|
| `GET` | `/` | No (ops) | Health |
| `POST` | `/auth` | **No** (current) | **[reference]** fallback; older clients |
| `WS` | `/ws/accounts` | **Yes** | Primary |
| `POST` | `/list_accounts`, `/heartbeat`, `/update_location` | No | **[reference]** returns 404; do not revive as required |

### URL derivation **[proxy-required]**
Proxy config `sso_api` (rstrip `/`):
- `https://host` → `wss://host/ws/accounts`
- `http://host` → `ws://host/ws/accounts`
- other → `wss://` + base + `/ws/accounts`

### TLS **[proxy-required]**
- Default: verify with **certifi** CA bundle.
- `sso_verify_tls=false` disables verify (emergency).
- Plain `ws://` allowed (no SSL context).

### Timeouts / reconnect **[proxy-required]**
| Constant | Value | Effect |
|---|---|---|
| Auth first-message wait | **15s** server-side | Else close 4001 |
| `login_auth` wait | `sso_timeout` default **10s** | Proxy treats as failure string |
| App ping interval | **30s** **[reference]** | Proxy replies `pong` |
| Proxy recv wait slice | 60s | Internal; not a protocol timeout |
| Reconnect backoff | 1s → 60s exponential | On drop |
| Auth failure park | Until user changes token/URL | No auto-retry loop |

On any disconnect, proxy sets `_connected=False`, cancels pending `login_auth`, and **clears account cache**. SSO rewriting stops until a new `full_state`.

---

## 3. Connection sequence **[proxy-required]**

```
Client                         Server
|-- WS upgrade --------------->|
|-- auth (JSON text) --------->|   MUST arrive within 15s
|                              |-- validate --|
|<-- error {detail} + close ---|   on failure
|<-- full_state ---------------|   on success; proxy sets connected=true
|   ... bidirectional ...      |
|<-- ping ---------------------|
|-- pong --------------------->|
|-- login_auth / heartbeat / update_location / fte / mob_death -->|
|<-- login_auth_response / delta / ping -------|
```

Invariants:
- First message MUST be `auth` with non-empty `access_key`.
- Proxy marks connected **only** after `full_state` (not after WS open, not after `auth` send).
- `login_auth` is refused client-side with `"WebSocket not connected"` until `full_state`.

---

## 4. Message catalog

Schema: `schemas/ws-protocol.schema.json` (draft 2020-12).  
Every message is a JSON object with discriminator `type`. Unknown properties: **MAY** appear; receivers **SHOULD** ignore. Unknown `type` after auth: **MUST** ignore (no close).

### 4.1 Direction summary

| `type` | Dir | Required fields (schema) |
|---|---|---|
| `auth` | C→S | `type`, `access_key`, `client_version` |
| `full_state` | S→C | `type` only in schema; see §4.2 for proxy-required fields |
| `delta` | S→C | `type`, `changes` |
| `login_auth` | C→S | `type`, `request_id`, `username` |
| `login_auth_response` | S→C | `type`, `request_id` (+ success or error fields) |
| `heartbeat` | C→S | `type`, `character_name` |
| `update_location` | C→S | `type`, `character_name` |
| `fte` | C→S | `type`, `mob`, `player`, `character_name`, `eq_log_time` |
| `mob_death` | C→S | `type`, `mob`, `eq_log_time`, `character_name` |
| `ping` | S→C (also C→S) | `type` |
| `pong` | either | `type` |
| `error` | S→C | `type` |

---

## 5. Wire shapes (copy/paste)

### 5.1 `auth` (C→S)

```json
{
  "type": "auth",
  "access_key": "ConcentrateRedundantCollar",
  "client_version": "1.4.5",
  "client_settings": {
    "log_enabled": true,
    "rustle_present": false
  }
}
```

| Field | Nullability | Notes |
|---|---|---|
| `access_key` | string, required | Proxy `USER_API_TOKEN` |
| `client_version` | string, required by schema; proxy always sends | Semver-ish compare vs guild min **[reference]** |
| `client_settings` | object, optional | If **omitted**, **[reference]** skips `require_log` / `block_rustle`. If present, failing values reject. Proxy sends `log_enabled` (bool); `rustle_present` only after detection ran. Extra keys ignored. |

### 5.2 `full_state` (S→C) **[proxy-required]**

Schema requires only `type`. For proxy compatibility you **MUST** send:

```json
{
  "type": "full_state",
  "account_tree": {
    "realbot01": {
      "aliases": ["myalias"],
      "tags": ["clr"],
      "characters": {
        "Zzzz": {
          "class": "Cleric",
          "bind": "poknowledge",
          "park": "veeshan",
          "level": 60,
          "items": {
            "seb": true, "vp": false, "st": null,
            "void": null, "neck": null, "thurg": null,
            "reaper": null, "brass_idol": null,
            "lizard": null, "pearl": null, "peridot": null,
            "mb3": null, "mb4": null, "mb5": null
          },
          "keys": { "seb": true, "vp": false, "st": null }
        }
      },
      "last_login": "2025-01-15T03:22:00+00:00",
      "last_login_by": "DisplayName",
      "active_character": null,
      "owned": true,
      "shared": false,
      "group_roles": ["Member"]
    }
  },
  "count": 1,
  "dynamic_tag_zones": ["seb", "vp", "st", "tov", "dn", "kael", "pog", "thurg", "ss", "fear", "vox", "naggy", "dain", "yeli", "zlandi", "trak"],
  "dynamic_tag_classes": ["bar", "brd", "bard", "clr", "cle", "cleric", "dru", "druid", "enc", "enchanter", "mag", "mage", "magician", "mnk", "mon", "monk", "nec", "necro", "necromancer", "pal", "pld", "paladin", "ran", "rng", "ranger", "rog", "rogue", "sk", "shadowknight", "sha", "shm", "sham", "shaman", "war", "warrior", "wiz", "wizard"]
}
```

#### Account tree entry fields

| Field | Type | Proxy uses for SSO gate? |
|---|---|---|
| map key (`real_user`) | string | **Yes** — added to name cache **as-is (not lowercased)** |
| `aliases[]` | string | Yes — lowercased into cache |
| `tags[]` | string | Yes — lowercased |
| `characters` keys | string | Yes — lowercased |
| `characters.*.class` | string enum | UI / display |
| `characters.*.bind` / `park` | string \| null | UI |
| `characters.*.level` | int \| null | UI |
| `characters.*.items` | object | UI |
| `characters.*.keys` | object | Legacy UI; **[reference]** optional duplicate of `seb`/`vp`/`st` |
| `last_login` | ISO-8601 string \| null | UI; **[reference]** null if year ≤ 1 |
| `last_login_by` | string \| null | UI |
| `active_character` | string \| null | UI |
| `owned` / `shared` | bool | UI metadata |
| `group_roles[]` | string | UI metadata |

**CharacterClass enum values (exact strings):**  
`Bard`, `Cleric`, `Druid`, `Enchanter`, `Magician`, `Monk`, `Necromancer`, `Paladin`, `Ranger`, `Rogue`, `ShadowKnight`, `Shaman`, `Warrior`, `Wizard`

#### `items` wire keys **[proxy-required]** for ingest; UI expects these names

| Key | Value | Meaning |
|---|---|---|
| `seb`, `vp`, `st` | bool \| null | Zone keys |
| `void`, `neck`, `thurg`, `reaper`, `brass_idol` | bool \| null | Flags |
| `lizard`, `pearl`, `peridot`, `mb3`, `mb4`, `mb5` | int ≥ 0 \| null | Stack counts |

`null` / omitted on `update_location` = leave DB column unchanged **[reference]**.

### 5.3 `delta` (S→C) **[proxy-required]** for live updates

```json
{
  "type": "delta",
  "changes": [
    {
      "action": "add",
      "entity": "account",
      "account": "newacct",
      "data": { "aliases": [], "tags": [], "characters": {}, "last_login": null, "last_login_by": null, "active_character": null, "owned": false, "shared": false, "group_roles": [] }
    },
    {
      "action": "remove",
      "entity": "account",
      "account": "oldacct"
    },
    {
      "action": "update",
      "entity": "account",
      "account": "realbot01",
      "fields": {
        "aliases": { "add": ["x"], "remove": ["y"] },
        "tags": { "add": [], "remove": [] },
        "group_roles": { "add": ["Officer"], "remove": [] },
        "characters": {
          "add": { "New": { "class": "Wizard", "bind": null, "park": null, "level": null, "items": {} } },
          "remove": ["Gone"],
          "update": { "Zzzz": { "class": "Cleric", "bind": "a", "park": "b", "level": 60, "items": {} } }
        },
        "last_login": "2025-01-15T03:22:00+00:00",
        "last_login_by": "Name",
        "active_character": "Zzzz"
      }
    }
  ]
}
```

| Diff field | Shape | Proxy applies on delta? |
|---|---|---|
| `aliases`, `tags` | `{add:[], remove:[]}` | **Yes** |
| `group_roles` | same | **No** (until next `full_state`) |
| `characters` | `add` map / `remove` list / `update` map of **full** char objects | **Yes** |
| `last_login`, `last_login_by`, `active_character` | scalar (incl. null) | **Yes** |
| `owned`, `shared` | — | **[reference]** `compute_diff` does **not** emit field diffs; only present on `add`/`full_state` |

**[reference]** debounce ~3s for heartbeat bursts; immediate push on successful login / admin RBAC changes.

### 5.4 `login_auth` / `login_auth_response` **[proxy-required]**

Request:
```json
{"type": "login_auth", "request_id": "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f", "username": "mytag"}
```

- `request_id`: opaque string; proxy uses `uuid4().hex`.
- `username`: proxy sends **already lowercased**.

Success:
```json
{
  "type": "login_auth_response",
  "request_id": "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f",
  "real_user": "realbot01",
  "encrypted_credentials": "qqIv/3uQ7ssYIp1Nv6kGw5uiXJoY4ou/"
}
```

Failure:
```json
{
  "type": "login_auth_response",
  "request_id": "6f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f",
  "error": "Authentication failed",
  "status": 401
}
```

Proxy resolution logic: if `error` truthy → fail with that string; else Base64-decode `encrypted_credentials` (empty → `None`) and take `real_user`. **`status` is ignored by proxy** but **SHOULD** be set for other clients.

| `status` **[reference]** | `error` string |
|---|---|
| 400 | `Character not found` / `Missing request_id or username` |
| 401 | `Authentication failed` |
| 410 | `Tag is empty (possibly temporarily, due to inactivity requirements)` |
| 500 | `Internal server error` |

### 5.5 Credential crypto **[proxy-required]**

| Param | Value |
|---|---|
| Plaintext | `real_user + "\0" + real_pass + "\0"` (ASCII/UTF-8 bytes as used by proxy `.encode()`) |
| Padding | Append `\0` to multiple of 8 |
| Cipher | DES-CBC |
| Key | 8 zero bytes |
| IV | 8 zero bytes |
| Encoding | Standard Base64 of ciphertext |

**Verified interop (2026-10):** robotoald encrypts via `cryptography` `TripleDES` with the 8-byte zero key; proxy uses Cryptodome `DES`. Ciphertexts match.

**Test vector:**  
`real_user=realbot01`, `real_pass=secret` →  
`encrypted_credentials = "qqIv/3uQ7ssYIp1Nv6kGw5uiXJoY4ou/"`

Proxy **splices** decoded bytes into the SOE Login packet; it does not re-encrypt. Wrong crypto → EQ login server rejects password.

**MUST NOT** put plaintext `real_pass` on the WebSocket.

### 5.6 Telemetry (C→S)

```json
{"type": "heartbeat", "character_name": "Zzzz"}
```

```json
{
  "type": "update_location",
  "character_name": "Zzzz",
  "park_location": "veeshan",
  "bind_location": "poknowledge",
  "level": 60,
  "items": { "seb": true, "vp": false }
}
```

- Schema lists `items` only. **[reference]** also accepts legacy top-level `keys`; merge with `items` winning.
- Proxy heartbeat interval: **20s** if log mtime within **30s**.
- Missing/inaccessible `character_name`: **MUST** ignore (no error, no close). Proxy may send local-only character names.

```json
{"type": "fte", "mob": "Cekenar", "player": "Toald", "character_name": "Zzzz", "eq_log_time": "Fri Jan 31 22:04:02 2025"}
{"type": "mob_death", "mob": "King Tormax", "eq_log_time": "Sat Feb 15 20:52:45 2025", "character_name": "Zzzz"}
```

`eq_log_time`: EQ log bracket form `Wed Jul 15 22:14:05 2026`.  
**[reference]** skew: reject if \|Δ\| > 24h; else minute+second within 60s around hour. Discord TOD side effects optional for proxy login compatibility.

### 5.7 Keepalive / error

```json
{"type": "ping"}
{"type": "pong"}
{"type": "error", "detail": "Access revoked"}
```

Proxy reads **only** `error.detail` (default `"Authentication failed"`). Schema allows `message`/`reason`; **MUST** set `detail` for proxy UI.

### 5.8 HTTP `POST /auth` **[reference]** / older clients

```
POST /auth
Content-Type: application/json
X-Client-Version: 1.4.5
```

```json
{"username": "mytag", "password": "<access_key>", "client_settings": {"log_enabled": true}}
```

| Status | Body |
|---|---|
| 200 | `{"real_user":"...","real_pass":"..."}` plaintext |
| 400 | `{"detail":"Character not found"}` |
| 401 | `{"detail":"Authentication failed"}` |
| 410 | tag-empty detail |
| 422 | version/settings detail |

### 5.9 `GET /`

```json
{"status": "ok", "service": "RoboToald API", "message": "API server is running"}
```

---

## 6. Auth model

### Access key
Opaque secret. Proxy sends as WS `auth.access_key` and (legacy) HTTP `password`. Not a cookie/JWT for this protocol.

### WS session
After `auth`, connection is bound to the key’s identity. Later messages do not resend the key. **[reference]** re-checks guild `enable_sso` on each `login_auth`.

### Close codes **[reference]** (send `error` then close)

| Code | Meaning |
|---|---|
| 4001 | Auth timeout / bad JSON |
| 4002 | First message not `auth`+`access_key` |
| 4003 | Bad key / rate limit / revoked / SSO disabled |
| 4004 | Discord not ready (~30s) |
| 4010 | Client version too old |
| 4011 | `client_settings` policy fail |

### Rate limit **[reference]**
- Config defaults: `rate_limit_max_attempts=10`, `rate_limit_window_minutes=30` (function default args say 20 — **config wins**).
- Counts failed audit rows with `rate_limit != false` for the IP (no `account_id` filter in current `count_failed_attempts`).
- Response: same as auth failure (WS 4003 / HTTP 401), **not** 429.
- HTTP IP: `_get_client_ip` prefers first `X-Forwarded-For` hop when header present.
- WS IP: TCP peer only.

---

## 7. Username resolution **[reference]** (required for tag UX)

Order (case-insensitive):

1. Account `real_user`
2. Character name
3. Alias
4. Static tag → inactive-only if `inactive_only=True` (login path); else 410 if empty
5. Dynamic tag `<zone_prefix><class_suffix>`

**Inactivity default:** `inactivity_seconds=62`.

**Tag sort key** (`_login_sort_key`): among candidates, `bucket = age//30` if age < 1200s else `1200`; sort `(-bucket, -level)`.

### Dynamic tag zone prefixes → park/bind keys

| Prefix | Zone keys |
|---|---|
| `seb`, `trak` | `sebilis`, `trakanon` |
| `vp` | `veeshan`, `skyfire` |
| `st` | `sleeper`, `eastwastes` |
| `tov` | `templeveeshan`, `westwastes` |
| `dn`, `zlandi` | `necropolis`, `westwastes` |
| `kael` | `kael`, `wakening` |
| `pog` | `growthplane`, `wakening` |
| `thurg`, `dain` | `thurgadina`, `thurgadinb` |
| `ss`, `yeli` | `skyshrine` |
| `fear` | `fearplane`, `feerrott` |
| `vox` | `everfrost`, `permafrost` |
| `naggy` | `lavastorm`, `soldungb` |

Optional **[reference]** `require_keys_for_dynamic_tags`: require `key_seb`/`key_vp`/`key_st` for `seb`/`trak`/`vp`/`st`.

### RBAC outcome **[proxy-required]**
`account_tree` / deltas **MUST** only include accounts the access key may use.  
**[reference]** access via: Discord role→group, owner, direct share, or admin role.

---

## 8. Proxy SSO gating (failure modes agents miss)

Proxy lowercases the EQ login username, then SSO-rewrites iff:

```
not PROXY_ONLY
and username not in SKIP_SSO_ACCOUNTS
and username not in LOCAL_ACCOUNT_NAME_MAP
and username not in LOCAL_CHARACTER_NAMES
and username in ALL_CACHED_NAMES
and USER_API_TOKEN set
```

`ALL_CACHED_NAMES` built from `full_state` as:
- account map keys **as-is** (NOT lowercased)
- aliases / tags / character names **lowercased**
- Cartesian product of `dynamic_tag_zones` × `dynamic_tag_classes` (only when both lists provided)

### Hard facts
1. **Account keys MUST be lowercase** (or otherwise match `username.lower()`). Reference stores `real_user` lowercased. Mixed-case keys will not SSO-gate.
2. **Dynamic tags drop after the first `delta`:** proxy `_apply_delta` calls `_rebuild_cache(tree)` without re-passing zone/class lists, so dynamic-tag names vanish from `ALL_CACHED_NAMES` until reconnect/`full_state`. Static `tags` / aliases / characters survive. Treat as open proxy bug; backends that need reliable dynamic-tag login SHOULD also expose those names as real `tags` or accept reconnect-only dynamic tags.
3. Before `full_state` or after disconnect: cache empty → no SSO rewrite (passthrough).
4. `login_auth` timeout (default 10s): proxy forwards original packet after logging failure (may still rewrite if partial — see `server.py`; on error_detail it still may forward without splice).

---

## 9. Happy paths (minimal)

### A. Connect
1. Proxy opens WS, sends `auth`.
2. Server validates → `full_state`.
3. Proxy `connected=true`, builds name cache.

### B. Login
1. EQ Login packet → proxy parses Combined(ACK+Login).
2. If gated: `login_auth{username}`.
3. Server resolves + authorizes → `login_auth_response` with ciphertext.
4. Proxy splices ciphertext → forwards to EQEmu.
5. **[proxy]** on bad-password LoginAccepted may retry original client credentials once (backend unaware).

### C. Play telemetry
1. `heartbeat` / `update_location` while logged in.
2. Server updates state → `delta` to subscribers.

---

## 10. Security MUST / MUST NOT

**MUST**
- Ciphertext-only credentials on WS.
- Generic denial strings for key/RBAC/rate-limit on HTTP 401.
- Filter trees/deltas to authorized accounts.
- Set `error.detail` before auth close.

**MUST NOT**
- Require EQ client password for resolution.
- Send plaintext password on WS.
- Change DES key/IV/padding without a coordinated proxy break.
- Close WS on bad heartbeat/location/unknown type.
- Depend on cookies for the proxy API.

---

## 11. Compatibility matrix

| Capability | Proxy-required | Reference-only |
|---|---|---|
| `WS /ws/accounts` + `auth` + `full_state` | ✓ | |
| DES `login_auth_response` | ✓ | |
| `delta` add/remove/update | ✓ for live UI/names | |
| App `ping`/`pong` | ✓ (proxy replies; server ping recommended) | 30s loop |
| `heartbeat` / `update_location` accept | ✓ tolerate | persist + delta |
| `POST /auth` | | ✓ |
| Discord RBAC / revocation / audit | | ✓ (wire outcomes still required) |
| `fte` / `mob_death` handling | ignore OK | TOD channel |
| Legacy character `keys` | ignore OK | emit flag |
| Close codes 4001–4011 | | ✓ (proxy mainly needs `error`+drop) |

---

## 12. Verification (how an agent proves compatibility)

1. **Schema:** validate every fixture under `schemas/fixtures/**` against `schemas/ws-protocol.schema.json` (see `tests/test_ws_protocol_schema.py`).
2. **Crypto unit:** encrypt `realbot01`/`secret` → Base64 MUST equal `qqIv/3uQ7ssYIp1Nv6kGw5uiXJoY4ou/`. Decrypt with DES-CBC zeros → same plaintext.
3. **WS smoke:**
   - Connect → no auth in 15s → 4001 + `error`.
   - Bad key → 4003 + `error.detail`.
   - Good key → `full_state` with lowercase account keys + dynamic tag lists.
   - `login_auth` → success ciphertext spliceable; unknown user → `error`+status 400; denied → 401; empty tag → 410.
   - `ping` → client `pong`; client `ping` → server `pong`.
   - Unknown `type` → connection stays open.
4. **Proxy smoke (manual/automated):** point proxy `sso_api` at backend, set token, confirm UI “Connected (Live)”, login with alias/tag, confirm rewrite (logs: `Auth rewrite successful`).
5. **Delta:** add/remove account via admin API; proxy cache updates; note dynamic-tag gating quirk (§8).
6. **Negative:** disconnect backend → proxy cache clears → SSO stops until reconnect.

---

## 13. Open questions (unresolved from code alone)

These are hard facts about ambiguity — resolve before inventing behavior:

| ID | Fact |
|---|---|
| Q1 | No protocol version field. Compatibility is additive JSON + `client_version` / `min_client_version` only. |
| Q2 | Schema `full_state` requires only `type`; proxy needs `account_tree` (+ dynamic lists for dynamic tags). Contract = proxy behavior, not schema required[]. |
| Q3 | `owned`/`shared` not field-diffed by `compute_diff`; ownership flips may not push until other fields change or reconnect. |
| Q4 | Proxy drops dynamic tags from name cache after first `delta` (§8). Backend cannot fix alone without also publishing static tags or changing proxy. |
| Q5 | Proxy does **not** vendor/validate `ws-protocol.schema.json` at runtime (contrary to some README claims). |
| Q6 | Rate-limit threshold: config default **10**; some docs say 20; `is_ip_rate_limited` default arg is 20 but callers pass config. |
| Q7 | HTTP XFF trust depends on deployment (`forwarded_allow_ips` / reverse proxy). Code always prefers XFF when header present. |
| Q8 | Guild multi-tenancy, Discord readiness (4004), and audit retention are reference architecture — a single-tenant backend MAY stub (e.g. never send 4004) if it still speaks the wire. |
| Q9 | Encoding of non-ASCII passwords/usernames in DES plaintext is unspecified beyond Python default `.encode()` (UTF-8). Stick to ASCII for EQ accounts. |

---

## 14. Source map

| Topic | Path |
|---|---|
| Schema | `schemas/ws-protocol.schema.json` |
| Fixtures | `schemas/fixtures/` |
| WS + HTTP | `roboToald/api/server.py` |
| Deltas / tree | `roboToald/api/websocket.py` |
| Resolution / items map | `roboToald/db/models/sso.py` |
| Proxy WS client | `p99-login-proxy/p99_sso_login_proxy/ws_client.py` |
| Proxy SSO gate / splice | `p99-login-proxy/p99_sso_login_proxy/server.py` |
| DES helpers | `p99-login-proxy/p99_sso_login_proxy/login_protocol.py` |
