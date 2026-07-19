# Operations runbook

Use `make status`, loopback `/healthz`, `/readyz`, and `/metrics` for observation. Deploy immutable
images with `make deploy`; deployment always uses `--paused`. Use `make backup` and
`make restore-test`. Review reconciliation, alerts, clock synchronization, disk, heartbeat, and
lease expiry before any resume. Tax exports are records, not tax advice.
