# Bounded filing-source corroboration

This audit advances the source investigation for the retained stock filing sample.
It changes no market-data parser, qualification flag, strategy, order or deployment.
Selection used the prior frozen source-calibration rule, not a return estimate.

Root rehashed the committed company-enrichment and filing-facts archives through
`read_stock_observations`. One broker filing ID matches one retained index entry:
AGX, form 10-K, filed March 26, 2026. The broker ID is a 36-character identifier;
it does not have SEC accession syntax. No automatic accession conversion was made.

Public SEC search/index evidence identifies Argan Inc, CIK `0000100591`, accession
`0001104659-26-035216`, period January 31, 2026. The index lists the exact extracted
instance as `agx-20260131x10k_htm.xml`. Sources:
[filing index](https://www.sec.gov/Archives/edgar/data/100591/0001104659-26-035216-index.html),
[primary filing](https://www.sec.gov/Archives/edgar/data/100591/000110465926035216/agx-20260131x10k.htm),
[index-linked instance](https://www.sec.gov/Archives/edgar/data/100591/000110465926035216/agx-20260131x10k_htm.xml).

All 20 retained fact rows have explicit empty axes. Their entity text equals the
public index's CIK text in all 20 cases. This is scoped corroboration. It establishes
neither the broker field's identifier scheme nor universal issuer semantics, exact
UUID-to-accession mapping, context/unit equivalence or financial-value accuracy.

Original-instance retrieval was unavailable: the public-source agent's one ordinary
direct GET returned HTTP 403, and root's subsequent web opening of the index also
returned 403. No retry, authentication bypass or alternate access route was used.
The original XBRL bytes, contexts, unit definitions and numeric-value comparison were
not obtained. Public search metadata cannot substitute for those missing bytes.

The private, mode-0600 audit was written under an owned mode-0700 directory outside
all checkouts, flushed and rehashed from its stored bytes. Its SHA-256 is
`733286a5b1bae4e7db798ec1159fc832b3273d3d52858b1338d95c93e62f4b30`.
It contains receipt hashes, counts, public references and limitations; financial
values, broker identifiers and credentials were omitted. No new broker call occurred.
Source/strategy qualification, investment eligibility and live state remain false.

Next: obtain the exact index-linked original instance through permitted access and
retain its bytes/hash. Compare each reported concept QName, entity/context, period,
dimensions, unit and value without inferring decimals scaling. Only checked mappings
may advance under a scoped source contract. Price interpolation/calendar, corporate
actions, point-in-time membership and stock-strategy validation remain separate gates.
