# Dashboard snapshot refresh

After a successful manual connection, the dashboard requests the existing
authenticated `GET /api/hybrid/snapshot` every 30 seconds while the document is
visible. Typing a token or failing the initial connection does not start polling.
Hidden ticks are skipped; returning to the tab may wait until the next scheduled
tick. The browser may delay timers, so 30 seconds is the requested cadence rather
than a real-time delivery guarantee.

Background refresh uses the existing snapshot request helper, in-memory token,
15-second request timeout, busy guard and response validation. A pending request
prevents overlapping work. There is no immediate catch-up request or retry loop;
after a transient failure, another request may run on the next visible tick.

Successful refreshes update the displayed snapshot and retrieval time. Transient
failures preserve the last verified snapshot, display the error and disable
controls. A background retry keeps that error visible until a successful response.
Existing source-age checks still apply. Background refresh preserves manual action
notices and never supplies a control action or POST request.

HTTP 401/403 clears the connected snapshot and token and stops polling. Disconnect
also clears the session. Unmount removes the interval; generation invalidation
prevents late in-flight responses from restoring session state after disconnect or
unmount. Tokens remain in component memory and are never written to localStorage
or sessionStorage.

This change refreshes already published dashboard evidence. It does not connect
automatically, collect broker data, run or resume research, alter risk/source
settings, activate a kill switch or enable live trading. Existing manual controls
retain their separate explicit actions.

## Verification

The missing-behavior RED test observed one request after connection when the
30-second boundary should have produced a second. Product code was then added.
Fake-clock/fetch tests render the actual React component and verify the cadence,
authenticated GET-only requests, no preconnection/hidden polling, overlap avoidance,
401/403 shutdown, bounded transient retries, notice preservation and disconnect/
unmount cleanup. All existing dashboard tests remain included.

Actual commands in the isolated dashboard directory:

```sh
npm test -- --reporter=dot
npm run build
```

Both passed: 67 tests across two files, then TypeScript checking and Vite production
build. Existing sibling dependencies were reused through a temporary local symlink;
no install or upgrade occurred. The symlink is removed before returning the commit.
No backend suite, external provider request, real credential, deployment or browser
visual QA was part of this narrow timer change.

Next, root independently reviews and integrates the exact commit and verifies it
with the current dashboard/backend consumer. A successful frontend refresh does
not prove continuous collector operation or qualify an investment strategy.

## Root integration and rendered check

Root reviewed every changed file and integrated candidate5504be75 as
`35a07439c36dd4b5a5ec3b2a09a71f1d05e7e62d`. Independent local reruns passed all67
dashboard tests and the TypeScript/Vite production build. No backend source changed;
the separately verified filing backend remains source0914482.

The rendered flow was manual connection -> Research -> automatic GET -> updated
fictional stock score -> disconnect -> reconnect -> authorization denial stops
polling. Existing Playwright/Chromium checked the built app at
`http://127.0.0.1:5191/` at1440x1000 and390x844. Browser plugin was unavailable;
the already installed Playwright runtime was used without installing dependencies.
This test used fictional API responses and a virtual browser clock, not a timed
production trial or a broker connection.

| Check | Result |
| --- | --- |
| Intended URL/title and meaningful content | Passed both viewports |
| Framework error overlay | None |
| Relevant console errors/warnings | None; expected fixture401 was checked separately |
|30-second GET updates rendered score | Passed |
| No preconnection requests; disconnect and401 stop polling | Passed |
| Automatic control requests | Zero |
| Browser credential storage | Empty local/session storage |
| Layout width and screenshots | No document overflow; both viewports inspected |

Temporary screenshots and QA script remain outside Git. The preview server stopped
and the temporary dependency link was removed. The first QA attempt correctly
displayed a stale snapshot because its fixture timestamp did not advance with the
virtual clock; correcting the fixture timestamp produced the passing checks without
changing product code. Hidden-tab/overlap/unmount/403/transient retry behavior was
covered by the component tests; no production collector, deployed runtime or real
provider authentication was exercised by this rendered check.
