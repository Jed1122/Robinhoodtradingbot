# Options import row contracts

## Massive REST options quote row

`trading_bot.market_data.massive_options_rows` is a credential-free parser for one response row
from Massive's documented options quotes endpoint, retrieved 2026-09-18 UTC:
[Options REST quotes](https://massive.com/docs/rest/options/quotes).

It accepts exactly these documented row fields: `ask_exchange`, `ask_price`, `ask_size`,
`bid_exchange`, `bid_price`, `bid_size`, `sequence_number`, and `sip_timestamp`. Prices are
preserved as exact `Decimal` values; a zero bid is retained, but negative, non-finite, or crossed
prices are rejected. Exchange IDs, sequence number, and `sip_timestamp` must be nonnegative
integers. `sip_timestamp` stays an exact epoch-nanosecond integer; the parser never constructs a
Python datetime and therefore cannot silently truncate it to microseconds.

`MassiveOptionsQuoteRow` itself also requires exact `Decimal` price and size fields. The parser is
the only boundary that normalizes JSON numbers to `Decimal`; direct construction with integers,
binary floats, booleans, or strings is rejected. Its source and size-unit labels are fixed and
cannot be replaced with an inconsistent value.

Massive documents bid/ask sizes as counts of round-lot orders (normally 100 shares). The row
parser preserves their raw integral provider values in `Decimal` fields and labels its source
`massive_options_rest_v3` and size unit `provider_documented_round_lot_orders`; it never
multiplies by 100 and never calls them option contracts.
This is deliberately a provider-row contract, not a claim that the values are executable depth.

The parser has no networking, credentials, account access, contract identity lookup, receipt
time, availability time, underlying quote, quality-policy decision, `OptionQuote`, or
`OptionsDataRecord` conversion. A later provenance layer must supply a verified
`optionsTicker -> contract_id, underlying` mapping, raw-byte hash, local receipt/availability
times, and independently timestamped underlying observation. Until then, the row cannot be an
executable quote or a complete domain record.

Input is bounded by the caller-provided canonical `BundleLimits`; malformed JSON, duplicate keys,
unknown/missing fields, unsupported values, and invalid limits fail with the repository's
sanitized `BundleError` codes and do not echo rejected payloads.
