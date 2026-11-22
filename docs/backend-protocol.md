# SSO Proxy Backend Protocol (moved)

The implementer guide for SSO backends now lives in the P99 Login Proxy repo:
**[p99-login-proxy `docs/backend-protocol.md`](https://github.com/eq-p99-tools/p99-login-proxy/blob/rust/docs/backend-protocol.md)**.

It covers the HTTP and WebSocket endpoints, every message shape, credential crypto, username resolution and access control outcomes, size caps, proxy gating, and verification.

The normative wire schema and fixtures live only there
([`schemas/`](https://github.com/eq-p99-tools/p99-login-proxy/tree/rust/schemas)); this repo keeps no copy.
`tests/test_ws_protocol_schema.py` validates this server against them from a p99-login-proxy checkout
(`P99_LOGIN_PROXY_DIR`, or a sibling `p99-login-proxy` directory).

roboToald is the reference backend. Its own deployment and operations notes stay in [`README_API.md`](../README_API.md).
