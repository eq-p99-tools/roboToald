# WebSocket protocol schema

**Machine-readable wire contract** for `WS /ws/accounts` messages exchanged between the P99 Login Proxy and this SSO API.

| Artifact | Role |
|---|---|
| [`ws-protocol.schema.json`](ws-protocol.schema.json) | Normative JSON Schema (draft 2020-12) for message envelopes |
| [`fixtures/`](fixtures/) | One example per message type (inbound = server→client, outbound = client→server) |
| [`../docs/backend-protocol.md`](../docs/backend-protocol.md) | **Additive** agent/human implementer guide (flows, crypto, RBAC, checklists). Does **not** replace this schema; must not diverge from it. |

Validate fixtures and live shapes with `tests/test_ws_protocol_schema.py`.
