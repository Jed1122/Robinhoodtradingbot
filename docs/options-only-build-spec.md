# MASTER CODEX PROMPT: ROBINHOOD OPTIONS-ONLY RESEARCH AND AUTOMATED TRADING SYSTEM

## 1. Assignment and authority

You are Codex operating inside my existing Robinhood trading project. Act as a principal options quantitative researcher, derivatives-risk engineer, broker-integration engineer, execution specialist, security engineer, and reliability/test lead.

Convert the original multi-asset system into an options-only system. Inspect and preserve useful existing implementation before adding or replacing anything. Build working software, not merely a proposal, dashboard, collection of stubs, or attractive backtest.

My objective is to identify and implement the options strategies with the strongest defensible, risk-constrained, after-cost economic performance that are actually executable through officially supported Robinhood interfaces. Do not assert that a strategy is the most profitable without evidence, guarantee returns, or optimize for trading activity.

The service should operate continuously for research, scheduling, reconciliation, monitoring, and reporting. Orders may execute only during sessions verified for the specific contract, account, broker interface, and order type. Do not equate 24/7 operation with 24/7 options-market access.

This request authorizes development and offline testing, not real-money trades, transfers, account upgrades, paid subscriptions, or paid infrastructure provisioning. Never place an order to test connectivity. Leave live trading disabled until I separately authorize activation after reviewing evidence and risk limits.

Read existing AGENTS.md files, relevant project instructions, source code, configuration, migrations, tests, audit reports, and deployment manifests. Do not erase unrelated work, reset Git history, delete risk evidence, or replace existing production state. Do not disturb an active deployed service or its protective monitoring while preparing the migration.

Create a migration map showing which original requirements are retained, replaced, retired, or blocked. In particular, replace equity share-sizing, crypto schedules, prediction-market modules, the blanket options prohibition, and the original $5 micro-live order assumption. Preserve auditability, official interfaces, deterministic execution, account isolation, staged authorization, testing, and DigitalOcean deployment.

If an external dependency blocks live integration, complete the independent engineering and testing that remains possible. Clearly label missing capabilities and evidence. Never fabricate API support, data, fills, test results, or deployment success.

## 2. Options-only scope

The only alpha-generating instruments are approved, listed options on permitted equities, ETFs, or indexes, subject to verified account and interface support.

Remove or disable standalone equity, crypto, futures, forex, and prediction-market trading strategies from the active runtime. Retain underlying-price data, corporate-action information, account-equity reads, and other inputs needed to analyze options.

Initial live-eligible structures, each requiring separate validation and approval:

- Fully paid long calls and long puts.
- Matched, same-expiration debit verticals.
- Matched, same-expiration credit verticals.
- Defined-risk iron condors only after the simpler structures pass validation.

A short option leg is permitted only inside an approved matched structure. Do not accidentally preserve the old long-only equity invariant in a way that prevents valid spreads, and do not interpret permission to sell a spread leg as permission for naked option selling.

Exclude naked calls or puts, unlimited-loss structures, ratio spreads with uncovered residuals, stock-replacement borrowing, Martingale sizing, averaging down, and loss-recovery escalation.

Exclude covered-call, cash-secured-put, and wheel strategies from this options-only mandate because their operating model includes deliberate stock ownership or acquisition. Calendars, diagonals, volatility-index options, earnings trades, and 0DTE strategies may be researched later but remain disabled in initial live configurations.

Unexpected shares or short-stock liabilities from exercise or assignment are incidents, not permission to start an equity strategy. Build detection and reconciliation. Any automated stock remediation requires a separately authorized, officially supported, narrowly scoped risk-reduction policy. Otherwise alert me and block new entries. Do not ignore the liability because the strategy is options-only.

## 3. Define profitability before selecting a strategy

Use this hierarchy:

1. Satisfy capability, capital, permission, liquidity, and risk constraints.
2. Demonstrate positive net expectancy using appropriately independent out-of-sample evidence.
3. Evaluate expected full-account growth and net dollar profit after operating costs, with uncertainty and tail-risk penalties.
4. Prefer the simpler, lower-turnover implementation when evidence does not clearly distinguish candidates.

Maintain separate estimates for:

- Trading P&L after execution costs and broker/exchange/regulatory fees.
- Operating profit after data, hosting, monitoring, subscriptions, and optional model usage.
- Opportunity cost versus an appropriate no-trade cash baseline.
- Optional tax scenarios, explicitly separated from verified trading results.

Build a cash-flow-based cost ledger. Spread and slippage costs already embedded in simulated or actual fills must not be subtracted again. Track opportunity cost separately unless the comparison expressly includes it.

Do not confuse premium collected with profit, high win rate with positive expectancy, high implied volatility with an exploitable edge, or return on collateral with return on total account equity. Do not assume option delta is the real-world probability of profit.

Evaluate realistic fill rates, adverse selection, capital lockup, drawdown duration, expected shortfall, gap losses, execution uncertainty, and strategy capacity. Reject a strategy whose attractive economics disappear under plausible costs or conservative fills.

Produce a strategy scorecard with evidence strength, net expectancy intervals, total-account returns, tail risks, capacity, operating cost, limitations, and GO/NO-GO reasons. Do not select a winner merely because the specification asks for a profitable bot.

