# Live activation

Live trading is disabled by default. Run `make live-preflight`, obtain stage-specific promotion
evidence, then create the signed operator artifact with the exact loss acknowledgement. Startup
remains paused; authorization never automatically resumes execution. Prediction and equity live
remain unavailable pending exact evidence.


Before requesting a signed activation artifact, run `make live-readiness`. The command is a
local fail-closed audit only: it checks that live mode was explicitly enabled by the operator,
that Crypto credential and runtime verification files are present with restrictive modes, and
that the runtime process was not given an operator signing-key path. It does not place orders,
does not print secret values, and exits non-zero until every prerequisite is satisfied.


A Robinhood Agentic browser connection (for example, the Robinhood web page showing ChatGPT
as connected) is not by itself a runtime credential for this service. If an operator wants the
bot to use a reviewed Robinhood Trading MCP OAuth store, expose it through
`ROBINHOOD_MCP_OAUTH_STORE_DIR` as a service-owned directory with mode `0700` or stricter;
the live path still requires the signed activation and promotion gates above before trading.
