"""Offline runner safety using fictional files only."""

import gzip
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.runtime.stock_price_study import (
    compress_study_document,
    publish_study_document,
    run_bound_stock_price_study,
)


def test_streamed_document_retains_exact_canonical_values_and_hash():
    from trading_bot.market_data.recording import canonical_json

    @dataclass(frozen=True)
    class Fixture:
        nav: Decimal
        stamp: datetime

    value = {"fictional": Fixture(Decimal("1.2300"), datetime(2024, 1, 2, tzinfo=UTC))}
    compressed, digest, size = compress_study_document(value)
    native = gzip.decompress(compressed)
    assert native == canonical_json(value).encode()
    assert hashlib.sha256(native).hexdigest() == digest
    assert len(native) == size


def test_study_document_publication_is_private_hashed_and_never_overwrites(tmp_path):
    root = tmp_path / "study"
    root.mkdir(mode=0o700)
    raw = b'{"kind":"fictional","live_enabled":false}\n'
    name = publish_study_document(root, raw, suffix=".study.json")
    path = root / name
    assert name == hashlib.sha256(raw).hexdigest() + ".study.json"
    assert path.read_bytes() == raw
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        publish_study_document(root, raw, suffix=".study.json")
    assert path.read_bytes() == raw


def test_failed_publication_leaves_no_partial_final_file(tmp_path, monkeypatch):
    import trading_bot.runtime.stock_price_study as runner

    root = tmp_path / "study"
    root.mkdir(mode=0o700)

    def fail_fsync(_descriptor):
        raise OSError("fictional failed durable write")

    monkeypatch.setattr(runner.os, "fsync", fail_fsync)
    with pytest.raises(ValueError):
        publish_study_document(root, b'{"fictional":true}', suffix=".study.json")
    assert not list(root.iterdir())


@pytest.mark.parametrize("kind", ["public", "existing_result"])
def test_output_preflight_fails_before_reading_missing_sources(tmp_path, kind):
    from trading_bot.research.stock_price_study import PROTOCOL_HASH

    root = tmp_path / "study"
    root.mkdir(mode=0o700)
    if kind == "public":
        root.chmod(0o755)
    else:
        (root / "existing.summary.json").write_text("fictional")
    with pytest.raises(ValueError, match="publication"):
        run_bound_stock_price_study(
            evidence_directory=tmp_path / "absent-inputs",
            manifest_path=tmp_path / "absent.json",
            expected_manifest_sha256="07c8d3084ec7b199c8bc30944835b6b24aaf9110555a44c4b84a234cdb9dbae3",
            expected_protocol_sha256=PROTOCOL_HASH,
            output_directory=root,
        )


@pytest.mark.parametrize("kind", ["symlink", "public", "suffix", "oversize"])
def test_publication_rejects_unreviewable_destinations(tmp_path, kind):
    root = tmp_path / "study"
    root.mkdir(mode=0o700)
    suffix, raw = ".study.json", b"{}"
    if kind == "symlink":
        link = tmp_path / "link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    elif kind == "public":
        root.chmod(0o755)
    elif kind == "suffix":
        suffix = "/../escape"
    else:
        raw = b"x" * (64 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        publish_study_document(root, raw, suffix=suffix)
    assert not list(root.iterdir())


def test_unknown_protocol_rejected_before_source_reads_and_no_output(tmp_path):
    root = tmp_path / "study"
    root.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="protocol"):
        run_bound_stock_price_study(
            evidence_directory=tmp_path / "absent-inputs",
            manifest_path=tmp_path / "absent.json",
            expected_manifest_sha256="0" * 64,
            expected_protocol_sha256="0" * 64,
            output_directory=root,
        )
    assert not list(root.iterdir())