## 4. Verify current official Robinhood capabilities

Public-documentation starting point, to verify again at implementation time:

https://agent.robinhood.com/mcp/trading

The official public options-tool list reviewed when this specification was prepared included:

get_option_level_upgrade_info
get_option_historicals
get_option_chains
get_option_instruments
get_option_quotes
get_option_positions
get_option_orders
review_option_order
cancel_option_order
place_option_order

These are discovery starting points, not proof that this Codex session, my account, or the deployed service has those capabilities. Introspect the actual tools and schemas before calling them. Do not invent parameters, response fields, authentication flows, order IDs, or hypothetical REST equivalents.

Verify and record:

- Official server ownership, endpoint, transport, supported authentication, and permissions.
- Eligible Agentic account and account allowlist.
- Options approval level and permitted structures.
- Cash versus limited-margin account behavior, settlement restrictions, and buying power.
- Single-leg versus multi-leg support, maximum legs, leg ratios, and opening/closing semantics.
- Net debit/credit conventions, quote units, tick rules, quantity rules, and supported time in force.
- Review, submission, cancellation, status, fill, pagination, and reconciliation capabilities.
- Real-time versus delayed quotes, quote timestamps, historical-data coverage, and data entitlements.
- Index-option, overnight-session, expiration-day, and contract-specific availability.
- Current fees, collateral treatment, rate limits, and restrictions.
- Exercise, assignment, settlement, corporate-action, and broker-initiated liquidation visibility.
- Whether documented unattended authentication and renewal work from the intended DigitalOcean runtime.

A working interactive Codex connection does not establish that a standalone daemon can authenticate or renew credentials safely. Validate the production authentication path separately using supported mechanisms. Never copy interactive session credentials into an unsupported background client.

Allow only official Robinhood tools and supported authentication. Prohibit reverse-engineered endpoints, unofficial mobile-API wrappers, browser automation, scraping, captured cookies, password automation, and authentication bypasses.

Create docs/capability-matrix.md and a machine-readable capability manifest with source URLs, retrieval times, schema hashes, account scope, verification level, limitations, and expiration/revalidation rules.

Separate PUBLICLY_DOCUMENTED, SESSION_DISCOVERED, ACCOUNT_VERIFIED, and RUNTIME_VERIFIED states. Missing critical support blocks only the affected live capability, not unrelated offline development. Record OPTIONS_LIVE_SUPPORTED=false until all required evidence exists.

## 5. Account isolation and capital feasibility

The original specification assumed approximately $100 and a $150 account-equity ceiling. Preserve those as unconfirmed configuration assumptions unless I explicitly replace them. They are not a statement of my current balance or permission to transfer funds.

Use an explicit account-ID allowlist. Mask identifiers in reports. Do not retrieve or retain unrelated personal-account details unnecessarily. An unexpected account, materially inconsistent account state, or equity above the authorized ceiling blocks new exposure.

Research hypothetical capital tiers of $100, $500, $1,000, $2,500, $5,000, $10,000, $25,000, and $50,000. Research tiers do not change live authorization or recommend a deposit.

For each tier report:

- Smallest admissible whole-contract position or complete spread unit.
- Theoretical payoff loss, operational stress loss, and required collateral.
- Remaining available cash after pending-order reserves and fees.
- Feasibility under the authorized per-trade and portfolio limits.
- Number of economically meaningful independent positions.
- Annual operating-cost drag and break-even assumptions.
- Evidence-based suitability for paper, shadow, micro-live, or no deployment.

Do not use fractional options, round zero permissible units up to one, move to illiquid contracts, select far-out-of-the-money lottery trades, or enable 0DTE merely to accommodate a small balance.

Example invariant: a $100 account with a 0.50% risk limit has a $0.50 risk budget. A hypothetical standard 100-multiplier option priced at $0.25 costs $25 before fees and does not fit that budget. Reject it. Do not silently reinterpret 0.50% as 50%.

Keep TECHNICAL_READINESS, ECONOMIC_READINESS, and LIVE_AUTHORIZATION separate. A small account may be technically connected yet unsuitable for any admissible live trade.

## 6. Options-specific risk policy and sizing

Use typed configuration. Store prices, premiums, strikes, fees, cash flows, realized P&L, and order quantities with exact decimal/integer semantics. Numerical analytics may use floating-point libraries with explicit finite-value checks, tolerances, units, and controlled conversion at financial boundaries.

Initial conservative engineering defaults, not claims of optimal investment allocation:

expected_starting_equity_usd: 100
live_account_equity_ceiling_usd: 150
risk_per_trade_fraction: 0.005
max_total_defined_payoff_loss_fraction: 0.05
max_underlying_group_defined_payoff_loss_fraction: 0.02
min_unencumbered_cash_fraction: 0.80
max_open_strategy_positions: 3
max_new_positions_per_session: 3
minimum_minutes_between_new_positions: 30
max_daily_loss_fraction: 0.02
max_weekly_loss_fraction: 0.05
max_peak_to_trough_drawdown_fraction: 0.10
margin_borrowing_enabled: false
uncovered_options_enabled: false
zero_dte_live_enabled: false
overnight_session_entries_enabled: false
live_trading_enabled: false

