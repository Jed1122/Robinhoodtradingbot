# Synthetic ETF pending-admission seam

This additive research seam preserves the legacy accepted `intent` fact and its
valid historical hashes. New `pending_intent` facts reserve cash and the complete
trial episode but remain `SUBMISSION_PENDING`; an explicit later acknowledgement
is required before an observed fill can affect cash or shares. No transport,
credentials, production account state or automatic promotion is constructed.

`admit_etf_pending_intent(request, candidate)` first reconstructs the trusted
history through the existing account owner. Invalid history raises. A rejected
candidate returns that unchanged state and no new order or reservation. A fresh
allowed candidate records only the matching pending order. Existing event or
order identities return a duplicate denial, even if the old order is rejected,
ambiguous, partially filled or accepted. Replay itself remains idempotent.

This is explicitly `synthetic-account-limits-only-v1`, not the full production
pretrade gate. Existing canonical sizing, exposure, cash, losses, trial capacity
and the new pending-BUY common activity check remain account-owned. The risk
reference remains $100 for both hypothetical cash tiers. Protective SELL facts
do not apply the entry activity gate. Prices, instrument terms, settlement and
account effects still require independently validated synthetic facts.

An ambiguous acceptance retains both cash and trial reservations and blocks a
new entry. Reconciliation labels must agree with already observed filled
quantities; they cannot invent shares/cash or erase a partial fill. Late
nonterminal acceptance after the intent expiry denies. Confirmed unfilled
rejection releases its reservation without replenishing consumed historical loss.
Pending cancellation and residual exposures remain incomplete.

## Verified scope and next steps

Focused tests cover explicit acknowledgement, invalid early fills, ambiguity,
partial quantities, rejection, expiry, reconstruction, zero-effect denial,
duplicate/retry prevention and unchanged legacy hashes. Independent review
identified and then verified the duplicate-admission repair.

The next composition must separately schedule decision, actual synthetic
submission and acknowledgement timestamps; enforce raw quote/control epochs,
positive latency, side capacity and exact event ordering; apply effective-date
fee evidence; and evaluate protective exits on every eligible quote. It must
continue using this single account owner. Neither this seam nor its tests qualify
native quotes, establish candidate economic results or begin qualifying
paper/shadow clocks. Live execution stays disabled.
