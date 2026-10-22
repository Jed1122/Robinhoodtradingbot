# Producer terminal closure clarification

Implementation status: pending. Every historical attempt still blocks admission;
there is no completed public producer/CLI. This is not the intended final one-shot
behavior. Root freezes the following clarification before implementing history.

## Why the distinction is necessary

The earlier text required a terminal receipt before final lock/handler cleanup and
clock/shutdown checks, while also requiring every uncertain final acknowledgement to
block future attempts. A lost successful return and a failure after that receipt can
leave identical retained files and an available lock. Another receipt only moves the
last acknowledgement gap. Files cannot prove that a past caller received success.
Independent read-only design analysis identified the same ambiguity; root owns the
resolution below. No trading, risk or worker control is changed.

## Historical facts and current success

1. Complete every owned source/build/probe/render operation and all four-file
   flushes, readbacks, loader checks and publication-file receipt acknowledgements
   under the original producer clock and shutdown gates. The probe must already be
   completed and removed; no native action may remain pending or ambiguous.
2. Only then construct one closed terminal **facts** record, binding that complete
   evidence chain, namespace and original in-window completion clock. It must not
   assert that the caller received success or that its own write/close was acknowledged.
   No native dispatch, worker start, installation or credential operation follows it.
3. Current caller success still requires acknowledged terminal durability, every
   descriptor/lock/handler cleanup, namespace identities, original window/shutdown
   checks and bounded CLI formatting. Any failure suppresses the current return.
   Reading a file, including a complete terminal file, cannot replace these checks.
4. A later attempt may recognize **historically complete native work**, rather than
   reconstructing the prior caller's result. It must acquire the actual permanent
   exclusive lock and validate the entire closed source/build/probe/render/release/
   terminal chain and exact inventories/identities. It must obtain fresh actual
   flush/readback acknowledgements for that intact historical namespace. Readable
   bytes alone are insufficient. It never rewrites bytes, modes, records or identities.
5. Such recognition can admit only a **different** source and only its fresh complete
   operation sequence. It cannot return the old manifest as a successful producer
   result, deploy it, replay an old action, refund an attempt or adopt an old native
   acknowledgement for current action authority. The same source always remains denied.

A missing/partial/malformed terminal record, incomplete native operation, invalid
original completion clock, failed fresh flush/readback, substituted namespace or
unknown inventory blocks new production. A post-facts caller-only loss of return or
cleanup acknowledgement does not erase independently verified historical native facts;
it also never establishes that the previous invocation succeeded. The earlier blanket
post-receipt wording is deliberately narrowed to distinguish these different claims.
All current-call elapsed-time and fail-closed controls remain mandatory.

This is reconciliation of intact completed facts, not incident repair or resume.
Partial histories stay blocked; there is no new recovery command, operator approval,
automatic pruning, image/container deletion or trading authority. The final public
producer, history validator, final-gate tests and whole-branch acceptance remain
incomplete. Native proof, scheduled research, stock data/strategy qualification and
broker reconciliation are separate gates.