Lower existing authorized limits take precedence. Raising a capital or risk ceiling requires explicit operator approval. Document every intentional change from the original policy. Recognize the embedded economic leverage of options even when margin borrowing is prohibited.

For a standard matched structure with verified multiplier M, per-unit entry debit D, credit C, strike width W, and applicable cost reserve F:

- Long option or standard debit vertical payoff-risk baseline: D * M + F.
- Standard credit vertical payoff-risk baseline: (W - C) * M + F.
- Standard same-expiration iron condor baseline: evaluate its combined payoff; use the larger applicable wing loss less total credit where the verified structure permits that simplification.

Validate signs, ratios, expirations, deliverables, and settlement conventions before applying any shortcut. Reject impossible or inconsistent pricing. These formulas describe idealized matched payoff losses, not a guarantee against assignment, financing, execution, or operational losses.

Use a conservative risk denominator that includes relevant additional stress losses. Calculate the largest whole number of complete structure units satisfying ALL of:

- Per-trade risk budget.
- Remaining portfolio and correlated-group risk budgets.
- Available buying power and collateral rules.
- Cash reserve and fee reserve.
- Greek, scenario-loss, liquidity, and position-count limits.

Account for nonlinear fee schedules or collateral rules through validated integer search rather than an incorrect linear approximation. Pending entries reserve risk and buying power until their terminal state is confirmed.

A stop-loss trigger is an exit instruction, not a guaranteed maximum loss. Never size a long option using only a narrow intended stop when the full premium can be lost.

Use conservative liquidation marks for risk, official broker marks for reconciliation, and explain material differences. Daily and weekly loss calculations include realized and unrealized P&L, with deposits and withdrawals treated as external cash flows rather than trading performance.

## 7. Contract master and market data

Implement a point-in-time options instrument master containing broker contract ID, standardized identifier, underlying, call/put, strike, expiration, last trading timestamp, settlement timestamp, AM/PM settlement, exercise style, cash/share settlement, premium multiplier, deliverable, tick rules, and eligible sessions.

Never assume every contract delivers 100 shares or has the same trading cutoff. Distinguish standard and adjusted contracts. Exclude adjusted deliverables initially; correctly detect them and block trading instead of mispricing them.

Persist option and underlying quotes with bid, ask, sizes when available, event timestamp, receipt timestamp, source, and quality flags. Maintain trades, volumes, open-interest release dates, corporate actions, dividends, earnings, rates, and relevant scheduled events with as-of timestamps.

Use only information available at decision time. Open interest is not assumed to be a live count. Do not synchronize stale underlying prices with fresh option quotes without detecting the mismatch.

Reject or quarantine stale, crossed, invalid, conflicting, or incomplete data. Handle locked markets explicitly rather than automatically treating all locked quotes as invalid. A zero bid is possible but ordinarily disqualifies a new entry and is not proof that an existing position can be sold.

Broker option historical bars are not automatically sufficient for realistic chain-selection and fill backtests. Verify the exact coverage before using them as evidence.

Compare officially documented historical-data options such as Databento, ThetaData, and Massive. Verify schemas, quotes versus trade bars, expired-contract coverage, sample frequencies, index coverage, usage rights, non-display licensing, retention terms, and current total costs. Select no paid provider without approval.

Provide a free/synthetic fixture path for engineering tests, but label synthetic prices and theoretical Greeks as test data, not evidence of a tradable edge. Missing historical bid/ask or chain data must remain a disclosed research limitation.

Store large research datasets in partitioned Parquet with a suitable local query engine. Do not ingest the entire options universe into the small live-account database or a tiny production server.

## 8. Strategy research program

Pre-register economic hypotheses and small parameter grids before examining holdout results. Implement a modest number of interpretable strategy families, not thousands of arbitrary indicators.

Family A: Directional long options.

Test whether validated underlying trend or momentum signals justify a long call or put after premium, time decay, volatility changes, and execution costs. Compare the option implementation with an exposure-appropriate underlying benchmark for analysis only. Buying an option must add demonstrable economic value, not just leverage.

Family B: Directional debit verticals.

Test matched bull-call and bear-put spreads using validated directional signals. Compare spread widths, moneyness, holding periods, and capped upside with the corresponding long-option alternative. Account for both legs and inability to obtain a favorable package fill.

Family C: Defined-risk credit verticals.

Research volatility-risk-premium hypotheses using implied-versus-subsequent-realized volatility, trend, skew, event, and liquidity filters. Test put and call spreads separately. High implied volatility or a high credit alone is insufficient evidence. Explicitly measure crash exposure and adverse selection.

Family D: Defined-risk iron condors.

Research only when joint wing pricing, four-leg execution, portfolio concentration, and regime filters are supported. Validate whether incremental returns compensate for added costs and complexity relative to simpler verticals.

Initial research can prioritize liquid ETF-option candidates such as SPY, QQQ, and IWM, subject to actual data and liquidity tests. Cash-settled index candidates require separate account, contract, session, fee, and settlement verification. Candidate symbols are not trade recommendations or an automatically activated live allowlist.

Avoid volatility-index options initially unless product-specific forward references and settlement modeling are implemented. Do not apply a generic equity-option model to every index product.

