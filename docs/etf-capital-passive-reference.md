# Source-owned mathematical SPY reference

`run_capital_passive_reference(CapitalPassiveRequest(...))` owns the original
five-symbol development dataset internally. It accepts a canonical capital tier,
contiguous original sessions with a preceding baseline, one approved round-trip
whole-percent friction level and explicit entry/estimated-exit fees. It accepts
no caller-supplied balances, prepared sources, comparison results or allocation
authority. This implements only the full mathematical SPY role, not the complete
four-reference statistical panel.

The hypothetical investment is initial cash less the entry fee, at the first
supplied opening with half the round-trip friction. It is intentionally NOT
admitted by the strategy's20% position/40% cash risk policy or claimed to be
executable. Mathematical fractional ratios are not broker lots or order support.

Raw prices remain separate from feature prices. For each date, the adapter
multiplies raw open/close by the cumulative declared split ratios effective after
the entry date and through that date. These are prices in INITIAL-share units,
not terminal/future split-adjusted prices. A dividend amount is converted using
its EX-date factor, never its payment-date factor. A split effective on the entry
date is already reflected in its raw opening and is not applied again.

The unchanged `run_etf_benchmark` cash/value engine computes the reference.
`kernel_result.shares` therefore represents initial-share units; `raw_quantities`
separately displays each day's corresponding raw quantity. Rounded display
quantities are never multiplied back to calculate NAV or entitlements. Exact
bounded products deny unsupported precision/range; the existing explicit28-digit
nonterminating-ratio approximation remains visible. Kernel API/hashes are unchanged.

Entitlements become receivables on eligible ex dates and cash on supplied payment
dates, including no-bar weekends. They are not reinvested automatically. First
entry-day ex dates receive no entitlement. Unpaid amounts remain receivable at
the horizon. Coincident post-entry splits/distribution ex dates remain unsupported
consistently with current action ownership. Missing/unknown action tuples deny;
empty supplied tuples still do not prove complete corporate-action coverage.

No sale, terminal fill, forced payment, settlement or operating-expense cash debit
is manufactured. Estimated liquidation friction/fees are a proxy, not paid cash
or realized trading P&L. Operating profit is a separate reporting overlay; it
cannot silently borrow against a fully invested reference. Sale/payment-after-sale
controls belong to the original-event account owner, not this uninterrupted
passive kernel. Taxes and genuine execution costs remain independently unknown.

The result binds original source/config identities, transformation version,
baseline/used sessions, capital, costs and the kernel request. Future declared
actions may change whole-source provenance without changing earlier numeric
values. Receipt/hash/calendar validity is not authentic acquisition, coverage,
rights or historical availability evidence. Latest-vintage chronology limitations
remain disclosed under the existing research waiver.

Source, cost, execution, economic, promotion and live eligibility remain false.
Policy-managed SPY, retrospective exposure matching and complete aligned reports
are implemented/reviewed in the [panel](etf-capital-panel.md). Next: corrected-source
release and full actual workload verification,
capital-specific immutable executable freeze, then evaluation only with qualified
authorized inputs. No broker/provider call, private-data inspection, deployment,
spending or risk-limit change is provided by this adapter.
