# Manual Testing Plan: SSO Security Fixes

> This plan validates that the security fixes applied to the SSO system work correctly and that normal functionality is not broken.

## Prerequisites

- A running instance of RoboToald with the patched code
- Discord access with an account that has SSO admin role
- A test user's access key (use `/sso access get`)
- A tool for raw HTTP/WS requests (e.g. `curl`, Postman, or `websocat`)
- Access to the SQLite database (`alerts.db`) for inspection
- Access to server logs

## A. Regression: Normal Login Flow

### A1. Login via proxy (happy path)

1. Launch the login proxy with a valid access key
2. Connect to an account by name, alias, tag, and character name -- all four should work
3. Verify you land in-game and `last_login` / `last_login_by` update in `/sso_admin audit`

### A2. WebSocket connection (happy path)

1. Start the login proxy
2. Verify it connects via WebSocket and receives the account tree (check proxy logs for account list)
3. Leave it running a few minutes -- heartbeats should keep `active_character` populated
4. Verify location updates work (park a character, confirm it shows in the account tree on a second client or via `/sso_admin` inspection)

### A3. Access key reset

1. Run `/sso access reset` in Discord
2. Confirm the new key is returned (should now be 4 words instead of 3)
3. Confirm the old key no longer works (proxy should fail to connect)
4. Configure the proxy with the new key and confirm login works

### A4. Tag round-robin

1. Log in via a tag that maps to multiple accounts
2. Verify the least-recently-used inactive account is selected
3. Log in again immediately -- should get a different account (first one is still "active")

---

## B. Fix 1: Revocation Enforcement

### B1. Revoke blocks `/auth`

1. Using a test user, confirm `/auth` works normally (login succeeds)
2. Run `/sso_admin revocation add @testuser` in Discord
3. Attempt `/auth` again with the same access key -- expect 401
4. Check `/sso_admin audit` -- should show "Access revoked" detail

### B2. Revoke blocks WebSocket

1. With revocation still active, restart the login proxy
2. The proxy should fail to connect (WebSocket closed with code 4003)
3. Check server logs for "Access revoked" in close reason

### B3. Revoke blocks deprecated endpoints

1. With revocation still active, send a raw `POST /list_accounts` with the access key -- expect 401
2. Send a raw `POST /heartbeat` -- expect 401

### B4. Remove revocation restores access

1. Run `/sso_admin revocation remove @testuser`
2. Confirm `/auth` works again
3. Confirm WebSocket connects and receives full_state
4. Confirm login proxy works end-to-end

### B5. Timed revocation expiry

1. Run `/sso_admin revocation add @testuser 0` (permanent) -- confirm blocked
2. Run `/sso_admin revocation remove @testuser` -- confirm unblocked
3. *(Optional, if you can manipulate timestamps)* Create a 1-day revocation, verify it blocks now, then confirm it would expire after the period

---

## C. Fix 2: Rate Limiting Counts All Failures

### C1. Invalid keys trigger rate limit

1. Note the current rate limit settings (20 attempts / 30 minutes)
2. Send 20+ `POST /auth` requests with a completely wrong access key (e.g. `{"username": "anything", "password": "BadKey123"}`)
3. After 20 failures, the next request (even with a *valid* key) should return 401
4. Verify in the database: `SELECT COUNT(*) FROM sso_audit_log WHERE ip_address = '<your_ip>' AND success = 0 AND rate_limit != 0` -- should be >= 20

### C2. Rate limit clear works

1. While rate-limited, confirm login fails
2. Run `/sso_admin reset_rate_limit <your_ip>` in Discord
3. Confirm login works again immediately
4. Verify in the database: the failed entries now have `rate_limit = 0`

### C3. Valid usage doesn't trigger rate limit

1. After clearing, perform a few normal logins and list_accounts calls
2. Confirm no rate limiting occurs (successful requests don't count)

---

## D. Fix 3: Access Key Entropy

### D1. New keys are 4 words

1. Run `/sso access get` for a user who doesn't have a key yet (or `/sso access reset`)
2. Confirm the returned key has 4 capitalized word segments (e.g. `ConcentrateRedundantCollarVibrant` rather than `ConcentrateRedundantCollar`)
3. Confirm the key works for login

### D2. Existing 3-word keys still work

1. Use an existing user whose key was not reset
2. Confirm their old 3-word key still works for `/auth` and WebSocket

---

## E. Fix 4 & 5: Heartbeat RBAC

### E1. WebSocket heartbeat respects RBAC

1. Identify a character on an account the test user does NOT have role access to
2. While connected via WebSocket, send a raw heartbeat message: `{"type": "heartbeat", "character_name": "<unauthorized_char>"}`
3. Verify: `last_login` on the unauthorized account should NOT update
4. Verify: no session is created for that character (check `sso_character_session` table)
5. Verify: the WebSocket connection is not dropped (message is silently ignored)

### E2. WebSocket heartbeat works for authorized characters

1. Send a heartbeat for a character the user DOES have access to
2. Verify: `last_login` updates, session is created/extended, `active_character` shows in the account tree

### E3. HTTP heartbeat respects RBAC

1. Send a raw `POST /heartbeat` with access key and an unauthorized character name -- expect 401
2. Send the same request with an authorized character -- expect `{"status": "success"}`

---

## F. Fix 7: `/auth` Uses X-Forwarded-For

### F1. Without proxy (direct connection)

1. Send `POST /auth` directly (no `X-Forwarded-For` header)
2. Check audit log -- `ip_address` should be your actual IP

### F2. With X-Forwarded-For header

1. Send `POST /auth` with header `X-Forwarded-For: 1.2.3.4`
2. Check audit log -- `ip_address` should be `1.2.3.4` (if your IP is in `forwarded_allow_ips`) or your real IP (if not trusted)
3. **Important:** verify that rate limiting uses the same IP. Send 20 failures with `X-Forwarded-For: 5.6.7.8`, then confirm that requests from your real IP (without the header) are NOT rate-limited -- only `5.6.7.8` should be blocked

---

## G. Fix 9: Audit Log Details

### G1. Login with exact account name

1. Log in via `/auth` using the exact `real_user` account name
2. Check `/sso_admin audit` -- details should read `"Authentication successful"` (not empty)

### G2. Login via tag/alias

1. Log in via `/auth` using a tag or alias
2. Check audit -- details should read `"Authentication successful via tag/alias <name>"`

---

## H. Cleanup

1. Remove any test revocations: `/sso_admin revocation remove @testuser`
2. Clear any rate limits: `/sso_admin reset_rate_limit <ip>`
3. Reset any test access keys if needed

