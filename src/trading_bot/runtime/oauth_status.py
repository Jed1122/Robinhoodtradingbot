"""Owner-only offline lifecycle status; no provider, token or client identity output."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_bot.brokers.robinhood_mcp_sdk import EncryptedFileTokenStorage
from trading_bot.brokers.robinhood_oauth_lifecycle import PrivateOAuthStoreLease
from trading_bot.clock import require_utc


async def read_oauth_status(oauth_store: Path, *, now: datetime) -> dict[str, object]:
    """Inspect only a private encrypted record under the same exclusive SDK lease.

    Active describes saved protocol state, not current provider validity. This
    function never refreshes, signs in, sends traffic or changes the record.
    """
    try:
        at = require_utc(now)
        with PrivateOAuthStoreLease(oauth_store):
            record = await EncryptedFileTokenStorage(oauth_store).get_lifecycle()
            if record is None or at < record.last_observed_at:
                raise ValueError
            return {
                "version": 1,
                "state": record.state,
                "flow": record.flow,
                "generation": record.generation,
                "expires_at": None if record.expires_at is None else record.expires_at.isoformat(),
                "last_observed_at": record.last_observed_at.isoformat(),
                "expired": None if record.expires_at is None else at >= record.expires_at,
                "natural_expiry_not_before": None
                if record.response_received_at is None or record.expires_in is None
                else (
                    record.response_received_at + timedelta(seconds=record.expires_in)
                ).isoformat(),
            }
    except Exception:
        raise ValueError("oauth_status_unavailable") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oauth-store", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(read_oauth_status(args.oauth_store, now=datetime.now(UTC)))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('{"status":"oauth_status_unavailable"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
