# Original-filing annual quality measurements

`research.stock_annual_quality` builds a typed annual measurement bundle from an
original `StockFiling` and normalized `StockFilingFacts` collections. The initial
method is explicitly AXP-only; it is not a universal issuer debt mapping or a
stock recommendation. Actual-data factor validation and policy-consumer wiring
remain separate from this implementation.

## Measurement scope

The frozen `axp-annual-as-reported-financing-to-reported-equity-v1` method calculates:

- Annual net income divided by mean opening/closing reported stockholders' equity.
- Comparable annual total-revenue growth.
- Reported long-term debt plus short-term borrowings, divided by closing reported equity.

These are named research features. The income/equity ratio is not automatically
common-shareholder ROE. Current maturities already included in reported long-term
debt are counted once. Embedded finance-lease scope remains as reported; deposits
are separate. Missing short borrowings or another component do not mean zero.

Annual income/revenue durations remain distinct from year-end equity/debt
instants. The bundle never manufactures an annual start date for an instant.
Adjacent comparable fiscal periods include supported 52/53-week years. All
components bind the same original filing and entity, native USD units and explicit
empty dimensions. Native `decimals=-6` describes rounding, not a multiplier.

Equivalent native context strings can retain multiple agreeing references.
Conflicting values, mixed vintages/entities/units, missing components or invalid
denominators produce a typed unavailable result. Missing observations do not
become neutral scores or partial successful bundles. References retain native
periods, row positions, complete observation/facts hashes and actual receipt clocks.

## Time and authority

The separately labeled retrospective availability proxy is midnight UTC two
calendar days after native `date_filed`. It is a conservative research convention,
not a measured SEC publication timestamp. The actual retrieval clock remains
unchanged. Later original filings and their comparative values cannot be
backdated into earlier decisions.

`AnnualQualityPeriods` and `AnnualQualityRequest` feed `build_annual_quality`,
which returns `DefinedAnnualQuality` or `UnavailableAnnualQuality`.
`revalidate_annual_quality` reconstructs the result from its retained inputs.
Constructors, replacement and revalidation preserve the derived-field and
permanently false qualification/authorization boundaries.

```sh
PYTHONPATH=src uv run pytest tests/unit/research/test_stock_annual_quality.py -q
```

This verification uses fictional source fixtures. It supplies no actual factor,
strategy-return or live-broker result.

## Remaining work

Integrate the typed bundle with the quality-policy consumer without changing
legacy evidence when no bundle is supplied. Freeze a source-admitted actual input
run, independently verify its arithmetic, and retain issuer-specific mapping and
history gaps. The other issuers' raw source intake has passed its normalizers;
OXY's historical-original coverage, missing KHC revenue concepts and other debt
mappings remain explicit. All seven intake pagination states are unknown.

The full Task 5 monetary/strategy/statistical evaluation remains incomplete.
