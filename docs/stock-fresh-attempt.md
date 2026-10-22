# First stock research attempt

This legacy first-attempt entry point remains bounded to empty state. The later
[repeatable lifecycle](stock-repeated-cycle-verification.md) adds a separate
coordinator and fixed-root CLI with shutdown handling before admission. Statements
below about absent repeated composition describe this legacy entry point.

`infra.hybrid.stock_launcher.launch_fresh_attempt(store, release_path)` connects
the existing trusted-release, Engine/image, durable attempt, prestart, START and
active-supervision components. It is a root-only library for the first attempt in
an already initialized, empty operations namespace. It has no CLI, service, timer,
credential input or automatic control-resume behavior.

The caller must hold the actual fixed `operations()` context throughout the call.
The entry point applies its fixed production guard and validates an empty snapshot
before release/daemon work. Caller release/image objects, raw observations, CIDs,
fences, callbacks, clocks or time limits cannot replace its internal dependencies.

The closed sequence is:

1. Load the retained root-controlled release using the actual release verifier.
2. Read and verify the fixed Engine version and exact local image.
3. Durably admit one attempt; create its worker exactly once.
4. Inspect the returned full CID and verify all prestart identity, command, state,
   mount, namespace and hardening fields using the original observation bytes.
5. Durably record that verified CID; dispatch START exactly once.
6. Run the existing active supervisor in the same still-open store context.

If START raises, the launcher validates the persisted chain. Only a matching
created/start-fenced attempt can proceed to supervision. The original owning-session
deadline remains unchanged; a lost reply never causes another START or fence.
No valid fence means denial. Successful START acknowledgement without durable
state also cannot bypass the supervisor's checked cleanup target.

Admission, CREATE, inspection and CID-persistence failures do not retry or infer
execution authority. Supervision or stopped-persistence failure cannot return a
successful lifecycle result. All covered errors use the fixed sanitized
`stock_launcher_unavailable`; receipt uncertainty remains available for a separate
recovery workflow. A returned `StockSupervisionResult` describes observed durable
termination, including nonzero exit codes; it does not assert successful research.

## Verified locally

Twenty-five missing-module cases were observed RED before implementation. The
launcher suite expanded to 28 cases; all 586 launcher/store/transport/prestart/
container/supervisor checks passed. The launcher has 100% combined statement and
branch coverage. Tests use actual temporary receipt stores, actual metadata
verifiers and actual supervision, substituting only fictional release/socket/clock
boundaries. They do not create a container, obtain a credential or call a provider.

## Remaining operational work

Every nonempty namespace is deliberately denied, including stopped, pending,
never-started and fenced attempts. This entry point does not resolve or adopt those
states, initialize a replacement namespace or remove anything. Repeated collection
needs a durable predecessor-cleanup/admission protocol. A crash after new admission
but before old-CID cleanup must be distinguishable from uncertain CREATE; an
in-memory predecessor reference alone is insufficient.

The full recovery workflow must separately handle generated-name/no-CID incidents,
created state after an uncertain START, typed absence and non-force/no-volume old-CID
removal. An opaque lookup error or signal acknowledgement never proves termination.
Host signals are handled only after entry into the existing supervisor; death before
that point leaves durable state for a separately installed recovery hook. Such a
hook and native physical deadline/reboot proof remain absent.

Trusted release production, actual immutable/executing image and CID compatibility,
paused installation, a disabled completion-relative timer, exclusive credential
lifecycle, encrypted backup/restore and actual scheduled collection remain unverified.
The earlier full baseline does not validate this new code; its eventual integrated
revision needs the full repository check. Source/strategy qualification and live
authorization remain independent, and live execution stays disabled.
