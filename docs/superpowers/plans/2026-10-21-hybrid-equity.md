# Hybrid equity implementation

Approved in chat 21 October 2026. Base: efaed4b494cc33e4dd547d726e5e0dcc3a137fb5.

Goal: extend the existing kernel into a source-backed hybrid equity application.
No mandatory paper period. No live authority is granted by implementation.

- [x] Canonical opt-in hybrid policy; preserve legacy hashes and live envelopes.
- [x] Exact lot accounting, three exits, reservations, settlement, risk, simulation.
- [x] Durable experimental account journal, scheduler, reports, authenticated API.
- [x] Source-backed research and reproducible comparisons (independent worktree).
- [x] Responsive static dashboard (independent worktree).
- [x] Integration, regression, security, bounded experimental deployment verification and limitations.

Frozen contracts: dashboard reads `/api/hybrid/snapshot`, controls only pause,
resume_research and kill. Research exposes `research_snapshot()`. Monetary API
values are decimal strings. No invented observations or strategy qualification.
Single integration owner controls economic/risk/execution/persistence composition.

User decisions: isolated extension; no added recurring expense; existing $12/month
droplet counted; optional experimental paper; separate explicit live authorization.
Existing Task5 results and cost rejection remain untouched. No qualifying strategy
or complete unattended authentication verification is currently established.

Implementation evidence and remaining external qualification/integration work are in
[hybrid-verification-2026-10-21.md](../../hybrid-verification-2026-10-21.md).
Completion of the experimental extension does not establish live readiness.
