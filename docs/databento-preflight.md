# Databento local credential and cost preflight

This is a standalone diagnostic, not a market-data importer or broker integration.
It cannot download time-series data, submit batch jobs, activate a subscription,
manage an account, place orders, or produce economic evidence.

## Safe credential entry

Rotate any key previously shared in chat. Do not paste its replacement into chat,
source code, a shell command, or a Cloud task. Use an existing, user-owned directory
outside the project with mode `0700`. For example, create a dedicated directory
`/Users/jedweinstein/.robinhood-options-research` with those permissions.

From the repository with its verified Python environment:

```sh
PYTHONPATH=src python -m trading_bot.cli.databento_preflight store-key \
  --credential-directory /Users/jedweinstein/.robinhood-options-research \
  --native-dialog
```

On macOS, a hidden local dialog requests the replacement key. Its result is captured
inside the process and never printed or placed in command-line arguments. Cancel
or timeout denies the operation. Do not send screenshots of credential entry.
Without `--native-dialog`, an interactive terminal uses two hidden prompts and
refuses any fallback that would echo input. Pipes and key-value CLI flags are not
supported. Setup does not connect to Databento.

The file `databento.key` is published with mode `0600`, using the existing
descriptor-relative, no-follow, no-overwrite storage primitives. The directory
must already exist. A different existing key is never overwritten. Loading rejects
symlinks, multiple hard links, excessive size and unsafe permissions. This is a
restricted **plaintext file**, not an encrypted password vault; same-user programs
and machine administrators may access it. Do not back it up to shared storage.

## Preview first

```sh
PYTHONPATH=src python -m trading_bot.cli.databento_preflight estimate \
  --credential-directory /Users/jedweinstein/.robinhood-options-research \
  --symbol SPY --schema cbbo-1m --start 2025-01-02 --end 2025-01-03
```

This default prints the proposed request without opening credentials or making a
network request. Dates are UTC midnight, start-inclusive/end-exclusive. The example
is a one-day integration/cost pilot, not a selected research period or holdout.

Adding `--allow-metadata-network` authorizes one GET to the fixed official
`https://hist.databento.com/v0/metadata.get_cost` endpoint. TLS verification is on;
environment proxies, redirects and retries are off. There is a 30-second total
deadline and a 512-byte response bound. Only a finite nonnegative JSON numeric USD
estimate is accepted, using Decimal parsing. Raw provider responses, credentials
and exception details are never printed.

The fixed dataset is `OPRA.PILLAR`. Default parent mode accepts one to four
alphabetic underlying roots and `definition` or `cbbo-1m`. Explicit
`--stype-in raw_symbol` accepts one to 100 unique standard-format SPY option
symbols, preserving their three ASCII spaces after `SPY`, and supports only
`cbbo-1m`. The encoded expiry is interpreted as 2000–2099 and must be a valid
calendar date; the encoded strike must be positive. Invalid or mixed modes,
duplicates, adjusted-root strings, wildcards and `ALL_SYMBOLS` are rejected,
not repaired or expanded into a broader query.

Syntax validation is not proof of deliverables, historical availability or
tradability. No exact-contract selector or downloader is included. Underlying
history, corporate actions, calendars and other costs are not estimated by this
command. Repeat a parent-mode estimate with `--schema definition` to quote
definitions separately; do not repurchase the existing archive.

This **offline-only synthetic syntax example** does not select a research contract
and does not read a key or contact the provider:

```sh
PYTHONPATH=src python -m trading_bot.cli.databento_preflight estimate \
  --credential-directory /Users/jedweinstein/.robinhood-options-research \
  --stype-in raw_symbol --symbol 'SPY   250117C00500000' \
  --schema cbbo-1m --start 2025-01-02 --end 2025-01-03
```

Repeat `--symbol` for each explicitly selected contract. Before making a real
estimate, freeze and verify the private contract/date selection manifest; a
cheap subset is not automatically sufficient research coverage. See the
[scope and estimate record](options-data-budget-scope.md).