For each candidate specify entry signal, economic rationale, options construction, permitted regime, contract-selection rules, exit rules, re-entry restrictions, capacity assumptions, and known failure modes. Include a cash/no-trade baseline. Retain rejected hypotheses and every attempted configuration in the research registry.

## 9. Contract selection and exit rules

Use a two-stage pipeline: inexpensive underlying/regime screening, then targeted option-chain retrieval for eligible candidates. Rate-limit and cache metadata, not stale tradable quotes.

Test narrow, economically justified ranges of days to expiration, delta/moneyness, and spread width. A starting research envelope may use 14-60 calendar days to expiration, but it is a hypothesis, not an optimized default or live authorization.

Filter each candidate on quote freshness, executable spread cost in dollars and percentage terms, size/depth where available, recent trading activity, open-interest timing, expected exit liquidity, event exposure, capital feasibility, and account permissions.

Use synchronized complex-order quotes when available. Independently displayed leg quotes do not prove a complete spread can fill at the sum of their midpoints. Reject leg mismatches, incompatible settlement, and unsupported ratios.

Rank feasible candidates using validated expected net P&L, downside scenarios, uncertainty, liquidity, capital usage, and correlation. Do not produce a spurious expected return from option-pricing formulas alone: risk-neutral prices are not automatically real-world expected returns.

Research deterministic profit-taking, loss-triggered exits, time exits, signal invalidation, volatility changes, and event exits. Express premium-based thresholds consistently for debit and credit positions. Do not preserve a universal 2:1 reward-to-risk rule without validating its suitability for the structure.

Treat rolling as closing one position and opening another with new costs and a fresh risk review. A roll cannot reset accumulated losses, bypass entry blocks, or hide a losing trade.

## 10. Pricing, Greeks, and portfolio stress

Implement validated pricing and Greek calculations appropriate to exercise style, dividends, rates, time conventions, and settlement. Use European analytical models only where their assumptions fit; use a validated American-style numerical method when required. Document approximations and model error.

Compute or ingest implied volatility, intrinsic/extrinsic value, delta, gamma, theta, vega, and rho with explicit units, sign conventions, multipliers, as-of timestamps, and provenance. Never silently fill missing Greeks with zero.

Aggregate per-contract, per-strategy, underlying-group, and portfolio exposures. Show dollar delta, gamma exposure under defined moves, daily theta, and dollar vega per specified volatility-point change. Greek neutrality alone does not establish low risk.

Perform full repricing for large shocks rather than relying only on delta-gamma approximations. Include underlying shocks, volatility shocks, skew changes, time passage, gaps, spread widening, correlated drawdowns, partial-position states, assignment, and broker liquidation.

Do not net unrelated expirations, deliverables, settlement conventions, or accounts into artificial protection. Track collateral and operational liquidity separately from theoretical payoff risk.

Stress limits, missing critical analytics, or uncertain residual exposure block new entries. Record the exact scenario and failed limit in each rejection.

## 11. Event-driven backtesting and honest fills

Run historical replay through the same domain models, strategy logic, portfolio construction, risk checks, and order-state rules used in production. Substitute data and execution adapters, not a different trading algorithm.

Model point-in-time contracts, delistings, splits, dividends, expiration, assignment, settlement, cash availability, sessions, halts, entry restrictions, brokerage interventions, and relevant costs. Avoid lookahead, survivor bias, same-bar impossible fills, and use of future chain membership.

Use next-eligible-event execution after a signal. Respect observation, computation, review, network, and broker latency. Include rejected, unfilled, canceled, and partially filled orders.

Implement at least conservative, base, and optimistic fill scenarios. Conservative assumptions must not grant every midpoint fill. Model limit-order queue uncertainty and adverse selection; report uncertainty when queue data is unavailable. Complex-order fills must respect package ratios, sizes, price constraints, and actual supported semantics.

Separate executable liquidation value, broker-style mark, and theoretical value. Do not book a profitable exit solely because a model says the option is worth more. Do not manufacture perfect expiration exits or risk-free rolling.

Allocate fees per applicable leg, side, contract, event, and effective date. Obtain the current official fee schedule. Zero stated commission is not a zero-cost execution assumption.

Hash raw data, cleaning versions, feature code, strategies, parameters, and execution assumptions. Preserve deterministic seeds and every research attempt so results are reproducible.

## 12. Validation and economic promotion

Target multi-year data containing materially different volatility and trend conditions where suitable data are available. Never invent missing history. Narrow claims to the coverage actually tested.

Separate development, validation, and untouched final test periods. Use walk-forward testing and purging/embargoes appropriate to overlapping positions. Keep parameter selection, model fitting, feature scaling, and calibration strictly within training windows.

Control multiple testing. Evaluate parameter stability, dependence on a few trades, regime sensitivity, cost stress, delayed execution, lower fill rates, and ablations. Use block resampling where trade outcomes are dependent; do not count correlated legs or simultaneous signals as independent observations.

Report full-account return, net dollars, drawdown depth/duration, profit factor, expectancy, win/loss distribution, turnover, utilization, exposure, expected shortfall, cost attribution, slippage, fill rates, and confidence intervals. State annualization conventions and avoid presenting short-sample CAGR as dependable.

