# AGENTS.md

AI Trading Bot: Codex Development Instructions

## 1. Engineering and Parallelization

* Act as the lead engineering orchestrator.
* Inspect the repository and identify dependencies before implementation.
* Decompose substantial tasks into independent workstreams.
* Delegate parallel tasks to specialized agents when supported and beneficial.
* Integrate, review, and test all completed work.
* Execute routine development autonomously without unnecessary approval requests.

## 2. Code Quality

* Prioritize modular, maintainable, production-quality Python.
* Use official, documented APIs and brokerage integrations.
* Write automated tests for critical functionality.
* Fix failures and run regression tests before declaring completion.
* Document significant architectural decisions.

## 3. Trading Safety

* Keep live trading disabled by default.
* Never place real-money trades without explicit authorization.
* Enforce deterministic risk limits independent of AI recommendations.
* Implement an emergency kill switch and comprehensive trade logging.
* Never bypass brokerage authentication or security controls.

## 4. Quantitative Research

* Use verified market data and reproducible methodologies.
* Prevent look-ahead bias, survivorship bias, and data leakage.
* Include realistic transaction costs and slippage in backtests.
* Compare strategies against passive benchmarks.
* Never fabricate results or assume a strategy is profitable without validation.

## 5. Portfolio Management

* Separate long-term investing from tactical trading.
* Maintain accurate cost-basis, realized-gain, and reinvestment accounting.
* Evaluate profit-taking strategies through backtesting.
* Enforce portfolio diversification, position sizing, and drawdown limits.

## 6. Completion Requirements

* Independently verify all integrated components.
* Report completed features, test results, and remaining limitations.
* Never claim successful deployment or continuous operation without verification.
* Prioritize capital safety, reliability, and risk-adjusted performance over trading frequency.
