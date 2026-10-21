# Dedicated stock research authentication

Individual stocks are the primary research universe. A Codex-connected Robinhood
session is useful for interactive investigation, but its credential is not copied
into a worker. The standalone research client uses its own official browser grant.
Robinhood currently advertises only the trading-capable `internal` OAuth scope;
local schema/research facades restrict behavior and do not make a stolen token
intrinsically read-only. Live execution remains disabled.

## Fresh schema-only grant

On the trusted workstation, choose an absent directory under an owned mode-0700
parent and explicitly run:

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.schema_bootstrap \
  --oauth-store /absolute/private/oauth-stock-research
```

The owner completes Robinhood's official login and consent. The loopback callback
uses the existing PKCE/state protections and timeout. This path captures complete,
sanitized `tools/list` declarations using a facade without `call_tool`. It makes
no account, portfolio, review, placement or cancellation call. It writes no account
fingerprint and cannot prove account reconciliation.

Credential/client records are encrypted private files. The complete staged store
is published using a native no-clobber rename into its absent final destination
after success; unsupported platforms fail closed. Failures remove only new staging,
and cleanup failure cannot skip restoring the process umask. The existing grant
is preserved. The command emits only status,
artifact hash/count, booleans and issue-time lifetime metadata, never token values,
token hashes, provider exception text or OAuth URL parameters. Directory fsync is
required at publication. Failed or uncertain publication is not silently retried.

## Bounded official renewal

After reviewing this exact provider contract and completing the owner-authorized
browser grant, the operator can explicitly renew the dedicated research credential:

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.oauth_renewal \
  --oauth-store /absolute/private/oauth-stock-research
```

The command acquires a single-process store lease before reading credentials and
holds it through bounded HTTP cleanup. It fetches current fixed official protected
resource and authorization-server metadata, verifies the public client, atomically
persists `refresh_pending`, sends exactly one refresh POST, and commits the new
token plus absolute lifetime metadata in one encrypted record. It exposes no MCP
session, tool invocation, browser callback or account operation. No proxy settings,
redirects, fallback endpoints, registration or retries are enabled.

Unknown response outcomes and invalid responses leave the store denied pending
owner recovery. Never rerun by restoring an old refresh token or removing the pending
record. A failed atomic commit can leave either pending state or a complete new
generation; recovery never retries the old refresh token. Injected filesystem and
cancellation fixtures test these boundaries but do not prove physical power-loss
durability. The lock coordinates cooperating processes on one host, not store copies.

On 2026-10-21 the authorized dedicated grant completed one actual official refresh.
Its conservative absolute expiry was retained as 2026-10-29 18:45:38 UTC. A fresh
process then reused that encrypted generation without a callback and captured all
83 tool declarations, with schema artifact SHA-256
`d7e31092ac39b56350cac907769916f17bdd95d5cb89e3d4c1f1126e1ee8f1dc`.
Neither command invoked account, portfolio or order tools. This proves explicit
renewal and process-restart reuse at that checkpoint. Natural expiry, owner revocation,
long-running deployed access and account binding remain unverified.

Headless connections restore the persisted deadline without extending it, pin the
reviewed metadata, use wall/monotonic clock high-water checks and checkpoint observed
time. A known expired generation or unexpected 401 permits at most one guarded refresh
within the connection; legacy tokens without observed absolute lifetime do not silently
enter an interactive flow. Pending/denied stores fail before outbound traffic.

## Remaining authentication proofs

Successful browser authorization proves neither indefinite background access nor
refresh/revocation behavior. Explicit renewal, genuine issue-time expiry metadata,
single-owner persistence and separate no-browser restart were verified above.
Natural-expiry recovery, owner-revoked denial and the deployed worker still require
separate evidence.
Never force refresh through an invented fallback endpoint or replay old refresh
credentials. Existing legacy read-schema gates remain unchanged.

The reviewed selected-server stock-research declarations are a separate fixed
research-only tool profile. Writer, account,
portfolio and reconciliation operations must be denied independently at session
and transport boundaries. Current snapshots become available at receipt time;
financial period dates cannot be substituted for publication timestamps.
