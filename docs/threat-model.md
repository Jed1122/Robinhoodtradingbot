# Threat model

Protected assets include credentials, OAuth state, signing keys, account identities, the ledger,
and execution authority. Controls include file-only secrets, redaction, non-root/read-only
containers, loopback administration, lease fencing, one-attempt writes, and fail-closed schema
gates. Single-host flock is not a distributed mutex.
