# Private owned research originals

`market_data.etf_capital_owned._own_capital_source` is a private foundation for
later evaluator-local preparation. It accepts an original `CapitalResearchDataset`,
validates its complete source/actions/calendar/configuration graph before copying,
and reconstructs every dataclass node with the existing constructors. The owned
copy is validated again and its dataset hash must equal the original hash. A
changed original during copying denies; this is not a general concurrency proof.

Exact immutable scalar values may be shared. New owned intake requires exact
`datetime` clocks with `datetime.UTC`, rejecting custom mutable timezone aliases.
Existing public readers and their historical hashes are unchanged. Invalid
original publication/eligibility fields cannot be reset into valid copied values.

The separate `capital-owned-source-v1` root binds SHA256 of exact canonical
configuration bytes, the configuration hash, and the complete dataset hash.
This is not an alias to public owner-v4 frame identities, an authenticated source
receipt, a qualified dataset factory, or permission to skip risk checks. No
caller-provided prepared source, risk state, cached approval or account balance
is accepted by a public evaluator; the eventual evaluator must create its owned
snapshot internally. No global cache or filesystem/network operation is added.

All original source/execution/promotion flags remain false. Snapshot integrity
does not qualify latest-vintage history, action coverage, costs or economics.
The helper is not yet consumed by the complete evaluator and does not satisfy
the failed 750-frame or full-grid workload gates.

Next: share the existing numerical signal/policy kernels over compact per-as-of
prepared rows, preserve original account/risk/admission at every boundary, then
validate the full workload before executable freeze and a separately qualified
economic evaluation. Never slice a terminal split-adjusted history backward.
