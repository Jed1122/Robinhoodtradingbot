# Private owned research originals

`market_data.etf_capital_owned._own_capital_source` is a private foundation for
evaluator-local preparation consumed by the DEVELOPMENT panel. It accepts an original `CapitalResearchDataset`,
validates its complete source/actions/calendar/configuration graph before copying,
and reconstructs every dataclass node with the existing constructors. The owned
copy is validated again and its dataset hash must equal the original hash. A
changed original during copying denies; this is not a general concurrency proof.

Exact immutable scalar values may be shared. New owned intake requires exact
`datetime` clocks with `datetime.UTC`, rejecting custom mutable timezone aliases
before public validation, hashing or copying can invoke their hooks.
Existing public readers and their historical hashes are unchanged. Invalid
original publication/eligibility fields cannot be reset into valid copied values.

The separate `capital-owned-source-v1` root binds SHA256 of exact canonical
configuration bytes, the configuration hash, and the complete dataset hash.
This is not an alias to public owner frame identities, an authenticated source
receipt, a qualified dataset factory, or permission to skip risk checks. No
caller-provided prepared source, risk state, cached approval or account balance
is accepted by a public evaluator; the implemented panel creates its owned
snapshot internally. No global cache or filesystem/network operation is added.

All original source/execution/promotion flags remain false. Snapshot integrity
does not qualify latest-vintage history, action coverage, costs or economics.
The helper is consumed by private daily preparation and the complete panel;
this helper alone does not constitute that evaluator or source qualification.
Reviewed epoch preparation passed its unchanged750-session120s/512MiB guard
in42.725s; that does not certify the original-event owner or full-grid workload.

Next: verify the implemented [panel](etf-capital-panel.md) at corrected source,
preserve original account/risk/admission at every boundary, and measure the
full workload before executable freeze and a separately qualified authorized
economic evaluation. Never slice a terminal split-adjusted history backward.