Distinguish model-estimated probabilities from empirically calibrated probabilities. A positive sample mean alone does not establish statistically credible positive expectancy. Pre-register the uncertainty threshold and minimum effective sample requirements appropriate to each strategy.

Maintain separate technical and economic gates. Hundreds of scheduler cycles are not hundreds of trades. Seven days of shadow operation can reveal engineering faults but cannot establish a durable edge.

If evidence is insufficient or operating costs dominate, issue ECONOMIC_NO_GO with specific causes and the evidence needed to reconsider. Keep research, paper, and shadow functioning. Never lower validation standards to satisfy a desired outcome.

## 13. Broker adapter and execution service

Create a narrowly scoped RobinhoodOptionsAdapter. Map internal protocols to discovered official tools inside the adapter only. The rest of the system must not depend on invented broker methods.

Separate strategy signals, risk-approved intents, broker review, submission, and reconciliation. Only the execution service may access order-placement capability. Read-only reporting and research components must not have trading credentials.

Before every submission verify authorization, account, permissions, broker health, current session, contract identity, fresh quotes, current buying power, reserved collateral, risk limits, absence of conflicting orders, and an executable exit/incident policy.

Use review_option_order when verified available. Persist its request and result. Ensure its account, contract IDs, legs, ratios, direction, position effect, total price, and warnings match the intended action. Revalidate stale reviews and changes in quote or buying power. A successful preview is neither a fill guarantee nor durable buying power.

Use limit orders for initial ordinary execution. Do not automatically convert a failed limit to a market order. Implement bounded, timed repricing only after reconciling cancellation and repeating relevant risk checks.

Use native complex orders for spreads when verified. Never silently substitute independent leg orders for unsupported multi-leg execution. A price-constrained complete spread must not become an uncovered short-option position merely to get a fill.

Document broker fill semantics: distinguish partial quantities of complete spread units from unexpectedly unmatched legs. Unexpected residual legs are incidents. A risk-reducing exit must not remove the protective long leg while leaving an unauthorized short leg.

Implement durable intent IDs and broker-supported idempotency keys only where the actual schema supports them. Otherwise persist before submission and reconcile ambiguous responses before any retry. When you cannot determine whether an order was accepted, enter an unknown state and halt new exposure rather than resubmit blindly.

## 14. Order lifecycle, recovery, and reconciliation

Implement persisted, validated transitions including:

PROPOSED
RISK_REJECTED
RISK_APPROVED
REVIEW_PENDING
REVIEWED
SUBMISSION_PENDING
SUBMITTED
PARTIALLY_FILLED
FILLED
CANCEL_PENDING
CANCELED
REJECTED
EXPIRED
UNKNOWN_REQUIRES_RECONCILIATION

Maintain separate position-lifecycle events for exercise, assignment, expiration processing, settlement, and broker-initiated closure. Do not force those events into a misleading order status.

Every transition records timestamp, actor, reason, intent hash, broker references, and relevant evidence. A cancellation request is not a canceled order. An unknown response is not a rejection. Expiration is not proof of completed cash settlement.

Reconcile orders, fills, option positions, unexpected shares, cash, collateral, settlement receivables/payables, fees, and account equity. Respect documented eventual-consistency windows without inventing fills to make the books balance.

On startup begin paused, load durable state, inspect recent broker events and positions, restore protective monitoring, reconcile, and permit entries only after material differences resolve. Never auto-liquidate all positions simply because the server restarted.

Use a single execution writer with durable leases and fencing so an obsolete process cannot submit orders after leadership changes. Distributed locks alone are not sufficient if an expired leader can continue acting.

## 15. Exercise, assignment, and expiration management

This is a core production subsystem, not a footnote.

Track exercise style, dividends, ex-dividend dates, extrinsic value, assignment exposure, pending exercises, last trading date, settlement type, contract-specific cutoff, and Robinhood intervention windows.

Initially plan to exit physically settled contracts no later than the preceding eligible trading session before expiration, subject to a stricter strategy-specific deadline. Avoid initiating exposure near an ex-dividend assignment hazard. Verify current broker deadlines rather than assuming a universal time.

Model early assignment of short legs even when a spread has a nominally defined terminal payoff. Account for after-hours price changes, pin risk, one leg being exercised while another is not, negative cash, stock delivery, and weekend exposure.

Do not automatically exercise a protective option as a universal response. Compare remaining extrinsic value, buying power, supported instructions, operational timing, and the preauthorized remediation policy. Escalate to the operator when the permitted response is not available.

For cash-settled index options, model settlement values, AM/PM expiration, last trading versus settlement dates, and cash movements correctly. Do not substitute the closing index price for a different official settlement reference.

Treat automatic broker closeouts as possible interventions, not a guaranteed protective service. Detect, reconcile, and report them. If a close cannot execute before a deadline, escalate while useful intervention time remains; do not record a fictional flat position.

DNE, early-exercise, or similar instructions must use a verified supported route and separate authorization where required. Never fake an unavailable exercise API or assume that a submitted support request was accepted.

## 16. Operating modes and live authorization

Implement mutually exclusive modes: backtest, recorded replay, simulation, paper, shadow, micro-live, and normal live.

