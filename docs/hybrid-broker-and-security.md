# Hybrid brokerage, security and activation boundary

The preferred future live broker remains Robinhood's official Trading MCP at
https://agent.robinhood.com/mcp/trading. No unofficial endpoints or authenticated
scraping are permitted. Capability discovery is scoped to the selected server's
actual tools/list schemas. Different installed connections are not interchangeable.

## Observed capability matrix, 21 October 2026

| Capability | Evidence | Release behavior |
|---|---|---|
| Account discovery and equity quote | Responded successfully during planning | No balances or positions inferred |
| Dedicated eligible cash account | Account discovery | No other account may be adopted |
| Prices, financials, filings, earnings, scanning | Exposed official schemas | Data completeness and history unqualified |
| Equity tax lots and specified-lot sales | Current schema declarations | Never infer execution from read access |
| Fractional execution | Market, regular session, eligible symbol, six decimals in current schema | Paper reservations respect constraints |
| Review/place/cancel/status | Declared tools, not verified order lifecycle | No live writer composed |
| UUID ref_id deduplication | Placement schema declaration | Stable logical id required; ambiguous submission must reconcile |
| News | Listed publicly, absent from inspected connection inventory | No invented news-tool calls |
| OAuth refresh token | Public authorization-server discovery | Lifetime, rotation, revocation and unattended eligibility unverified |
| Trade approval setting | Documentation says external MCP default may be off | Never substitutes for local authorization |

Official references: [onboarding](https://robinhood.com/us/en/support/articles/agentic-trading-overview/),
[trading/tools](https://robinhood.com/us/en/support/articles/trading-with-your-agent/),
[OAuth metadata](https://agent.robinhood.com/.well-known/oauth-authorization-server).

Tax-lot selection exclusions and order/session compatibility must be validated from
the selected runtime schema before any future proposed order. Settlement must obey
the account's actual restrictions and current broker state. The current application
does not transfer OAuth tokens from Codex to a service or assume an interactive
connection grants background authentication.

## Local security review

- API and controls require a private high-entropy bearer token; constant-time digest
  comparison, same-origin writes, no-store responses, CSP and frame restrictions.
- Token file mode 0600 inside owned mode 0700 state; no credentials in URLs or argv.
- Frontend authentication stays in memory. No Robinhood token enters the browser.
- No live-enable API, no broker writer in the service composition, no transfers.
- SQLite state is serialized transactionally, configuration-bound, hash chained and
  database append-only. Unknown state, corruption and configuration drift deny.
- Threshold targets and cumulative fills survive cancellation/restart. Conflicting
  fills fail instead of increasing exposure. Settlement proceeds are not immediate cash.
- Source text cannot modify risk, call tools, or enable execution. Values and source
  identities are bounded; unavailable inputs remain unavailable.
- Deployment must use nonroot, read-only, capability-free containers, private state,
  loopback publishing, bounded resources and no production-ledger/credential mounts.

A bounded deployed-runtime backup/restore and restart rehearsal passed; see the
release verification report. Remaining review items include sustained operation, licensed
source completeness, unattended broker authentication, real nonempty broker mappings,
and behavior under actual broker review/approval constraints. Automated static and
fixture checks do not establish these external facts.

## Future live activation checklist — no mandatory paper period

1. Exact strategy, data, policy, costs and code identities pass frozen qualification.
2. Current critical tests and security checks pass; recovery and kill controls work.
3. Intended Agentic account, permissions, buying power and reconciliation are verified.
4. Official authentication, refresh, expiry and revocation are verified on the host.
5. Review/order/fill/cancel mappings are verified without inventing broker semantics.
6. Deployment identity, monitoring, backups, limits and fail-closed startup are verified.
7. User separately authorizes exact account, capital, strategy versions and risk limits.

No credentials, deployment, successful test, market event or LLM output may grant
step 7. Initial live verification itself requires that authorization. Existing
legacy policies remain unchanged; this hybrid checklist adds no paper-duration gate.
