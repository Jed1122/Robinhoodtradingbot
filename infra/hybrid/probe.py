"""Bounded loopback startup checks; does not read tokens or journal contents."""

import json
import urllib.error
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path: str) -> tuple[int, bytes]:
    try:
        with opener.open("http://127.0.0.1:8081" + path, timeout=3) as response:
            return response.status, response.read(4096)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


status, raw = request("/healthz")
health = json.loads(raw)
if status != 200 or health.get("healthy") is not True or health.get("live_enabled") is not False:
    raise SystemExit("Hybrid health/live-disabled verification failed")
if request("/readyz")[0] != 503:
    raise SystemExit("Hybrid readiness must deny live operation")
if request("/api/hybrid/snapshot")[0] != 401:
    raise SystemExit("Hybrid API must deny unauthenticated access")
print("Loopback health, live-disabled, readiness denial and API authentication denial passed.")