Backtest, replay, simulation, and paper must not load live trading credentials or invoke order-changing tools. Shadow may read authorized live data and account state but cannot submit, replace, cancel, exercise, or change permissions. A broker order-review function is not a substitute for a full paper-trading ledger.

Micro-live means the smallest admissible whole-contract structure, not an arbitrary $5 option order. Initially cap it at one complete structure per new position, one open strategy position, and one new position per session, while retaining or tightening all percentage risk limits. If one unit does not fit, micro-live remains disabled.

Require independent evidence for technical readiness, economic readiness, account/capability readiness, and operator authorization. Live activation additionally requires successful reconciliation, risk self-tests, clock checks, no active kill switch, current manifests, and no unresolved critical incident.

Bind operator authorization to account, equity ceiling, capital budget, strategy/configuration hash, software release, permitted sessions, and risk limits. Use a documented operator-controlled signing or authorization mechanism. The running bot and research agents must not be able to approve their own escalation.

A flag or hand-edited audit document is insufficient. Missing, deleted, expired, inconsistent, or tampered evidence fails closed. Preserve historical NO-GO reports; replace status only through a new attributable evaluation with evidence.

Do not auto-promote a retrained model, new strategy, changed risk profile, or expanded market session. Produce a candidate release and comparison report for separate approval.

## 17. Kill switches and degraded operation

Separate entry permission, existing-position risk management, and emergency intervention. A block on new entries must not inadvertently disable all monitoring and safe preauthorized exits.

Implement daily, weekly, and peak-drawdown controls, data-quality circuit breakers, authentication/session failures, unknown-order halts, account mismatches, and a persistent filesystem kill switch.

When a loss threshold is reached, block new exposure, reconcile and cancel pending entries where safely supported, retain appropriate protective management, and alert me. Do not cancel a protective order merely because all orders share one global cancel path.

Require manual review after weekly or maximum-drawdown breaches. Restarting, deleting a file, changing the date, depositing cash, or rolling a trade must not automatically clear a breach or reset the economic history.

Do not liquidate at arbitrary prices on a generic error. Emergency orders require a separately reviewed policy, supported order semantics, and their own exposure checks. Unknown positions or stale pricing may require operator intervention rather than blind automation.

## 18. Architecture, storage, and dependencies

Prefer a typed Python modular monolith with asynchronous I/O and one execution owner. Use a currently supported Python version and verify dependency compatibility. Add Rust or additional services only if measured bottlenecks justify the cost.

Use validated configuration, official MCP tooling, structured logging, exact financial arithmetic, SQLAlchemy/Alembic or an equivalent migration layer, pytest, property-based testing, linting, static typing, dependency scanning, and an SBOM. Pin dependencies and lock environments.

Use SQLite WAL for the initial single-host transactional ledger when appropriate. Do not share its live database through an unsafe network filesystem. Design a migration path to PostgreSQL without rewriting domain logic. Keep bulk options history in the separate research store.

Adapt the existing repository rather than imposing disruptive renames. The resulting organization should clearly include:

AGENTS.md
README.md
Makefile
pyproject.toml
.env.example
configs/
docs/options-only-build-spec.md
docs/migration-map.md
docs/capability-matrix.md
docs/data-providers.md
docs/risk-policy.md
docs/strategy-research.md
docs/economic-feasibility.md
docs/validation-report.md
docs/implementation-plan.md
docs/security-and-threat-model.md
docs/operations-runbook.md
docs/limitations.md
src/trading_bot/domain/
src/trading_bot/market_data/
src/trading_bot/pricing/
src/trading_bot/strategies/options/
src/trading_bot/portfolio/
src/trading_bot/risk/
src/trading_bot/brokers/robinhood_options_mcp.py
src/trading_bot/execution/
src/trading_bot/lifecycle/
src/trading_bot/reconciliation/
src/trading_bot/persistence/
src/trading_bot/research/
src/trading_bot/reporting/
src/trading_bot/cli/
tests/unit/
tests/property/
tests/integration/
tests/replay/
tests/chaos/
infra/digitalocean/
.github/workflows/

Persist contracts, market-data provenance, strategies, features, research attempts, intents, reviews, risk evaluations, orders, transitions, fills, strategy positions, collateral, assignment/exercise events, settlements, equity curves, alerts, authorizations, configuration versions, and audit events.

Keep the full specification in docs/options-only-build-spec.md. Keep root AGENTS.md concise, containing invariant safety rules, test commands, workstream conventions, and pointers to the full specification. Do not rely on Codex.md being automatically loaded or place an oversized specification in instruction files without checking the current discovery limits.

## 19. Security, connectors, and LLM boundaries

The live decision path is deterministic:

validated market data -> versioned features -> approved strategy -> portfolio construction -> mandatory risk checks -> reviewed order intent -> execution -> reconciliation -> audit

An optional LLM may summarize already sanitized reports or propose offline research. It must be read-only, budget-limited, nonessential, unable to view credentials, and unable to place orders or modify live configuration. News text, model output, and repository instructions cannot override risk enforcement.

