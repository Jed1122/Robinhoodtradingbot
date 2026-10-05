"""Native synthetic receipts exercise immutable private intake, not trading."""

import hashlib
import importlib
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from tests.unit.market_data.test_etf_native_archive import (
    loaded as loaded,
)
from tests.unit.market_data.test_etf_native_archive import (
    manifest as manifest,
)
from tests.unit.market_data.test_etf_native_archive import (
    quote_body,
    quote_row,
    retain,
)
from trading_bot.market_data.alpaca_native import AlpacaStockRequest, parse_timestamp_ns
from trading_bot.market_data.etf_quote_catalog_models import QuoteCaptureLocation

ROOT = Path(__file__).parents[3]
START = parse_timestamp_ns("2016-01-04T14:30:00Z")
STAMP = START + 123456789


def api():
    try:
        return importlib.import_module("trading_bot.market_data.etf_quote_catalog")
    except ModuleNotFoundError:
        pytest.fail("bounded private native quote catalog is missing")


@pytest.fixture
def captures(tmp_path, manifest):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    locations, raw_paths = [], []
    cases = (
        (
            "first",
            "2016-01-04T14:30:00Z",
            "2016-01-04T14:31:00Z",
            "2016-01-04T14:30:00.123456789Z",
            2,
        ),
        ("second", "2016-01-04T14:31:00Z", "2016-01-04T14:32:00Z", "2016-01-04T14:31:01Z", 1),
        ("future", "2016-01-05T14:30:00Z", "2016-01-05T14:31:00Z", "2016-01-05T14:30:01Z", 1),
    )
    for name, start, end, stamp, count in cases:
        capture = replace(
            manifest,
            quarantine_root=root / name,
            request=AlpacaStockRequest(
                "quotes", parse_timestamp_ns(start), parse_timestamp_ns(end)
            ),
        )
        raw = quote_body([quote_row(stamp)] * count).replace(b"200.125", b"200.123456789123456789")
        digest, _ = retain(capture, [raw])
        locations.append(QuoteCaptureLocation(name, digest))
        raw_paths.append(root / name / (hashlib.sha256(raw).hexdigest() + ".raw"))
    return root, tuple(locations), tuple(raw_paths)


def publish(captures, loaded):
    root, locations, _ = captures
    m = api()
    first = m.publish_quote_day(root, locations[:2], repository_root=ROOT)
    later = m.publish_quote_day(root, locations[2:], repository_root=ROOT)
    digest = m.publish_quote_catalog(
        root,
        (first.index_hash, later.index_hash),
        loaded=loaded,
        code_revision="a" * 40,
        repository_root=ROOT,
    )
    return digest


def quotes(captures, digest, start=START, end=START + 2 * 86400 * 10**9):
    return api().iter_catalog_quotes(
        captures[0], digest, start_ns=start, end_ns=end, repository_root=ROOT
    )


def test_exact_native_ties_and_multiple_captures_are_preserved(captures, loaded):
    digest = publish(captures, loaded)
    rows = list(quotes(captures, digest))
    assert len(rows) == 4
    assert [row.record.row_index for row in rows] == [0, 1, 0, 0]
    assert [row.location.relative_path for row in rows] == ["first", "first", "second", "future"]
    assert rows[0].record.bid == Decimal("200.123456789123456789")
    assert rows[0].record.timestamp_ns == STAMP
    assert rows[0].record.conditions == ("R", "Y")
    assert rows[0].record.bid_size == 3
    assert rows[0].record.publication_at_ns is None
    assert rows[0].record.executable is False
    assert rows[0].record.record_hash != rows[1].record.record_hash
    assert len(list(quotes(captures, digest, STAMP, STAMP + 1))) == 2
    assert list(quotes(captures, digest, START + 1, STAMP)) == []
    catalog = api().read_quote_catalog(captures[0], digest, repository_root=ROOT)
    assert [ref.observation_count for ref in catalog.days] == [3, 1]
    assert not catalog.source_qualified and not catalog.cost_qualified


def test_late_selected_corruption_denies_before_first_occurrence(captures, loaded):
    digest = publish(captures, loaded)
    captures[2][1].write_bytes(b"corrupt")
    with pytest.raises(ValueError, match=r"^etf_quote_catalog_invalid$"):
        next(quotes(captures, digest))


