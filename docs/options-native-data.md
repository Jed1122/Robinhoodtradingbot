# Native options research data

## Implementation status

Native SPY minute-bar scanning and canonical resource controls are implemented.
Private bar storage, historical source verification, verified session/contract inputs,
the imported-data shortlist and complete quote coverage remain subsequent tasks in
the [approved integration plan](superpowers/plans/2026-09-25-native-options-data-integration.md).
There is not yet a native-bars CLI or a real-data economic result.

## Intake boundary

`NativeBarRequest` fixes the query to `XNAS.ITCH`, `ohlcv-1m`, `SPY`, raw-symbol input
and instrument-ID output. `scan_bars` accepts only DBN versions 1–3 with the exact
request bounds and schema. It checks dated, non-overlapping symbol mappings and
monotone minute-start timestamps. This structural mapping check does not prove when
the mapping or a bar was historically available.

Prices remain nullable integer nanounits; timestamps remain integer nanoseconds.
Undefined, nonpositive and inconsistent OHLC values are retained as rejected
observations. Byte-identical same-key repeats are retained as duplicates; conflicting
repeats invalidate the entire stream. Duplicate state is limited to the current minute.
No missing bar is fabricated, and a minute bar is never an executable quote.

Callbacks are provisional until `scan_bars` returns after complete DBN and compressed
EOF, checksum and SHA-256 validation. Consumers must discard staged results on any
failure. Multiple compression frames may encode one DBN document; concatenated DBN
documents, unknown metadata extensions, truncated records and trailing garbage deny.

The existing definitions scanner shares only its byte-reading/decompression helpers;
its request policy, records, validation semantics and evidence format are unchanged.

## Configuration and authority

The one canonical `options.native_data` graph is disabled in ordinary profiles.
`configs/options/native-data/simulation.yaml` explicitly enables offline intake.
PAPER, SHADOW and live modes deny native-data activation. Strict integer ceilings in
the canonical config and safety envelope can only tighten: 512 MiB compressed,
4 GiB expanded, 256 MiB metadata, 10,000,000 records and 1,000,000 native identities.
The decompression window remains capped at 128 MiB. Part/manifest ceilings are also
declared now for the subsequent private-storage implementation.

Every intake profile has immutable false values for historical availability,
economic evidence, production eligibility, evidence promotion, download authorization
and live authorization. Integrity checks do not grant data usage rights or confirm
source semantics. No credentials, network calls, broker capabilities, purchases,
deployment or risk-limit changes are introduced.

Existing capital assumptions and safety controls remain unchanged. These synthetic
tests validate the software boundary, not an options strategy's economic performance.
