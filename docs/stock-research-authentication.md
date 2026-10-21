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
is renamed into its absent final destination after success; failures remove only
new staging. The existing grant is preserved. The command emits only status,
artifact hash/count, booleans and issue-time lifetime metadata, never token values,
token hashes, provider exception text or OAuth URL parameters. Directory fsync is
required at publication. Failed or uncertain publication is not silently retried.

## Remaining authentication proofs

Successful browser authorization proves neither indefinite background access nor
refresh/revocation behavior. Verify a separate no-browser connection, genuine
expiry provenance and correct official metadata before refresh, single-owner token
rotation, successful persistence, natural-expiry recovery and owner-revoked denial.
Never force refresh through an invented fallback endpoint or replay old refresh
credentials. Existing legacy read-schema gates remain unchanged.

Only after reviewing the selected-server stock-research declarations should the
worker receive a separate fixed research-only tool profile. Writer, account,
portfolio and reconciliation operations must be denied independently at session
and transport boundaries. Current snapshots become available at receipt time;
financial period dates cannot be substituted for publication timestamps.
