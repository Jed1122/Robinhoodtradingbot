# Current stock decision validation and release boundary

Task 5 implements current stock research through portfolio proposals. Long-term
stocks are evaluated separately from tactical holdings reviewed after one and two
calendar months. Historical profitable outperformance and a mandatory paper wait
are not release gates; returns remain unproven.

## Implemented

- Opt-in official-provider discovery/enrichment profile, source-bound current
  financial/price evidence, held/watch priorities and successful-cohort rotation.
- Separate company-quality and tactical rankings, explicit missing data and
  scenario assumptions; no invented expected returns or profit probabilities.
- Cash-only allocation ceilings, exact ownership joins, monthly holding reviews,
  principal/partial/trailing profit proposals, lot basis and estimated tax
  accounting. Proposed proceeds never become available cash.
- Restart-safe source readback, immutable versioned reports, optional minimal
  read-only dashboard export and optional caller-owned durable watch publication.
- Default-false execution authority, current source/control/issuer/account/child
  expiry fences and independently reviewed failure behavior.

## Verified locally

The combined 55-file current-stock and shared-source safety selection passed
1,511 tests on Python 3.12.13 and 3.14.6, with native exit 0 on each version
(164.10 and 155.36 seconds). The final report schema-downgrade correction was
then verified in the affected 70-case plan/report/watch/cycle selection on both
versions, also with native exit 0. Genuine failing counterexamples were preserved
before correcting stale review permissions and report schema downgrades.

The frozen dashboard passed all 83 frontend tests, TypeScript, production build
and independent counterexample rechecks for counts, omitted-row expiry and cached
expired/unhealthy actions. Architecture checks passed (185 cases); whole-source
Ruff and strict mypy passed (494 files). Bandit reported no identified issues;
existing suppression/comment warnings were retained. These are software checks
with fictional account fixtures, not investment-performance evidence.

Bounded official read-only metadata, scanner preview and financial-response
checks verified the requested provider columns/filter shapes and normalizer.
They do not prove indefinite background authentication, complete market/news
coverage, profitable selection or an operational deployment.

## Remaining project work

Complete the release CI/merge verification, then integrate the portfolio owner
with actual dedicated-account snapshots, supported issuer identity, authoritative
sessions and official order review/submission/fill reconciliation. Recheck actual
pending orders and atomically reserve cash before any execution. Verify the
external scheduler, storage retention/alerts and authentication behavior on the
intended runtime. No local development session supplies that operational proof.

Live trading remains disabled. It requires a separate, explicit user-controlled
activation after the actual broker and deployment checks. No credential material
was read. No actual order review/submission/cancellation, transfer or deployment
was performed. See [configuration, commands and limitations](current-stock-selection.md).
