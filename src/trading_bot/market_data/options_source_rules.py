"""Code-owned source policy. No provider's historical semantic roles are approved yet."""

import hashlib
from pathlib import Path

from trading_bot.domain import DataHash
from trading_bot.market_data.options_source_models import SourceEvidenceError, SourceRule
from trading_bot.market_data.recording import content_hash


def load_reviewed_rules() -> tuple[SourceRule, ...]:
    """Missing reviewed source-era evidence is a real-data blocker, not inferred approval."""
    return ()


def reviewed_rulebook_hash() -> DataHash:
    return content_hash(load_reviewed_rules())


def source_code_hash() -> DataHash:
    """Whole installed Python boundary; no transitive consumer helper is omitted.

    Unrelated Python changes also invalidate earlier verification contexts. This
    conservative identity is not a deployment signature or trust certificate.
    """
    try:
        root = Path(__file__).resolve().parents[1]
        return content_hash(
            {
                "schema": "options-source-code-v2",
                "files": tuple(
                    (str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest())
                    for path in sorted(root.rglob("*.py"))
                ),
            }
        )
    except Exception:
        raise SourceEvidenceError() from None
