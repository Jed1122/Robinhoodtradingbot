"""Private storage fixtures preserve original supplied bytes, not authenticity."""

import hashlib
import json
import stat
from datetime import UTC, datetime

import pytest

from tests.unit.market_data.test_alpaca_capital_native import body, request
from trading_bot.market_data.etf_capital_archive import (
    read_capital_daily_archive,
    write_capital_daily_archive,
)


@pytest.fixture
def roots(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    return repository, private


def write(roots, bodies=None):
    repository, private = roots
    raw = bodies or (body(),)
    return write_capital_daily_archive(
        private,
        repository_root=repository,
        request=request(),
        bodies=raw,
        received_at=tuple(datetime(2026, 10, 8, tzinfo=UTC) for _ in raw),
    )


def test_original_bytes_roundtrip_and_private_modes(roots):
    repository, private = roots
    digest = write(roots)
    original = private / (hashlib.sha256(body()).hexdigest() + ".capital-daily-body")
    assert original.read_bytes() == body()
    assert stat.S_IMODE(original.stat().st_mode) == 0o600
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    value = read_capital_daily_archive(private, digest, repository_root=repository)
    assert value.request == request()
    assert value.pages[0].records[0].symbol == "QQQ"
    assert value.source_qualified is value.evidence_promotable is False
    assert value.manifest_hash == digest
    assert len(value.archive_hash) == 64


def test_exact_retry_never_replaces_originals(roots):
    _, private = roots
    first = write(roots)
    before = {path.name: path.read_bytes() for path in private.iterdir()}
    assert write(roots) == first
    assert before == {path.name: path.read_bytes() for path in private.iterdir()}


@pytest.mark.parametrize("target", ["raw", "manifest"])
def test_changed_raw_bytes_and_manifest_are_denied(roots, target):
    repository, private = roots
    digest = write(roots)
    path = (
        private / (hashlib.sha256(body()).hexdigest() + ".capital-daily-body")
        if target == "raw"
        else private / (digest + ".capital-daily-manifest.json")
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="capital_daily_archive_invalid"):
        read_capital_daily_archive(private, digest, repository_root=repository)


def test_invalid_input_publishes_nothing(roots):
    _, private = roots
    with pytest.raises(ValueError):
        write(roots, bodies=(body(), body()))
    assert list(private.iterdir()) == []


def test_nonprivate_or_checkout_root_is_denied(roots):
    repository, private = roots
    private.chmod(0o755)
    with pytest.raises(ValueError):
        write(roots)
    with pytest.raises(ValueError):
        write_capital_daily_archive(
            repository,
            repository_root=repository,
            request=request(),
            bodies=(body(),),
            received_at=(datetime(2026, 10, 8, tzinfo=UTC),),
        )


def test_missing_receipt_or_naive_clock_is_denied_before_publication(roots):
    repository, private = roots
    for clocks in ((), (datetime(2026, 10, 8),)):
        with pytest.raises(ValueError):
            write_capital_daily_archive(
                private,
                repository_root=repository,
                request=request(),
                bodies=(body(),),
                received_at=clocks,
            )
    assert list(private.iterdir()) == []


def test_source_qualification_cannot_be_laundered_through_a_new_hash(roots):
    repository, private = roots
    digest = write(roots)
    original = private / (digest + ".capital-daily-manifest.json")
    document = json.loads(original.read_bytes())
    document["source_qualified"] = True
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    forged = hashlib.sha256(encoded).hexdigest()
    path = private / (forged + ".capital-daily-manifest.json")
    path.write_bytes(encoded)
    path.chmod(0o600)
    with pytest.raises(ValueError, match="capital_daily_archive_invalid"):
        read_capital_daily_archive(private, forged, repository_root=repository)


def test_raw_artifact_symlink_is_not_followed(roots):
    repository, private = roots
    digest = write(roots)
    original = private / (hashlib.sha256(body()).hexdigest() + ".capital-daily-body")
    target = private / "fixture-copy"
    target.write_bytes(original.read_bytes())
    target.chmod(0o600)
    original.unlink()
    original.symlink_to(target)
    with pytest.raises(ValueError, match="capital_daily_archive_invalid"):
        read_capital_daily_archive(private, digest, repository_root=repository)


def test_incomplete_capture_is_retained_without_claiming_coverage(roots):
    from trading_bot.market_data.alpaca_capital_native import assess_capital_daily_pages

    repository, private = roots
    digest = write(roots, bodies=(body(token="pending"),))
    value = read_capital_daily_archive(private, digest, repository_root=repository)
    assert assess_capital_daily_pages(value.pages).pagination_complete is False
    assert value.source_qualified is value.evidence_promotable is False
