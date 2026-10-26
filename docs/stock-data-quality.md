# Stock dossier data-quality diagnostics

`assess_stock_data_quality(dossier, *, as_of, policy=StockDataQualityPolicy())`
returns a frozen, deterministic assessment of an existing normalized stock dossier.
It fetches nothing, repairs nothing and changes no runtime or trading control.

The assessment separates each source's receipt age from the latest bar's UTC
left-edge date, each financial period's end date and the fundamentals market date.
These dates do not certify exchange sessions or publication times. Ages retain
microsecond precision independently of the caller's Decimal arithmetic context.
The assessment clock must be aware UTC and at least the dossier clock. Any nested
receipt after that clock rejects the whole assessment with
`ValueError("stock_data_quality_invalid")`; it does not filter a compiled dossier's
values or membership into an earlier historical view.

The default policy uses receipt age 86,400 seconds, latest-bar lag 7 calendar days,
financial-period age 550 calendar days and minimum history 201 retained bars.
These are explicit investigation hypotheses, not calibrated investment criteria.
Thresholds are inclusive. Policy fields require exact integers, excluding bool;
their finite ranges are respectively 1–31,536,000, 0–3,650, 0–36,500 and 1–100,000.
Unknown/quarantined bar counts remain `None`; actual empty normalized series have
zero bars. Missing financial values remain named missing metrics; observed zero
values are present. Interpolation omissions, unknown interpolation/session flags,
null rows and unavailable request results remain separate counts or reason codes.
Collection null-row counts refer to the original collection, which can include
other requested symbols.

Each receipt has an explicit origin: `dossier_source`, `linked_local_projection`,
or `unverified_additional_receipt`. A history projection retains its own hash and
links to the original observation only when the projected hash, tool, receipt
clock and dossier projection context all match. It is a local derivative, not
another original or authenticated source. Unlinked extra receipts retain their
hashes with no claimed original-source link. Receipt rows must therefore not be
counted as independent original source observations.

`descriptive_observations_present` means at least one retained record has a receipt
within policy. It does not establish that its underlying value is current, complete
or comparable. Each source and financial period has its own diagnostic reasons.
`blocked_uses` names restrictions for daily features, financial comparisons,
source qualification, historical strategy evaluation, investment selection and
live trading; absent/stale observations also block current descriptive research.
There is no general readiness boolean. Calendar, actions, quote currency, entity
mapping, historical universe and point-in-time availability remain unverified by
these dossier types. Opaque filing entity/unit text is preserved, not certified.
All six qualification, eligibility and trading flags are fixed false.

`assessment_hash` binds the complete existing dossier hash (including source and
projection provenance), exact policy, assessment clock and all diagnostic output
under `stock-data-quality-v1`. This is content addressing, not independent proof of
original source bytes, provider authenticity or coverage. The module assumes the
existing typed normalizer/dossier contract; the archive and source-evidence checks
remain separate.

Next: bind an independently reviewed source contract, calendar/action/currency and
availability evidence to actual retained inputs, then qualify the observations
needed for the declared stock strategy study. Local fixture tests alone do not
complete Task 4 or authorize investing.