def test_future_raw_is_unread_and_cannot_change_selected_prefix(captures, loaded):
    m = api()
    first = m.publish_quote_day(captures[0], captures[1][:2], repository_root=ROOT)
    old = m.publish_quote_catalog(
        captures[0],
        (first.index_hash,),
        loaded=loaded,
        code_revision="a" * 40,
        repository_root=ROOT,
    )
    expected = list(quotes(captures, old, START, START + 120_000_000_000))
    complete = publish(captures, loaded)
    captures[2][2].unlink()
    assert list(quotes(captures, complete, START, START + 120_000_000_000)) == expected
    assert complete != old


def test_mid_iteration_mutation_is_incomplete_not_silent_exhaustion(captures, loaded):
    digest = publish(captures, loaded)
    iterator = quotes(captures, digest)
    assert next(iterator).record.row_index == 0
    captures[2][1].unlink()
    assert next(iterator).record.row_index == 1
    with pytest.raises(ValueError, match=r"^etf_quote_catalog_invalid$"):
        next(iterator)


@pytest.mark.parametrize("target", ["raw", "result", "manifest", "receipt", "day", "catalog"])
@pytest.mark.parametrize("violation", ["hardlink", "symlink", "mode"])
def test_unsafe_selected_files_deny(captures, loaded, target, violation):
    digest = publish(captures, loaded)
    root, locations, raws = captures
    if target == "raw":
        path = raws[0]
    elif target in ("day", "catalog"):
        path = next(
            root.glob(
                "etf-native-quote-" + ("days" if target == "day" else "catalogs") + "-v1/*.json"
            )
        )
    else:
        path = next((root / locations[0].relative_path).glob("*.capture-" + target + ".json"))
    if violation == "hardlink":
        os.link(path, path.with_suffix(".linked"))
    elif violation == "symlink":
        moved = path.with_suffix(".moved")
        path.rename(moved)
        path.symlink_to(moved)
    else:
        path.chmod(0o644)
    with pytest.raises(ValueError, match=r"^etf_quote_catalog_invalid$"):
        next(quotes(captures, digest))


def test_idempotent_publication_does_not_replace_or_repair(captures, loaded):
    digest = publish(captures, loaded)
    path = captures[0] / "etf-native-quote-catalogs-v1" / (digest + ".json")
    inode, original = path.stat().st_ino, path.read_bytes()
    assert publish(captures, loaded) == digest
    assert path.stat().st_ino == inode and path.read_bytes() == original
    path.write_bytes(b"invalid")
    with pytest.raises(ValueError):
        publish(captures, loaded)
    assert path.read_bytes() == b"invalid"


@pytest.mark.parametrize("violation", ["mode", "symlink", "git"])
def test_private_root_denies_unsafe_roots(captures, loaded, violation):
    root = captures[0]
    if violation == "mode":
        root.chmod(0o755)
    elif violation == "symlink":
        alias = root.parent / "alias"
        alias.symlink_to(root)
        captures = (alias, *captures[1:])
    else:
        (root.parent / ".git").write_text("gitdir: somewhere")
    with pytest.raises(ValueError, match=r"^etf_quote_catalog_invalid$"):
        publish(captures, loaded)


def test_canonical_config_and_backtest_boundary_deny_before_publication(captures, loaded):
    digest = publish(captures, loaded)
    ref = api().read_quote_catalog(captures[0], digest, repository_root=ROOT).days[0]
    for bad in (
        replace(loaded, config_hash="f" * 64),
        replace(loaded, config=loaded.config.model_copy(update={"live_trading_enabled": True})),
    ):
        with pytest.raises(ValueError, match=r"^etf_quote_catalog_invalid$"):
            api().publish_quote_catalog(
                captures[0],
                (ref.index_hash,),
                loaded=bad,
                code_revision="a" * 40,
                repository_root=ROOT,
            )


def test_invalid_windows_and_absent_index_deny(captures, loaded):
    digest = publish(captures, loaded)
    for start, end in ((START, START), (True, START), (START, -1)):
        with pytest.raises(ValueError):
            next(quotes(captures, digest, start, end))
    with pytest.raises(ValueError):
        api().read_quote_catalog(captures[0], "f" * 64, repository_root=ROOT)


def test_offline_capture_intake_never_opens_credentials_or_network(captures, loaded, monkeypatch):
    import httpx

    from trading_bot.diagnostics import alpaca_capture

    def forbidden(*args, **kwargs):
        pytest.fail("offline catalog attempted credentials or network")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(alpaca_capture, "capture_native", forbidden)
    digest = publish(captures, loaded)
    assert len(list(quotes(captures, digest))) == 4
