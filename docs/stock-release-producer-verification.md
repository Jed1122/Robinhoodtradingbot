# Stock release producer: implementation checkpoint

The [producer design](stock-release-producer-design.md) and
[implementation plan](superpowers/plans/2026-10-22-stock-release-producer.md) retain
the full build/probe/render/publication requirement. The producer is not yet runnable
or deployment-ready. This work grants no native build, source-data, strategy, broker
reconciliation or live-trading qualification.

Task1 is implemented and accepted locally at877924d. The supplied-data module checks
the bounded prepared Git archive without extraction and decodes only legacy quiet
build's terminal full-image-ID record. Intermediate aux IDs, progress/error/multiple
records and truncated output cannot yield a result. These are data functions;
constructing or copying their output does not authorize dispatch or publication.

Root observed74 missing-module REDs, then74GREEN. Three further REDs demonstrated
that directories without regular files could satisfy required-tree checks; the
corrected77-case group passed. Actual task-done acceptance passed323 combined
source/release/container/controller tests in14.48seconds with100% statement/branch
coverage over the new input module. Ruff passed, strict mypy passed461source files,
expanded stock-module Bandit exited0 without findings, and lock/diff checks passed.
Existing scanner comment/suppression warnings and the broader12inheritedLow host
script findings remain separate.

An actual committed Git archive using the prescribed file allowlist and forced
tar.umask0022 was parsed locally:4,864,000bytes and527entries. The retained Git comment
is supplied metadata, not independent authentication of repository history. No archive
was extracted, uploaded or built. The source-preparation command itself remainsTask3.

Task2 must implement the exclusive root producer namespace, durable one-use build
claim, bounded fixed Engine operation and exact resulting-image verification. Task3
must own source preparation, the fresh existing probe, scrubbed reviewed Compose
render, four canonical durable files, existing loader verification and final clock/
shutdown/context publication gate. One fresh whole-branch review and the eventual
actual source-specific full remain required.

The separate corrected-controller full is still running at8629cad in the frozen
runtime checkout, session55324/PID89926. It must not be duplicated or restarted and
cannot certify this later producer. Only after it actually terminates may another
full be queued. Actual native producer/probe proof, paused installation, OAuth lifecycle,
backups/restore, scheduled stock research, qualified data/strategies and nonempty broker
reconciliation remain independent. No mandatory60-day paper wait or automatic live
activation follows from this checkpoint.
