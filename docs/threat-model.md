# Threat model

Protected assets include credentials, OAuth state, signing keys, account identities, the ledger,
and execution authority. Controls include file-only secrets, redaction, non-root/read-only
containers, loopback administration, lease fencing, one-attempt writes, and fail-closed schema
gates. Single-host flock is not a distributed mutex.

The connected-shadow OAuth callback binds only `127.0.0.1:18765` and accepts one exact callback
path. The OAuth client requests and pins Robinhood's sole official `internal` scope. That scope is
not a broker-enforced read-only grant: the bearer credential must be treated as trading-capable, and
a stolen token or compromised host could trade in the Agentic account. The current client is
write-incapable only because both its SDK-session and provider-transport allowlists accept seven
reviewed reads and because it constructs no review, place, or cancel adapter.
For a reviewed zero-argument read, the declaration gate accepts an omitted `properties` member only
when the schema is an object with `additionalProperties: false`; an open or broader schema remains
incompatible.

Token and client records are authenticated-encrypted at rest; the encryption key, encrypted
records, and `account-fingerprint` file must be service-owned regular files with mode `0600` inside
the service-owned mode-`0700` OAuth directory. Bootstrap requires a private mode-`0700` parent and
an absent destination, stages the credential plus fingerprint together, and atomically commits the
directory. Ownership, type, permission, and symlink checks fail closed. Because the key travels with
the encrypted records, this protects accidental disclosure and at-rest copies, not a compromised
service account or host. Moving the OAuth store to a server is a credential-transfer boundary and
requires an independently reviewed procedure.

Promotion observations and decisions are append-only and content-hash-bound at the application and
SQLite-trigger boundaries. They are tamper-evident for ordinary application writes, not signed
proof against a database owner, root user, filesystem rollback, or host compromise. A compromised
host can also use refreshed OAuth material to trade; host hardening, least privilege, monitoring,
and independent backups remain required. The default paused Compose service reduces its credential
exposure by mounting no host volumes; only the explicit connected-shadow profile receives the OAuth
and evidence mounts.
