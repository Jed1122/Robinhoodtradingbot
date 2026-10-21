# Private stock evidence reports

The runtime report composes the existing typed normalizers and pure dossier assembler.
It does not contact a provider or issue recommendations. It rehashes a committed
observation archive, excludes future receipts, retains source hashes and normalized
provenance, and publishes private content-addressed JSON outside the source checkout:

```sh
PYTHONPATH=src uv run python -m trading_bot.runtime.stock_dossier_report \
  --archive-root /absolute/private/shortlist \
  --manifest CAPTURE_SHA256.stock-capture.json
```

`--as-of` accepts an aware UTC timestamp; the default is current UTC. The archive must
be owned mode 0700 and contain mode-0600 committed observations. Output is mode 0600,
file/directory-fsynced, content addressed, and idempotent for identical inputs and cutoff.
Reports exceeding 9,000,000 encoded bytes are denied before publication, matching the
bounded existing-artifact verifier; the source archive size bound is unchanged.
The command prints only status, artifact identity, counts and disabled live status.

Fundamentals, financial periods, earnings and filing indexes use their existing typed
normalizers. Whole-company history projection prevents one invalid company's prices
from invalidating all other companies, while the affected company remains quarantined.
History raw-price basis is retained only when the actual request declared `none`;
completion uses a conservative caller-declared cutoff before the receipt's current UTC
day. This does not establish exchange-calendar completeness, corporate-action accuracy
or vendor-certified bar completion. Quotes and other unprojected tools are explicitly
listed rather than represented as normalized dossier inputs.

Invalid collections appear in `normalization_denials` with the source identity and a
fixed reason; provider exception text is excluded. Duplicate receipts and contradictory
company joins fail the whole report. Missing values remain missing. Sources, normalized
hashes, projection context, static research questions and qualification gaps remain
available for later review. Every investment/qualification/live flag stays false.

Schema version 2 includes descriptive technical features from the same retained
history: raw price returns, simple moving averages, realized volatility, observed
volume measures and running-peak drawdown. Each summary retains the feature hash,
normalized/source/projection identities and all methodological limitations. The
complete normalized history remains in the dossier rather than being duplicated in
the technical summary. Raw close-times-volume is a proxy; currency, corporate actions
and actual exchange-session coverage remain unverified. No predictive score or
strategy eligibility follows from these descriptions.

Actual 2026-10-21 source binding returned nine `ineligible` technical summaries and
one `quarantined` summary, with zero calculated technical values: the 2,385 retained
ordinary bars omitted the optional `interpolated` field. Their value remains unknown,
not false. The tool declaration and response guide do not establish an omission
default. The dossier flags `history_interpolation_unknown`; the strict technical
prerequisite requires an explicit noninterpolated observation. Financial/earnings/
filing evidence remains available. Source semantics or a permitted alternative dataset
must resolve this gap before those metrics can be used.

The report records SDK receipt provenance, not authenticated HTTP wire frames or a
qualified historical dataset. A successful report is not a complete company thesis,
validated expected return, strategy approval or trading authority. The acquisition
worker and dashboard feed remain separate integration tasks.