## Interpret the result correctly

- A successful estimate is not a download, economic result, approval to spend,
  entitlement verification, or a guarantee of the eventual charge.
- `credits_remaining` stays `null`: verify credits in the provider's Billing page.
- `download_authorized`, `download_entitlement_verified` and `economic_evidence`
  remain false. No trading flags or canonical risk limits are changed.
- `network_used` denotes an attempted metadata operation, including uncertain
  transport failures; it does not certify that the provider received the request.
- The diagnostic does not verify licenses or local/Cloud usage rights. For the current
  private historical research scope, the operator has attested permitted use and local
  retention and directed us to proceed without requesting a separate agreement document.
  That does not authorize redistribution or raw-data access by Cloud agents. See the
  [current acquisition decision](databento-acquisition-next-steps.md).
- Historical usage limits should be configured in the provider portal, but the
  documented limit blocks requests after usage exceeds the limit; do not treat
  this as a guaranteed exact spending cap or protection for live-data usage.

Official sources checked 2026-09-18:
[API key protection](https://databento.com/docs/portal/api-keys),
[free metadata and cost estimates](https://databento.com/docs/api-reference-historical/metadata/metadata-get-cost),
[billing and usage limits](https://databento.com/docs/portal/billing).

## Verification scope

Automated tests use invented credentials, temporary private directories, mocked
HTTP transport and denied sockets. They verify the local boundary, not a real
account's authentication, entitlements, credits or data quality. No authenticated
tests or data downloads are part of CI. Keep independent economic, technical,
account/capability and operator-authorization gates unchanged.

## Operator preflight — 2026-09-18

After the user confirmed rotation, the replacement key was entered in the local
hidden dialog and stored outside Git. No key value is retained in this report.
The user reported $125 unused credit; that is an operator report, not a balance
verified by this diagnostic. Four free `metadata.get_cost` calls succeeded:

| UTC range, end exclusive | SPY.OPT schema | Estimated USD |
| --- | --- | ---: |
| 2025-01-02 to 2025-01-03 | cbbo-1m | 0.574408471584 |
| 2023-01-01 to 2026-01-01 | definition | 11.435879766941 |
| 2023-01-01 to 2026-01-01 | cbbo-1m | 396.336761265993 |
| 2025-01-01 to 2026-01-01 | cbbo-1m | 141.845587790012 |

Quotes were received at 23:55:17–23:56:04 UTC. These are account/request-specific
estimates, not charges or guarantees. Even one full year of broad SPY option-chain
minute quotes exceeds the reported credits before adding other data. Do not
download the broad history. A later acquisition plan should freeze the hypothesis
and selection rules, record the operator-attested permitted-use scope, validate
coverage and quote the necessary contract subset
before requesting approval for any credit use. A small sample can validate the
importer but cannot establish an economic edge or satisfy the holdout requirements.

No time-series data, batch job, live feed, account-management operation or broker
call was requested. Download and trading authorization remain false.

### Subsequent acquisition continuation

At `2026-09-19T00:45:38.965782+00:00`, one additional free cost-only request refreshed
the exact three-year SPY definition scope above: **$11.435879766941**. The 68 diagnostic
tests passed immediately beforehand. No download or credit expenditure occurred.
The operator no longer requires supplying a separate OPRA agreement; existing private
use/local-retention permission is operator-attested, not provider-verified. A separate
definitions-only acquisition of up to $12 in existing credits is now explicitly
approved, with no cash charges, subscriptions, quote downloads or live data. The
billing portal initially required browser sign-in. After the operator signed in,
the portal confirmed $125 credit and $0 due; one exact-scope $11.44 definitions-only
batch was submitted at 2026-09-19 00:53 UTC and accepted as queued. This browser action
does not add download capability to the cost-only diagnostic. Completion, final cost
and local files remain unverified; see the acquisition guide before any follow-up.