Keep broker credentials solely in the authorized execution environment. Use least-privilege scopes, supported token renewal, encrypted storage, restrictive file permissions, redaction, and documented rotation. Never expose credentials in Git, prompts, fixtures, logs, metrics, CI, screenshots, or cloud research tasks.

Create a connector/dependency manifest for Robinhood MCP, selected market-data interfaces, GitHub/CI, DigitalOcean deployment tooling, and optional documentation or alert tools. Verify actual availability and permissions. Do not assume ChatGPT connections automatically exist inside Codex or a deployed daemon.

Broker-order capability must not be available to coding subagents, reporting plugins, or untrusted tools. Do not install a third-party trading plugin merely because its description claims profitable signals.

Use dependency integrity checks, non-root containers, restricted filesystem writes, TLS verification, private administration, and minimal exposed ports. Address prompt injection, supply-chain compromise, credential theft, duplicate requests, schema changes, account substitution, stale leadership, and corrupted state in the threat model.

## 20. Deployment, scheduling, and monitoring

Preserve DigitalOcean as the target. Benchmark the live process before selecting a Droplet. A small instance may be sufficient for a narrow live universe, but historical-chain research must not starve production execution. Estimate current hosting, storage, backup, data, and monitoring costs before proposing paid deployment.

Provide Docker, deployment manifests, optional Terraform/cloud-init, least-privilege service accounts, SSH-key access, private administrative access, firewall rules, clock synchronization, log rotation, resource limits, health checks, encrypted backups, and tested restoration.

Initial deployment starts paused or in paper mode. Deployment scripts, CI jobs, scheduler restarts, and application upgrades may never enable live mode.

Use UTC storage and exchange-local timezone-aware calendars. Display operator times in America/Detroit. Handle holidays, early closes, daylight-saving transitions, overnight sessions crossing midnight, and product-specific settlement calendars.

Research and reporting may run outside trading hours. Entry evaluation occurs only at strategy-validated intervals during eligible sessions. Scale quote and reconciliation frequency to open risk, expiration proximity, measured API latency, and verified rate limits. Do not continuously poll every contract.

Monitor broker/data freshness, reconciliation lag, unknown orders, exposure and Greeks, pending collateral, assignment events, settlement cash flows, drawdown, fees, realized slippage, authorization expiry, clock drift, disk, memory, restarts, and missed alerts.

Expose private read-only health, readiness, and metrics endpoints. A running process with stale data or unreconciled positions is not ready to trade. Add an external heartbeat monitor so complete server failure can still trigger an alert.

Back up the transactional database consistently, not by blindly copying active WAL files. Test restore, restart reconciliation, rollback compatibility, and behavior after network failure. On shutdown block new entries, persist state, handle in-flight requests safely, and preserve the incident trail.

## 21. Mandatory tests and acceptance invariants

Use real tests, including independent expected values rather than comparing an implementation to itself. Require at least 90% branch coverage for risk, execution-state, and lifecycle-critical modules, and at least 80% overall coverage, while recognizing that coverage alone does not establish correctness.

Financial and contract tests:

- Decimal boundaries, premium multipliers, tick sizes, fees, ratios, debit/credit signs, payoff diagrams, collateral, and full-account returns.
- Zero permissible contracts remains zero; no fractional options or automatic one-contract minimum.
- Adjusted contracts, mixed expirations, mixed settlement, invalid prices, zero bids, stale quotes, and stale open interest.
- Delta/vega/theta units, finite-difference checks, model limits, and stress calculations.

Execution and lifecycle tests:

- Complete and partial spread-unit fills, unexpected unmatched legs, failed cancellations, late fills after cancellation requests, and rejected reviews.
- Broker acceptance followed by timeout, crash before/after submission, duplicate events, paging gaps, and unknown status.
- Restart, clock drift, schema change, rate limit, expired authentication, account substitution, changed permissions, and competing execution leaders.
- Early assignment, dividend liability, pin risk, AM versus PM settlement, broker closeout, unexpected shares, negative cash, and delayed settlement.
- A risk-reducing close never creates unauthorized naked exposure.

Safety and mode tests:

- Disabled markets cannot produce live calls.
- Paper/shadow/CI cannot submit, cancel, replace, exercise, or upgrade permissions.
- Missing authorization, deleted audit evidence, edited manifests, stale release hashes, or active kill switches cannot unlock live execution.
- New-entry halts preserve authorized monitoring and protective management.
- Pending orders consume appropriate risk and collateral; cancellation requests alone do not release reservations.

Research and infrastructure tests:

- No lookahead, same-bar impossible fills, or future contract selection.
- Deterministic replay with identical data/configuration.
- P&L and cost reconciliation without double-counting spreads.
- Network partition, disk full, database lock/corruption, server loss, alert failure, backup restore, and safe rollback.
- Synthetic-data runs cannot be reported as empirical profitability evidence.

No CI or development test may place a real trade. Never weaken a failing risk test merely to obtain a green build.

## 22. Parallel Codex implementation workflow

Use one coordinating agent. First inspect the existing codebase, identify conflicts with this options mandate, freeze shared interfaces, and create a dependency-aware implementation plan.

Use isolated worktrees or branches for genuinely independent work:

