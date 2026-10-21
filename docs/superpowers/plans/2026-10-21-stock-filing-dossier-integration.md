# Filing-level financial facts in company dossiers

> Root uses superpowers:executing-plans and TDD. The parallel pure adapter owns
> only its three declared files; all integration and acceptance decisions stay root.

Base c8925e39bae7285525964777ebc37c6f4616f3bc. The objective is to connect the
actual two-call filing probe to existing company research, not leave another
unconsumed parser. Live execution, strategy qualification and collector mode stay
unchanged. Primary1537 remains frozen for full41316; no duplicate full or mutation.

## Task 1: Visible exact-filing evidence in dossier reports

Files: research/stock_dossiers.py, runtime/stock_dossier_report.py and focused tests.

1. Write raw fictional index/catalog/facts observation tests through the existing
   compiler; watch RED for unsupported evidence before changing source.
2. Normalize catalog/facts through the parallel frozen adapter. Group by exact
   requested filing ID and bind only a single unambiguous index/catalog/facts chain.
   Do not choose a preferred receipt, merge incompatible contexts or guess symbols.
   Independent sibling observations survive a source normalization/binding denial.
3. Record safe `filing_evidence_denials` using only reason codes and receipt hashes.
   Missing/ambiguous/contradictory source chains remain explicit. Future receipts
   stay excluded. No financial/character value appears in diagnostic output.
4. Add optional `filing_evidence=()` to build_stock_dossiers and a tuple field on
   StockDossier. Revalidate binding at the current cutoff and require its exact
   index collection to be present in the supplied filings. Attach only to that
   matched company's dossier. Retain all old aggregate currency/history/source gaps;
   add reported-unit/entity mapping gaps for the new evidence, never trade authority.
5. Preserve exact legacy report bytes and dossier hashes when no filing catalog/facts
   observations are visible. Exclude the new empty field from legacy serialization
   and legacy hash; retain schema_version2. When new filing sources are visible,
   use report schema_version3, new field and explicit denial list. Dossiers with
   filing evidence use a versioned v2 hash; no-evidence dossier hashes stay v1.
6. Verify two chronological fact rows, missing values, unknown units, all-false flags,
   actual contributing receipts, no future evidence, wrong scope, missing/ambiguous
   chain, malformed source, exact period mismatch and no foreign-symbol attachment.

Expected: new integration RED observed first, then all new/old dossier/report and
dashboard/worker/cache consumer tests pass. Do not relax the pure adapter or price
history admission to fit a native response.

## Task 2: Rehash multiple committed captures for private publication

Files: runtime/stock_dossier_report.py, publisher tests, docs/stock-dossier-reports.md.

1. Write RED for optional `additional_captures` on publisher, a tuple of at most two
   `(Path, manifest_file)` pairs. Existing root/manifest remains primary. Default
   empty preserves the existing single-capture bytes and private worker call path.
2. Validate the whole bounded input and unique canonical roots before reading or
   publishing. Open each through existing private no-symlink/owner/mode guards;
   acquire existing nonblocking archive leases and hold handles through reading.
   Honor an already-owned primary directory FD without reopening its lease. No new
   transport, credential, database or control operation.
3. Rehash every manifest/envelope through read_stock_observations, combine at most
   32 observations, then call the integrated compiler. Preserve duplicate receipt
   rejection. Any unsafe/missing/altered additional capture fails before publication.
4. For combined publication, add the exact ordered source manifest hashes (primary
   then supplied additional captures); do not put local paths or raw data in the CLI
   result. Output stays private, content-addressed, bounded, idempotent and live=false.
   Add repeatable CLI `--additional-capture ROOT MANIFEST` inputs. These are job
   references, not new investment configuration.
5. Test actual fictional capture -> rehash -> bind -> private report, tampering,
   duplicate/unsafe roots, malformed manifests, too many observations/captures,
   lock failure and close/cleanup failure. Preserve existing private-file semantics.

Expected: focused publisher/dossier/capture/worker/dashboard tests and architecture
pass; four optional age skips remain disclosed, not backup proof.

## Task 3: Review, central verification and actual retained probe

Integrate only the independently reviewed exact pure adapter commit. Root reviews
every owned diff, runs central stock/market-data/worker/dashboard/architecture checks,
Ruff/strict mypy/expanded Bandit/lock/diff, and obtains one fresh independent review
of the complete root integration. Fix substantive findings with RED/GREEN.

Then privately rehash the actual prior enrichment plus catalog/facts captures and
publish the joined report, reporting only hashes/counts/denials. Expected native
calibration: one company has20 bound filing fact rows if the actual profile matches;
all investment/source/strategy/live flags remain false. A mismatch is evidence to
report, not permission to weaken validation. Preserve the prior immutable reports.

This connects source evidence to existing company dossiers. Scheduled adaptive
filing collection, dashboard detail projection, strategy qualification and production
runtime remain separate implementation work, not consequences of this local report.

## Review focus

- Receipt replay, forged flags and similar-looking filing IDs cannot attach foreign
  evidence or backdate availability.
- Extra captures cannot read unsafe paths or publish partial/unverified source chains.
- Legacy cached dossier bytes/hashes remain reproducible when new sources are absent.
- Ambiguous/revised observations are denied explicitly instead of picked by iteration order.
- Missing units/periods/values never become currency, zero, ratios or trade eligibility.
