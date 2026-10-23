# Stock build framing and historical wire compatibility

## Observed problem

The exact bac162f/8294 public producer exited1 on2026-10-23 at04:25:54Z.
Its original child1914810 reported receive/OSError/errno104 and retained exactly
six attempted-build files. The269-byte HTTP/1.0 response has neither Content-Length
nor Transfer-Encoding. It contains a quiet image identifier but is close-delimited;
a connection reset cannot prove HTTP completion. There is no image receipt,
build-complete, probe, render, publication, terminal or release. Preserve this
failure and never replay8294 or the older479/a54 source.

The same daemon is Ubuntu docker.io29.1.3-0ubuntu3~24.04.2, built using
Go1.24.4 and running the already pinned binary. This is an Engine protocol issue,
not a financial-data, broker, strategy or trading-authorization change.

## Forward exchange

New producer requests use fixed HTTP/1.1, the existing exact endpoint/query,
Content-Length tar upload and Connection: close. Do not change build resources,
network policy, source capture, owner lease, original deadlines or one-dispatch
semantics. No fallback to HTTP/1.0, another socket, CLI build or repeated request.

Accept only one bounded200/application-json/identity response with a valid unique
Content-Length (HTTP/1.0 or1.1) or exactly chunked framing (HTTP/1.1 only).
Reject conflicting/duplicate framing,
unsupported transfer/content coding, malformed lengths/chunks, trailers, oversized
data and absent framing. A response completes at exactly its declared body length
or the complete final zero chunk and empty trailer terminator. A valid quiet JSON
record is a separate subsequent requirement. A reset/EOF/truncation before framed
completion always fails, including a partial final chunk terminator.

Preserve exact bounded wire bytes even on failure. Reject trailing bytes already
in the captured response or immediately queued on the same socket. Use an actual
nonblocking socket operation, not MSG_DONTWAIT alone with a positive Python
socket timeout. Do not wait for clean EOF after a proven frame, or claim absence
of bytes that might arrive later. Post-frame would-block/reset may end this check;
other errors, close/retain/lease/shutdown/deadline failures remain failures.
This policy proves message framing, not successful connection teardown or cleanup.

After transport completion, retain the unchanged image inspection, image-profile
verification, fresh isolated probe/removal, rendering, publication and durable
terminal/CLI checks. No response or old image alone qualifies a release.

RFC9112 sections6.3,7.1,8 govern framing/completion. Exact Ubuntu Built-Using and
the retained Engine metadata both identify Go1.24.4. Its source emits chunked
framing for this flushed HTTP/1.1 response and the final empty trailer terminator
after the handler returns. The Ubuntu delta has only two runtime-test skips;
net/http server.go and transfer.go match the official1.24.4 tag byte-for-byte.
Retain the independently checked primary-source hashes and limits; this is no
signature-verification or reproducible-binary-build claim.

## Historical compatibility

Freeze the existing exact HTTP/1.0 request reconstruction and response-witness
parser in a pure historical module. It has no socket, dispatch or write authority.
Both old positive history and the negative codec currently import these functions
from the current builder; remove that coupling before changing current encoding.

Positive history may recognize only the exact source-derived compiled legacy or
new request format, and must use that request generation's response validator.
Keep all existing complete positive chain, namespace, hashes, fingerprints,
clock, durability and ownership checks. A legacy response witness is not a new
successful exchange; historical terminal facts remain indispensable.

Negative reconciliation recognizes exactly two compiled cohorts:479/a54 and
bac/8294. Each binds original commit, complete Git tree, archive digest, seven
causal module hashes and a distinct source profile ID. Derive selection from
parsed original evidence, never caller/environment registration or a supplied
profile. The observer checks the selected immutable checkout before and after
observation. Keep the pinned Ubuntu daemon/binary/socket/process/boot/capacity
profile and all original-file/durability/lease requirements.

Old479 schema1 canonical facts must remain byte-identical. Both old wire
witnesses stay HTTP/1.0 forever. Neither failed source can produce or return a
release, claim cleanup, replay or become successful retroactively. The new8294
negative closure requires a separate actual owned public invocation after its
implementation/tests/review; development never writes those facts manually.

## Verification and native boundaries

Observe RED before fixes. Cover fragmented valid CL/chunked replies with a peer
that stays open; post-frame reset; reset/EOF at every framing boundary; malformed,
duplicate, conflicting, missing, oversized and trailing data; invalid quiet
records; original deadlines, shutdown, close/retain failures and one-send ownership.
Use offline fixtures and controlled local mocks, never a duplicate native build.

Test old positive and negative wire compatibility independently of the new
encoder, cross-cohort mixtures, unchanged old facts, mixed histories and permanent
same-source denial. Run the current-stock regression/static/critical-coverage
gates and independent integrated review. Any source change resets exact-head
verification. Existing CI11990passes do not qualify this future change.

Only after that may a new immutable source implement one actual8294 negative
closure and a different fresh producer operation through every normal stage.
Keep all previous failures/receipts, unrelated work/services, controls, OAuth and
live-disabled state. No namespace resets, private-stage dispatch, broker calls,
credential reads/refreshes, orders or paid infrastructure follow from this work.
