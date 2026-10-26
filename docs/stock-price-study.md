# Offline individual-stock strategy study

This command evaluates the frozen daily 50/200 trend hypothesis on eight stocks
and four passive/exposure controls, across four declared cost assumptions. It is
the first **price-only** component of Task 5. It does not establish after-tax
profitability, complete the seven-family/exit/reinvestment evaluation or permit
trading. No broker account, order, credentials or provider request is accessed.

The first frame is AXP, AAPL, BAC, CVX, KO, KHC, MCO and OXY from the retained
original 2023Q4 disclosure. SPY is a benchmark only. The frame is an explicitly
selected institutional subset, not the complete U.S. equity universe. The
runtime's broader stock discovery remains a separate research workflow.

## Reproduce the frozen first probe

Install the existing project with Python 3.12–3.14. Keep original licensed source
receipts in a private directory. They are not distributed with the repository.
The accepted Task 4 handoff and every original file must match their hashes.
Create a new, empty output directory with mode `0700` before each authorized run.

```bash
python -m trading_bot.runtime.stock_price_study \
  --evidence-directory /absolute/private/task4-data \
  --manifest /absolute/private/task4-data/primary-common-actual-inputs-20261026/corrected-v3-run/manifest.json \
  --manifest-sha256 07c8d3084ec7b199c8bc30944835b6b24aaf9110555a44c4b84a234cdb9dbae3 \
  --protocol-sha256 067ccbd11b9748db4202c15e2f08941ff8cf9065aff5bfc1d20706843b2fe419 \
  --output-directory /absolute/private/new-study-result
```

The command fails before evaluating outcomes if the protocol, cohort/window or
output destination differs. A repeated run cannot overwrite a prior output.
Full canonical traces are streamed to deterministic gzip; a compact JSON report
retains all component hashes, metrics and assumptions. Successful files use
content-addressed names and mode `0600`, with staged atomic publication.
Source files and all input hashes are checked before and after calculation.
An outer process exit receipt remains necessary to verify command completion.

## Interpretation

Signals at completed session closes execute at the next regular-session open.
Training and holdout share one continuous cash/stock path. The training cut does
not liquidate positions. The final signal is unexecuted; the last close has one
predeclared liquidation cost. All eight members remain in the denominator.

The initial NAV is dimensionless one, not a funded dollar account. The panel is
eight independently funded equal initial sleeves. The 75/15/10 monetary portfolio
and its settlement, lot, tax and reinvestment rules are separate workstreams.
Native price currency remains unknown. Dividends, taxes, interest, operational
expenses, actual spreads and fills are not included in this first probe.

Metrics use daily simple returns and explicitly labeled annualization. Paired
block intervals use realized daily log-return differences, shared circular draws
and the declared sixteen-comparison adjustment. They estimate a historical mean
log difference, not the probability of future profits. All undefined ratios and
sparse-sample warnings remain visible. Training-only sensitivity is not used to
select a new holdout parameter. See the frozen design for every exact convention.

## Lean first release

The user approved deferring elaborate operational drills, additional backup
destinations and dashboard expansion. There is no mandatory 60-day paper wait.
Critical software simulations and risk/accounting/reconciliation tests remain.
Official authentication, intended account restrictions, the kill switch,
deterministic risk controls and a separate explicit live activation remain
required. Adding credentials or finishing this study cannot enable trading.

## Remaining Task 5 work

Admit the monetary distribution/action and security evidence without rewriting
native unknowns; resolve or bound conflicting dates and pagination limits.
Implement the source-admitted portfolio replay and compare all required strategy
families, three central exit models, repeated entries and reinvestment against
total-return passive controls. Preserve publication-aware quality/event/revision
inputs, tax/cost/stress sensitivities and the complete requirement audit. A
negative economic result is valid; missing required comparisons remain incomplete.
