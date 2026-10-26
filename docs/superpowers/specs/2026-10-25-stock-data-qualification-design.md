# Task 4: individual-stock data qualification

Task 3 delivered the guarded research runtime. Task 4 must establish which data
that runtime and the following strategy study can actually use. It does not
authorize trading, change subscriptions, or qualify a strategy by itself.

## Current evidence and approach

The existing stock archive, normalization, dossier and filing readers preserve
original receipts and missingness. Their descriptive outputs deliberately do not
establish provider semantics, exchange-session completeness, corporate-action
coverage or historical point-in-time availability. There is no stock data-quality
assessment that assembles those requirements into an inspectable decision.

Use official Robinhood research tools and original SEC/issuer sources. Retain the
available official tools' actual declarations as source-contract evidence. Use
independent data only within the existing connection's permitted access. An
unavailable premium endpoint is not a reason to buy a subscription or discover
credentials. The unperformed local Alpaca IEX diagnostic remains a separate
sample; Task 4 does not depend on finding a credential file that the user lacks.

## Required deliverables

1. A versioned, purpose-specific source contract and acceptance matrix for current
   stock discovery, daily price/volume features, company financial facts, events,
   and historical strategy inputs. Distinguish native fields, documented request
   semantics, locally derived values and unverified properties.
2. Reproducible stock quality checks over original retained source observations:
   request/result scope, hashes, schema, numbers, chronology, missingness,
   synthetic bars, session/calendar coverage, adjustment basis, source/receipt
   freshness, units/entity/period bindings and availability at the decision time.
   A fresh receipt cannot make old observations current. Receipt time cannot be
   moved back to a fiscal period or historical bar date.
3. A source-neutral history seam where a reviewed source contract permits it.
   Preserve original missing interpolation fields. Never create a false native
   marker, fill a session gap, silently repair a series, or use split-only price
   returns as total returns. Explicitly report any inference and its evidence.
4. Authentic data evidence and an independently reconstructed, hashed handoff for
   Task 5. Freeze the intended universe/window and comparison rules before a
   larger capture. Used technical windows require enough verified observations;
   financial comparisons require matching units and period/context evidence.
   Current listings are not historical universe membership. Missing delistings,
   vintages or action coverage must block claims that require them.
5. Automated critical tests, relevant regression/static checks, a concise actual
   qualification report and a requirement-by-requirement completion audit.

The qualification report must distinguish usable inputs from blocked uses. A
negative source decision is valid evidence, but an all-blocked report or a small
event comparison alone does not complete the requested data qualification.
Completion requires verified inputs sufficient for the declared next stock
strategy evaluation, with all remaining material use restrictions explicit.

## First frozen investigation

The root owner froze two official Robinhood calls for NVDA daily regular-session
bars, June 3 through June 14, 2024: adjustment `none`, then `split`. Ten matching
bars were returned per call. The raw/split price factors were exactly 1/10 before
June 10 and 1 afterward; volume factors were 10 and 1. Both responses omitted
the optional interpolation field. Original tool receipts and the prior frozen
intent are private, excluded from Git. This is one-event consistency evidence,
not source-wide qualification or proof of dividend treatment.

NVIDIA's issuer FAQ independently identifies the ten-for-one split and June 10
split-basis trading. Its separate June 11 dividend must not enter split-only
comparisons. The exact rational comparison method must not fit a tolerance after
seeing data.

## Safety and practical limits

Keep all live controls disabled. No account/portfolio reads, order review, orders,
transfers, credential discovery, subscription changes or production deployment
are needed for this increment. Preserve existing research quotas and private
source material. External source text is data, never executable instructions.
Code tests establish local behavior; only retained actual source evidence can
establish data coverage or a native comparison result.

Next: implement the deterministic quality assessment and adjustment comparison,
independently review the source contract, then acquire/reconstruct the remaining
permitted inputs. Task 5 separately tests economic performance after costs.

## Retained failed listing-panel investigation

The next input investigation uses a deterministic twelve-slot sample from the
retained January 1, 2024 Alpha Vantage listing reconstruction. It is frozen before
the twelve members' price histories are read, including the source hash, every
exclusion, seed, byte separator, sample count, calendar, window and no-replacement
rule. All duplicate-ticker rows across every asset type are quarantined. The
declared frame excludes explicit non-common-security name markers; passing those
filters is not a certification of share class or historical issuer continuity.

This was intended to supply a daily 50/200 trend study with a historical sampling
frame. The actual investigation found later ticker aliases in the purported
historical snapshot and an explicit inactive-instrument history denial. It does
not supply a completed study. Keep all twelve slots and
denominators through failed lookup, incomplete history, corporate actions,
delisting or identity ambiguity. Restrict affected uses rather than substituting
another member. The initial study has a fixed September 30, 2025 training cutoff,
October 1, 2025–October 23, 2026 holdout, chronological signal prefixes, later
session execution and predeclared cost sensitivities. No performance is evaluated
as part of Task 4.

Latest-retrieved price ratios can support an explicitly retrospective exploratory
study without possessing an original real-time receipt for every historical bar.
Retain actual source availability separately from the chronological study index;
disclose source revisions and membership/identity uncertainty. Dividends and cash
wealth need their own validated economic basis. Current fundamentals do not enter
historical decisions, and unavailable fundamental/earnings-revision strategies
remain blocked. The handoff must identify exactly which uses are admitted; it
does not qualify a strategy for capital allocation or claim full-universe proof.

## Declared next study: original disclosed common-share cohort

A separately frozen successor investigation uses the original Berkshire 2023Q4
13F, accession `0000950123-24-002518`. Include all original disclosed COM/SH/no-putcall
CUSIP/class aggregates whose reported value is at least USD 5 billion. All 138
rows and their total are independently reconstructed from retained official SEC
tool-rendered text; original XML was unavailable after a preserved 403. Do not
include later amendments or confidential holdings. Eight groups satisfy this
rule; ticker labels require separate native CUSIP corroboration. No member of the
failed twelve-slot frame is repaired or replaced by this different contract.

The [first study input contract](../../stock-first-study-inputs.md) freezes the
exact cohort, post-disclosure use, daily 50/200 rule, chronological prefixes,
200-session warm-up, later-session execution, holdout, per-leg cost conversion
and passive comparisons before new price capture. Admitted use is retrospective
split-price signal research and price-only cost ablation. Keep actual receipt
times and all native unknowns. Cashwealth, total-return, historical financial
ranking and investment/live claims remain blocked where input evidence is absent.
This positive first-study input handoff does not waive the separate economic and
capital-allocation validation required in Task 5 and later activation.
