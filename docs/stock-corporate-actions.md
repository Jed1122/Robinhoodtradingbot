# Retained corporate-action observations

`market_data.stock_corporate_actions` parses the original JSON **result-string
bytes** returned by `mcp__codex_apps__alpaca_get_corporate_actions`. It preserves
the bytes/hash, request and UTC receipt clock. It neither contacts Alpaca nor
constructs a complete corporate-action, tax or cashflow book.

Construct `StockCorporateActionsRequest(symbols=(...), start=date(...),
end=date(...), limit=1000, sort="asc")`, then call
`parse_stock_corporate_actions(content, expected_sha256=..., request=...,
received_at=...)`. The closed source profile supports cash dividends and forward
splits. Unknown groups/fields, duplicate IDs/JSON keys, malformed dates/rates,
cross-symbol/request data and response counts above the declared limit fail
closed. The profile requires unfiltered action types/CUSIPs/IDs and an explicit
inclusive date/symbol range. A new source shape needs a reviewed profile change;
unsupported actions are never silently dropped.

Known missing/null CUSIPs, dates or rates remain `None`, with separate native
missing/null field lists. Numeric JSON rates are parsed directly to bounded
`Decimal`, preserving exact decimal values independently of the ambient context;
no binary-float arithmetic is used. CUSIP leading zeros, native action dates,
row/group order and optional currency remain intact. No currency is inferred from
the symbol or foreign flag. No date is moved to agree with a separate source.

`audit_stock_corporate_actions(observations, as_of=...)` reparses the original
evidence and rejects mutated DTOs or future receipts. It counts returned cash
dividends/forward splits for every requested symbol, reports unresolved fields,
pagination visibility, limit saturation and formatted process-date ordering.
`structural_checks_passed` describes these checks only. All authentication,
complete-book, historical-availability, cashflow, source/investment and live
qualification flags remain false. Original receipt time is the availability
bound; process/ex/record/payable dates are not publication timestamps.

The [official Alpaca reference](https://docs.alpaca.markets/us/reference/corporateactions-1)
defines an inclusive process-date interval, a total response limit and continuation
tokens. It also warns creation time is not guaranteed. HTTP `data_quality=complete`
can still contain processed incomplete records. The connected tool exposes
neither `data_quality` nor a page-token input, and the retained result omits
pagination/quality metadata. Fewer rows than the requested limit proves neither
pagination completion nor an exhaustive/final action history. Even an explicitly
null continuation token does not prove an exhaustive action book. A formatted
grouped response need not retain global HTTP process-date sorting; the audit
reports the observed order without sorting or rewriting the source.

For the separately retained NVIDIA sample, a ten-for-one ratio and June 10
ex-date can be compared to the [retained June issuer FAQ](https://s201.q4cdn.com/141608511/files/doc_downloads/2024/06/nvidia-2024-stock-split_faq_investors.pdf).
Its record date and distribution timing must be compared separately; an agreeing
split factor does not resolve differing native record/payable dates. That audit
is private evidence, not hard-coded source correction or point-in-time proof.

Next: use the observations as explicitly limited action context, independently
reconcile issuer dates/currency and pagination before any use requiring them,
and keep strategy returns, tax/accounting and trading qualification separate.
