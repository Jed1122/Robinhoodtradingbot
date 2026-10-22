# Stock filing dossier integration verification

Verified source revision: `0914482fe578c7d3c7a3b6aa0f4dcf276fc5b06e`.
This is a completed bounded evidence integration, not a complete investing platform,
a qualified investment strategy, or a deployed continuous service. The product goal
remains individual-stock discovery, research, risk-gated investing and monitoring.
Live execution remains disabled. No mandatory 60-day paper wait was added.

## Built and checked

- Closed native filing-catalog/facts normalization with exact optional states,
  original row indexes, native periods/axes and exact Decimal values. No decimals
  scaling, character-value fallback, guessed issuer mapping or missing-value repair.
- Exact filing-index/catalog/facts binding, current-cutoff revalidation, source
  availability and safe diagnostics for incomplete/ambiguous/contradictory chains.
- Filing-aware company dossiers and schema 3 reports. Existing no-new-source schema 2
  reports and legacy dossier hashes remain byte-identical through golden tests.
- Private publication from up to three committed capture archives, with all-input
  validation, no-symlink/owner/mode guards, nonblocking leases and complete source
  rehashing. Default single-capture behavior remains compatible.

The exact pure candidate 9edcc66 was independently reviewed and integrated as c010142.
A fresh whole-increment review of 68f207e returned NOT_READY with two Important
findings: later-cutoff evidence reuse and missing unrelated-index ambiguity denials.
Root reproduced both and the exact-false scalar variant (3 failing regressions),
fixed them, and preserved the existing architecture boundary by using explicit
field checks. Final source 0914482 passed:

- **2,214 tests; four optional encrypted-backup tests skipped** because local age is
  unavailable. Those skips are not backup/restore proof.
- Ruff across the checkout, strict mypy across 453 source/host files, expanded Bandit
  with zero findings, lock check 106 packages and diff checks.
- Actual retained native archive publication and independent report-byte hash check.

There was no second independent review after root's one RED/GREEN fix pass. The
initial review outcome is not represented as approval of the later revision.
The broader primary 1537d7e full suite remains separate and was still running at
this checkpoint; its results cannot be applied to this later source revision.

## Actual retained native result

Two previously authorized official research calls acquired one catalog page and a
facts response. Selection was frozen from the prior ten-company shortlist: the
alphabetically first company with an eligible 10-K, then its most recent observed
10-K. Ten actual non-text, explicitly axis-free catalog concepts were requested.
This is one source-shape calibration, not comparative stock selection evidence.

At `2026-10-21T23:47:37+00:00`, the actual publisher rehashed 27 observations from:

| Capture | Manifest SHA-256 |
| --- | --- |
| Prior company enrichment | `0b6f7bdd7a2add233e649ba83c4e9daa774bc3d743ad65f29a1a61b8f28f6a1b` |
| Filing catalog | `79163cd029ba9b58367012e0c39c9127e73b3dabaee4236c3b4fabfd4e8f6ab0` |
| Filing facts | `374969a5ecaf9319fccc52227e6c1cd73a63b6d421b7d50642c0b95bebb5178d` |

Published report SHA-256:
`aa1f6ec1ec48857f618b3cdd76ba668347fe62193728d4e513fa653c0eaf1951`.
It contains 10 company dossiers, one company with 20 bound facts for 10 requested
concepts, zero normalization denials and zero filing-evidence denials. Each fact
has a retained numeric value, reported nonempty unit and explicit empty axes.
SDK transport authentication is true; source/strategy qualification, investment
eligibility and every live flag remain false. No new provider/authentication call
was needed to publish the retained report. Raw payloads, identifiers and values
remain private outside Git. No account/order/transfer operation occurred.

## Acceptance decisions and limits

1. Filing Decimal documents use exact scientific strings and versioned identities;
   the shared portfolio codec is unchanged. A different representation would require
   a versioned consumer migration.
2. Ambiguous company indexes are all withheld with explicit safe receipt denials;
   no preferred vintage is selected. Conservative evidence omission is possible.
3. Cleanup failure denies a success result, although a complete verified atomic
   private report can remain. Operators must recheck such an orphan artifact.
4. Native private acceptance and central/full results remain root-owned evidence.
   Independent fictional tests do not replace actual native/full verification.
5. Archive hashes establish byte integrity, not provider truth or independent time
   attestation. Source acceptance requires a separate contract.
6. Units, entity identity, historical completeness and financial inference remain
   unqualified. No ratios or return estimates were inferred from these rows.
7. Investment merit, strategy approval, broker reconciliation, live authorization
   and deployment remain separate gates. This result cannot submit an order.
8. Adaptive acquisition, pagination merging and dashboard detail projection remain
   future implementation. This joined report does not become the worker's committed
   enrichment head automatically.
9. Hostile same-user filesystem mutation remains outside the inherited cooperating
   archive-lease threat model. Stronger production isolation needs separate work.
10. Validated partial captures remain inherited accepted inputs with incomplete-chain
    diagnostics; partial source coverage never becomes completeness or qualification.

No Minor findings were reported in this increment's independent review. The older
launcher fixture/input-documentation minor remains deferred in its separate ledger.

## Next concrete work

Expose bounded typed filing summaries in the individual-stock shortlist, then add
budgeted catalog/facts refresh work with durable capture lineage and cache replay.
Default enrichment already uses 25/32 calls, so adaptive work must reserve its own
bounded requests. Add authenticated dashboard GET polling; updating only the age
label does not refresh source data.

Finish repeated worker handoff and verify the external scheduled runtime on the
existing host. Resolve stock price/calendar/corporate-action and issuer/unit source
requirements, validate one frozen stock policy after costs/taxes, and connect that
policy to risk-gated order proposals and verified broker reconciliation. Actual
investing still requires separate user-controlled live activation; no source or
strategy flag may be promoted merely because software checks pass.
