# Inert controller: whole-branch review and root disposition

One fresh independent review covered `0af7687..5be9681`. The reviewer independently
ran 322 controller/transport/observer checks, all passing. Its verdict was **with
fixes**, with no Critical finding, one Important finding and one Minor finding.
Root retained the Important grading: a successful result could escape its original
publication deadline or continuous-clock gate during final context cleanup.

Root reproduced 28 composed failures before changing source: store/handler context
exit with deadline expiry/equality, monotonic rollback, UTC rollback, boot change or
invalid time, plus CLI serialization delays/clock changes. A private completion
context now retains the actual session and original removal-fence identity through
result preparation. It checks the original window and shared shutdown state after
all context exits and, for the CLI, after serialization. It neither reads closed
descriptors nor rewrites receipts, renews a deadline or retries cleanup. All 28 new
cases then passed with the other 52 controller cases.

The corrected source passed 1,167 focused checks in31.10seconds at96.67% combined
controller/transport statement/branch coverage, and 2,951 deployment/architecture
checks in50.38seconds with four optional local-age checks skipped. Ruff, strict mypy
over460 source files, expanded stock-module Bandit, lock and diff checks passed.
Bandit emitted existing comment/suppression warnings; the separate12 inherited Low
host-script findings remain unchanged. The corrected revision's actual full suite
is still required. No second review substitutes for that run.

## Exclusions retained as separate gates

Root considered every item the reviewer declined to judge:

1. Actual Engine/API framing and logs: requires the intended daemon, not fictional
   socket evidence; wrong assumptions could reject or misread native responses.
2. Isolation/resource/network/credential enforcement: requires native inspection;
   parser acceptance alone could conceal an unsafe deployment.
3. Physical termination and daemon scheduling: caps govern application checks;
   kernel work may outlive them, leaving an incident requiring operator review.
4. Crash durability and intended-host filesystem headroom: local fault injection
   does not prove hardware persistence or native deadline capacity.
5. Source/image provenance and trusted producer: immutable image acceptance does
   not establish its origin; no release is qualified by this increment.
6. Arbitrary malicious root code or independent Docker mutations: root remains a
   trusted principal; these private interfaces are not an adversarial root sandbox.
7. Repair/pruning/force removal: deliberately unsupported; incidents or capacity
   exhaustion fail closed until a separately reviewed operator procedure exists.
8. Broader production-worker behavior: unchanged Engine files receive regression
   coverage but are not newly qualified end to end by this review.
9. Inherited12 Low preparation/watchdog findings: retained for producer/deployment
   review; excluding them must not be presented as a clean all-infrastructure scan.
10. Full-suite compatibility: requires a terminal result at the corrected revision;
    another revision's passing suite cannot establish this result.
11. Provider semantics/private capture hashes/entitlements: public documentation and
    local tests grant no dataset or strategy qualification.
12. Installation, OAuth lifecycle, backups/restore, scheduled research, strategies,
    broker reconciliation and live investing: independently unverified gates;
    treating these checks as deployment approval could enable unqualified operation.

## Deferred minor

Initial specification/store-header/checkpoint prose still describes superseded
implementation states. The latest checkpoint and this disposition identify the
current evidence; historical prose cleanup remains deferred. No financial, native
host, deployment or live authorization follows from this code review.
