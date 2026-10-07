# Local lifecycle and delayed-fee recorder integration

This implementation connects checked local lifecycle facts to the existing cost
receipt sink. It does **not** implement an authenticated Robinhood write adapter,
prove broker fee finality, authorize a trade, or qualify an economic result.

## Execution and accounting boundary

`CommittedCostRecording.publish()` accepts only an account-bound `EconomicEvent`
whose payload is `Execution`. It freezes the fact with the existing canonical
codec, then uses `uow.economics` to publish economic and execution effects in the
same SQLite transaction. Only after commit and transaction exit does it invoke
the observer. It introduces no new ledger, migration, risk configuration or
provider transport. An in-process lock serializes its calls; this is not a
cross-process lease or a deployed execution owner.

If commit fails or its outcome is uncertain, this object latches for independent
reconciliation. No observer is called and no transport retry exists. If the
optional recorder fails after commit, financial facts remain authoritative;
later valid economic facts can still be reconciled while this recorder stays
disabled. A returned `receipt_unavailable` must not be treated as calibrated cost
evidence. Exact duplicate journal facts never receive a new receipt timestamp,
including after restart. A crash between commit and recording therefore leaves
an honest evidence gap. There is no atomic transaction across SQLite and files.

## Same-session lifecycle projection

`EtfCostObserver.observed()` uses the common lifecycle reducer after the durable
boundary. Accepted starting responses must be submitted/rejected with zero fills;
initially filled responses remain unsupported. Event IDs, native execution keys,
fill IDs and contiguous fill ordinals are checked. Conflicting delivery,
overfill, account/order mismatch and future occurrence timestamps deny and latch.
Canonical independent snapshots prevent callbacks from changing a checked fact.

Partial fills, cancel races, confirmed cancellation, rejection and expiry retain
their distinct outcomes. Observed per-fill charges do not establish final order
fees. An identical delivery preserves its original receipt clock. Invalid facts
cannot silently increase exposure or change a committed economic outcome.

Expiry is represented by additive `terminal_v2` receipts in
`etf-execution-receipt-v3`. Existing v1 terminals and v2 same-session fee receipts
retain their schemas and hash preimages; legacy terminal receipts do not accept
new expiry semantics.

## Fees arriving after a recorder has closed

`diagnostics.etf_fee_attachments.publish_fee_attachment()` links an explicit
component observation and original source bytes to a terminal checkpoint. It
never reopens the old clock session. Every component (`commission`, `sec`, `taf`,
`cat`, `other`, `total`) is required as an exact decimal string; missing is not
zero. Component totals and derived report arithmetic are checked before immutable
publication. A document hash proves linkage, not provider authenticity, finality
or the correctness of a caller's component classification.

The first terminal binding is immutable. Exact retries validate existing bytes,
restore directory durability after interrupted publication and return the same
attachment without requiring a new clock sample. Conflicts deny. Original
execution/arrival/fill clocks are unchanged. Fee observation time is separate.
Reconciliation of corrections to an already attached final document remains
unsupported rather than overwriting economic history.

From a clean committed checkout, retain documents outside Git in current-user
directories mode 0700 and files mode 0600, then run:

```sh
PYTHONPATH=src uv run python -m trading_bot.cli.etf_observations attach-fees \
  --input-root /absolute/private/receipts \
  --manifest-hash CHECKPOINT_SHA256 --order-hash ORDER_SHA256 \
  --fee-components-file /absolute/private/fee-components.json \
  --fee-source-file /absolute/private/original-confirmation

PYTHONPATH=src uv run python -m trading_bot.cli.etf_observations link-costs \
  --input-root /absolute/private/receipts --manifest-hash CHECKPOINT_SHA256 \
  --fee-attachment-hash ATTACHMENT_SHA256 \
  --report-dir /absolute/private/reports
```

Exit 2 means unqualified diagnostic output, not operational success. Reports
remain customer-unauthenticated, calibration-unverified and non-promotable.
Default `link-costs` behavior is unchanged when no attachment is supplied.

## Remaining broker and research work

Authenticated nonempty order/fill mapping, final fee semantics, protected
review/place/cancel transports, durable pre-send reservations, runtime leases and
trusted worker composition remain independent prerequisites. A manual trade or
later activity CSV cannot reconstruct the recorder's causal local clocks.
Complete historical execution coverage, accepted after-cost economics, eligible
paper/shadow observations and deployed recovery are not supplied by this local
integration. The Alpaca historical waiver remains applicable to exploratory
research and does not fabricate missing input observations.
