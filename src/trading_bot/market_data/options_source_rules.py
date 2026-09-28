"""Code-owned source policy. No provider's historical semantic roles are approved yet."""

import hashlib
from pathlib import Path

from trading_bot.domain import DataHash
from trading_bot.market_data.options_source_models import SourceEvidenceError, SourceRule
from trading_bot.market_data.recording import content_hash

_SOURCE_FILES = (
    "config/hashing.py",
    "config/loader.py",
    "config/models.py",
    "market_data/options_source_models.py",
    "market_data/options_source_wire.py",
    "market_data/options_source_rules.py",
    "market_data/options_source_verify.py",
    "market_data/databento_bar_models.py",
    "market_data/databento_bar_store.py",
    "market_data/databento_bar_wire.py",
    "market_data/bundle_store.py",
    "market_data/bundle_codec.py",
    "market_data/recording.py",
)


def load_reviewed_rules() -> tuple[SourceRule, ...]:
    """Missing reviewed source-era evidence is a real-data blocker, not inferred approval."""
    return ()


def reviewed_rulebook_hash() -> DataHash:
    return content_hash(load_reviewed_rules())


def source_code_hash() -> DataHash:
    """Fixed installed-source identity, not a deployment signature or trust certificate."""
    try:
        root = Path(__file__).resolve().parents[1]
        return content_hash(
            tuple(
                (name, hashlib.sha256((root / name).read_bytes()).hexdigest())
                for name in _SOURCE_FILES
            )
        )
    except Exception:
        raise SourceEvidenceError() from None
