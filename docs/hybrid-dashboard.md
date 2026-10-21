# Hybrid research dashboard

The React + TypeScript Vite application in `dashboard/` is a local paper-research UI. It renders service evidence without seeded positions, charts, returns, opportunities, or claims of profitability. It cannot enable live trading, edit risk settings, submit broker orders, clear a kill switch, or authorize additional spending.

## Run and build

Use Node.js 20.19+ in the 20.x line, 22.12+ in 22.x, or >=24 (combined Vite 7 and Vitest 4 engine requirements):

```sh
cd dashboard
npm ci
npm test
npm run build
npm run dev
```

Development binds to `127.0.0.1:5173` and proxies `/api` to `http://127.0.0.1:8000`. The production build is `dashboard/dist/`; dependencies and generated assets are ignored by Git. Serve these assets from the same origin as the authenticated API. Production must use an appropriately protected local origin or HTTPS; do not expose the Vite development server. There are no external font, image, chart, analytics, or paid service requests.

Enter an existing **dashboard access token**, not a brokerage credential, in the password field. The value exists only in React memory and the Authorization header. It is not written to storage, a cookie, a URL, logs, or source files. Disconnect and reload clear the session; 401/403 responses clear the connected token and snapshot. No credential is bundled. This dashboard does not create or configure tokens.

## Frozen API boundary

- `GET /api/hybrid/snapshot`
- `POST /api/hybrid/controls` with exactly `{ "action": "pause" | "resume_research" | "kill" }`
- Both use `Authorization: Bearer <dashboard token>` and return the full snapshot.
- Fetches omit cookies, disallow redirects, bypass cache, and time out after 15 seconds.

Types and runtime checks are in `dashboard/src/api.ts`. Snapshots must report `mode: "paper"`, top-level and safety `live_enabled: false`, `authorization_status: "not_authorized"`, boolean pause/kill/paper-period states, valid decimal-string money and drawdown values (or the explicit unknown valuations described below), and the required collections. The extra-spending field must represent zero. Unsupported responses fail closed at the UI boundary. Backend authentication, state validation, serialization, cache headers, and controls remain authoritative and must independently enforce these rules.

Portfolio money fields: `starting_capital`, `equity`, `cash`, `buying_power`, `reserved_cash`, `tax_reserve`, `realized_gain`, `unrealized_gain`; `drawdown_pct` is a percentage. Equity, unrealized gain, drawdown, and allocations `long_term`/`tactical` may be explicitly `null` when current marks are missing. The UI preserves these unknowns as an em dash and shows `valuation_status: marks_unavailable`; it never substitutes zero. Undefined or malformed values are rejected. Cash, starting capital, buying power, reserved cash, tax reserve, realized gain, and the reserve allocation must remain known decimal strings. Allocations are USD amounts, not weights. Costs include `monthly_usd`, `annual_pct_of_starting_capital`, and zero `additional_budget_usd`. Values such as starting capital and monthly cost appear only when returned by the service; they have no client default.

Optional row fields rendered by the UI:

| Collection                 | Displayed keys                                          |
| -------------------------- | ------------------------------------------------------- |
| `research.opportunities`   | `symbol`, `strategy`, `status`, `reason`                |
| `research.sources`         | `name`, `status`, `as_of`                               |
| `research.strategy_status` | `name`, `status`, `reason`                              |
| `research.comparisons`     | `name`, `status`                                        |
| `safety.readiness`         | `name`, `status`, `reason`                              |
| `portfolio.positions`      | `symbol`, `quantity`, `market_value`, `unrealized_gain` |
| `portfolio.orders`         | `symbol`, `side`, `quantity`, `status`                  |
| `portfolio.lots`           | `symbol`, `quantity`, `cost_basis`, `acquired_at`       |
| `jobs`                     | `name`, `status`, `updated_at`                          |
| `reports`                  | `name`, `status`, `created_at`                          |

Rows are objects. Missing or non-scalar cells display an em dash. Monetary cells in record tables are service-supplied decimal strings with USD named in the heading. Research, source, comparison, readiness and report rows offer a disclosure showing their returned JSON fields, including additional evidence/detail fields. Supply only sanitized dashboard-safe evidence; never include credentials, account identifiers or production payloads in these rows. React escapes text, and source URLs are not turned into executable links. `research.regime` accepts a string or an object whose `name`/`status` is shown; `research.limitations` is a string array.

The client records retrieval time. Optional top-level `generated_at` is an ISO timestamp for source freshness. A snapshot is stale after 60 seconds since retrieval or source generation; a stale snapshot disables controls until refreshed. There is no background polling. Server time should be synchronized and the service should always provide fresh, truthful source timestamps. Loading prevents duplicate clicks, failed refresh retains labeled last-verified values and disables controls, and out-of-order responses after disconnect cannot restore the session. Resume is disabled while the kill switch is active; the service must also enforce this.

## Navigation and verification

Overview shows capital, costs, allocation and jobs. Research shows regime, sources, strategy evidence and limitations. Trades shows paper positions/orders/lots. Analytics shows returned gain/loss, reserves, drawdown, reports and comparisons. Settings provides research pause/resume, kill activation, readiness and session disconnect. All pages render truthful empty states before evidence arrives.

Nine deterministic Vitest tests cover rejection of live/invalid snapshots, decimal display, safe request transport, session-only credentials, navigation/control requests, disconnect clearing, authorization revocation, stale control denial, and explicit unknown valuation rendering. `npm test` and `npm run build` passed in the isolated dashboard worktree. A connected-backend acceptance pass remains necessary after integration.

Visual implementation uses local system typography, white surfaces, muted green controls, a desktop navigation rail and a mobile tab strip. Image generation was intentionally omitted under the no-added-spending constraint. Browser visual QA was blocked in this agent session: CUA exposed no browser surface, IAB returned “Browser is not available,” and native Chrome initialization timed out. No screenshot comparison or mobile browser verification is claimed. The implementation has responsive CSS breakpoints and semantic navigation/forms, visible keyboard focus, a skip link, scrollable data tables, live status/error announcements and reduced-motion support; these require rendered verification before release.

Next integration steps: serve the built assets on the API origin, run the backend with dashboard-safe sanitized snapshots, authenticate with a dashboard-only token, verify the five pages and research controls on desktop and mobile, and run the repository's broader regression checks. Deployment and live trading remain outside this implementation.

Dependency audit: `vitest` is pinned to patched version `4.1.11` to remove the vulnerable Vitest 3 mocker and tinypool dependency chain. The final full and production-only `npm audit --json` checks both reported zero vulnerabilities with this lockfile; no credentials or production service were needed for these checks.
