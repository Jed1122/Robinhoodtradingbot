# Scoped capability evidence (development only)

The existing `CapabilityManifest` now supports an additive version-2 `verifications` history.
`load_capability_manifest` remains the only manifest loader. Version 1 keeps its exact shape
and old evidence categories; no legacy record, artifact or historical hash is rewritten.
Version 2 requires the history field, even when empty. An absent or invalid field is not
interpreted as positive evidence.

`CapabilityAssetClass.OPTIONS` is a capability-metadata tag, deliberately separate from the
legacy order domain's `AssetClass`. It cannot make an option constructible through the old
single-instrument order validator. The legacy single-category `require_capability` gate
always denies positive options capability; it cannot bypass the new dimension requirements.

## Independent witnesses

Each immutable `CapabilityVerification` is bound to an exact provider and operation, one
dimension, an existing sanitized `CapabilityEvidence`, a status, expiry and applicable
opaque identity references. References must be random/opaque local commitments, not account
numbers, credentials or predictable hashes of private identifiers. They are not authentication
proof. Neither hashes nor a caller-created manifest prove that observations actually occurred.

| Dimension | Required evidence category | Binding |
| --- | --- | --- |
| Public | Documented | Exact provider/operation |
| Session | Schema declared | Exact schema digest and session reference |
| Account | Authenticated read verified | Exact schema digest and account reference |
| Runtime | Authenticated read verified; write-reviewed for review/place/cancel | Exact schema digest, account and runtime references |

Negative and unknown witnesses can retain unsupported findings. Committed evidence cannot
contain account data. Synthetic witnesses are retained for tests but always denied by
assessment. Public/session observations never imply account or runtime verification.

All nine currently reviewed options tool names are classified as options metadata during
schema discovery and remain locked. Discovery does not invoke any option operation, verify
an account or establish that Codex-session access works unattended on DigitalOcean. Tests
use fabricated declarations only; no fresh authenticated capture was performed.

## Assessment and preserved denials

`assess_operation(manifest, provider=..., operation=..., context=...)` is a pure diagnostic.
The context supplies current UTC time, expected schema digest and identity references.
It selects the latest witness for each matching operation/dimension/identity scope:

- Missing, future, expired, synthetic, unknown, denied or schema-mismatched evidence fails.
- A newer denial or expired witness never falls back to an older positive witness.
- Other accounts, runtimes, sessions and operations cannot supply a missing witness.
- Conflicting or duplicate same-time witnesses are rejected, independent of input ordering.
- Historical negative witnesses remain present when a later verified observation supersedes
  their current verdict; no destructive history rewrite is performed.
- Existing operation locks and unsupported records remain effective. A result must include
  each of the four distinct dimensions exactly once to report complete evidence.

`evidence_complete` is diagnostic only. `production_eligible` is permanently false. The
canonical options configuration still requires `live_supported: false`. There is no new
transport, credential path, authenticated capture, account-permission assertion or adapter.
The legacy Markdown capability matrix remains a view of legacy evidence categories; use
the scoped diagnostic for current dimension verdicts rather than interpreting that table
as fresh account/runtime validation.

## Still required

This is not completion of the official broker integration milestone. Official response
parsers and fake transport contracts, review-to-intent equality, final economic checks,
durable pre-submission intent, ambiguity reconciliation, cancellation lifecycle and
operation-specific operational evidence remain unfinished. Account settlement and intraday
regimes must be verified, not inferred from the date or options approval level. See the
[dated public/session audit](options-official-capabilities.md) and
[migration checkpoint](options-migration-validation.md) for the broader boundaries.