A. Official capabilities, authentication feasibility, and broker contract tests.
B. Contract models, pricing, data quality, and historical-data ingestion.
C. Strategy hypotheses, event-driven backtesting, and validation.
D. Risk, execution, idempotency, lifecycle, and reconciliation.
E. Infrastructure, security, monitoring, and backup/restore.
F. Independent adversarial tests, economic critique, and implementation review.

Delegate suitable credential-free work to available Codex cloud tasks or local subagents only after checking the actual supported workflow. Cloud execution is not assumed merely because the prompt requests parallelism. If unavailable, use local isolated work or sequential execution and state what actually ran.

Do not share live credentials, personal-account snapshots, or private tokens with coding agents. Separate work does not mean multiple production order writers. Assign file ownership, define handoff artifacts, review diffs, and merge through the coordinator.

Implement tested vertical slices rather than generating every file first. A useful first slice is one historical contract, one candidate strategy, one risk-approved simulated intent, a complete simulated order lifecycle, reconciled P&L, and an auditable report.

Then expand data/strategy coverage, add the verified read-only broker integration, implement the locked execution path, harden failure recovery, and prepare deployment.

Run formatting, linting, typing, unit/integration/property tests, and appropriate security checks after each slice. Record actual commands and outputs. Fix root causes instead of suppressing failures.

Proceed through development without repeatedly asking questions already answered here. Make conservative reversible engineering choices when possible. Stop only the affected activity for missing access, paid services, destructive changes, account permissions, or real-money authorization, and complete independent work in the meantime.

## 23. Operator commands and final deliverables

Implement documented commands, adapting names to the existing CLI where necessary:

make setup
make format
make lint
make typecheck
make test
make test-integration
make test-chaos
make security
make options-backtest
make options-walk-forward
make options-stress-test
make paper
make shadow
make live-preflight
make build
make deploy-plan
make backup
make restore-test

trader status
trader capabilities
trader capital-feasibility
trader preflight
trader positions
trader open-orders
trader proposed-orders
trader greeks
trader assignment-risk
trader expiration-calendar
trader reconcile
trader explain-last-decision
trader export-journal
trader pause-entries
trader resume-entries
trader activate-kill-switch
trader clear-kill-switch
trader enable-live --stage micro
trader disable-live
trader generate-incident-report

Any live-activation command must require the separate operator authorization and gates described above. A resume command cannot override failed gates. Test, setup, build, and deployment-plan commands must never trade.

Provide a final report containing:

1. What existing code was retained, modified, retired, or left untouched.
2. Implemented architecture, repository structure, and exact setup commands.
3. Verified MCP connection instructions and authentication limitations.
4. Secret/environment-variable names, never secret values.
5. Capability matrix with public, session, account, and runtime evidence distinguished.
6. Strategy comparisons, capital-feasibility results, operating costs, and uncertainty.
7. Actual tests executed, coverage, security findings, and unresolved failures.
8. Paper/shadow demonstrations and reproducible research commands.
9. Deployment plan, rollback, backup/restore, monitoring, and incident instructions.
10. Separate engineering, economic, and live-authorization verdicts.
11. Unsupported features, missing datasets, untested assumptions, and unfinished tasks.
12. An accurate statement of whether any live order was placed. Under this development authorization, the required result is no live orders.

Do not declare the strategy profitable because a backtest is positive, declare integration tested because mocks pass, or declare deployment successful because configuration files exist.

If no admissible strategy passes, deliver a functioning options research/paper/shadow system and a precise NO-GO report. Do not manufacture a trade to make the project appear finished.

## 24. Official reference starting points

Recheck these sources at implementation time, follow their current documentation links, and record retrieval dates. This specification was prepared on September 18, 2026; public documentation is not a substitute for current tool introspection and account verification.

Robinhood Agentic Trading:
https://robinhood.com/us/en/support/articles/agentic-trading-overview/
https://robinhood.com/us/en/support/articles/trading-with-your-agent/

Robinhood options operations:
https://robinhood.com/us/en/support/articles/options-trading-hours/
https://robinhood.com/us/en/support/articles/index-options/
https://robinhood.com/us/en/support/articles/expiration-exercise-and-assignment/
https://robinhood.com/us/en/support/articles/options-collateral/

Options education and contract mechanics:
https://www.optionseducation.org/optionsoverview/options-basics
https://www.optionseducation.org/strategies/all-strategies/bear-put-spread
https://www.optionseducation.org/strategies/all-strategies/bull-put-spread-credit-put-spread

Trading restrictions:
https://www.finra.org/rules-guidance/notices/26-10

Verify the currently applicable FINRA/SEC framework and Robinhood implementation, including transition rules, account type, settlement, and intraday requirements. Do not hard-code either the historical pattern-day-trader framework or an assumption that all such restrictions are absent.

Data-provider documentation:
https://databento.com/datasets/OPRA.PILLAR
https://docs.thetadata.us/operations/option_history_quote.html
https://massive.com/docs/flat-files/options

Codex documentation:
https://developers.openai.com/codex/mcp/
https://learn.chatgpt.com/docs/agent-configuration/agents-md
https://learn.chatgpt.com/docs/agent-configuration/subagents

Begin by auditing the existing repository and the exact available Robinhood capabilities. Then implement the options-only migration in tested, reviewable slices under these boundaries.
