# Capital-study joint uncertainty capacity

`dependent_capital_simultaneous_mean_intervals` uses the same dependent moving-
block max-centered-error engine as the existing simultaneous interval API.
Its fixed capacity is1..2784 aligned columns and at most2048 observations each:
29paths *6capital tiers *4friction levels *4reference roles. The legacy API
continues accepting at most2088 columns; its seeded values and rounding are
unchanged. No dependency or production configuration changes are needed.

Both APIs share original noncircular20/100-session starts within each draw,
fixed1100-digit sums, outward28-digit interval endpoints and immutable records.
Draws, original observations and comparison columns are distinct counts.
`independent_opportunities` remains unknown, not a bootstrap draw count.

This function accepts math columns, not authenticated source facts. It cannot
verify complete family membership, dates, roles, capital/cost identities or
train-only selection provenance. Conditional bootstrap bands are not guaranteed
adaptive-selection coverage, economic acceptance or promotion evidence. The
owning [panel](etf-capital-panel.md) now composes complete original-event paths
and benchmarks. Current corrected-source release, actual full workload validation,
protocol freeze and qualified authorized inputs remain separate unfinished gates.
No source/cost/execution/economic/promotion/live eligibility is established here.
