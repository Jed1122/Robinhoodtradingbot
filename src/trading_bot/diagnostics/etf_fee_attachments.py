"""Immutable later fee observations; original execution clock sessions never reopen.

This verifies local source linkage and arithmetic only. Documents and component
classification still require independent authentication and semantic review.
"""

import os
from pathlib import Path
from typing import cast

from trading_bot.clock import Clock, require_utc
from trading_bot.diagnostics.etf_execution_receipts import read_execution_receipts
from trading_bot.market_data.alpaca_native import parse_timestamp_ns
from trading_bot.market_data.bundle_codec import _array, _digest, _mapping, _string, _time
from trading_bot.market_data.bundle_store import _open_root, _publish, _read
from trading_bot.market_data.recording import canonical_json, content_hash
from trading_bot.research.etf_cost_calibration import measure_etf_cost_observations
from trading_bot.research.etf_execution_receipts import (
    MAX_BODY_BYTES,
    MAX_SOURCE_BYTES,
    EtfReceiptError,
    _check,
    _decode,
    _fees,
    source_digest,
)

_KEYS = {
    "schema",
    "checkpoint_hash",
    "clock_session_hash",
    "order_hash",
    "terminal_hash",
    "source_hash",
    "charged_fees",
    "observed_at",
    "evidence_promotable",
}
_ERRORS = (ValueError, TypeError, ArithmeticError, AttributeError, OSError, RuntimeError, KeyError)


def _read_source(descriptor: int, digest: str) -> bytes:
    _digest(digest)
    body = _read(descriptor, digest + ".source", MAX_BODY_BYTES)
    _check(source_digest(body) == digest)
    return body


def _terminal(
    descriptor: int,
    checkpoint_hash: str,
    order_hash: str,
) -> tuple[str, str]:
    """Caller first validates the complete checkpoint with the existing reader."""
    manifest = cast(dict[str, object], _decode(_read_source(descriptor, checkpoint_hash)))
    matches: list[tuple[str, str]] = []
    for digest in _array(manifest["receipt_hashes"]):
        row = cast(dict[str, object], _decode(_read_source(descriptor, str(_digest(digest)))))
        payload = cast(dict[str, object], row["payload"])
        if row["kind"] in ("terminal", "terminal_v2") and payload["order_hash"] == order_hash:
            matches.append((_string(digest), _string(row["received_at"])))
    _check(len(matches) == 1)
    return matches[0]


def _order(result: dict[str, object], order_hash: str) -> dict[str, object]:
    _digest(order_hash)
    cost = cast(dict[str, object], result["cost_input"])
    rows = _array(cost["orders"]) + _array(result["unfilled_outcomes"])
    matches = [
        cast(dict[str, object], item)
        for item in rows
        if cast(dict[str, object], item)["order_hash"] == order_hash
    ]
    _check(len(matches) == 1 and matches[0]["charged_fees"] is None)
    return matches[0]


def _binding(row: dict[str, object]) -> str:
    return (
        content_hash(
            (
                "etf-terminal-fee-binding-v1",
                row["clock_session_hash"],
                row["order_hash"],
                row["terminal_hash"],
            )
        )
        + ".fee-binding"
    )


def _binding_bytes(digest: str) -> bytes:
    return canonical_json(
        {"schema": "etf-terminal-fee-binding-v1", "attachment_hash": digest}
    ).encode()


def read_fee_attachment(
    root: Path,
    attachment_hash: str,
    repository_root: Path,
) -> dict[str, object]:
    """Revalidate the original receipts and the separately retained fee document."""
    descriptor = -1
    try:
        descriptor = _open_root(root, repository_root)
        row = _mapping(_decode(_read_source(descriptor, attachment_hash)), _KEYS)
        _check(row["schema"] == "etf-terminal-fee-attachment-v1")
        _check(row["evidence_promotable"] is False)
        for key in (
            "checkpoint_hash",
            "clock_session_hash",
            "order_hash",
            "terminal_hash",
            "source_hash",
        ):
            _digest(row[key])
        _time(row["observed_at"])
        fees = _fees(row["charged_fees"])
        _check(fees is not None and fees["source_hash"] == row["source_hash"])
        result = read_execution_receipts(root, _string(row["checkpoint_hash"]), repository_root)
        _check(result["clock_session_hash"] == row["clock_session_hash"])
        order = _order(result, _string(row["order_hash"]))
        terminal, received_at = _terminal(
            descriptor, _string(row["checkpoint_hash"]), _string(row["order_hash"])
        )
        _check(terminal == row["terminal_hash"])
        _check(parse_timestamp_ns(_string(row["observed_at"])) >= parse_timestamp_ns(received_at))
        source = _read_source(descriptor, _string(row["source_hash"]))
        _check(_read(descriptor, _binding(row), MAX_BODY_BYTES) == _binding_bytes(attachment_hash))
        references = cast(list[str], result["reference_hashes"])
        source_bytes = cast(int, result["retained_source_bytes"])
        if row["source_hash"] not in references:
            source_bytes += len(source)
            references.append(_string(row["source_hash"]))
        _check(source_bytes <= MAX_SOURCE_BYTES)
        order["charged_fees"] = fees
        cost = cast(dict[str, object], result["cost_input"])
        measure_etf_cost_observations(canonical_json(cost).encode())
        result["reference_hashes"] = sorted(references)
        result["retained_source_bytes"] = source_bytes
        result["missing_fee_order_count"] = sum(
            cast(dict[str, object], item)["charged_fees"] is None for item in _array(cost["orders"])
        )
        result["fee_attachment_hash"] = attachment_hash
        result["fee_observed_at"] = row["observed_at"]
        return result
    except _ERRORS:
        raise EtfReceiptError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def publish_fee_attachment(
    root: Path,
    checkpoint_hash: str,
    *,
    order_hash: str,
    charged_fees: dict[str, object],
    source: bytes,
    clock: Clock,
    repository_root: Path,
) -> str:
    """Bind explicit final component observations once; never infer fee finality.

    The first published binding is authoritative for this local attachment. Exact
    retries return it without resampling the original execution or fee receipt.
    Conflicting documents/amounts deny. An orphan content blob grants no result.
    """
    descriptor = -1
    try:
        _digest(checkpoint_hash)
        _digest(order_hash)
        source_hash = source_digest(source)
        components = _mapping(charged_fees, {"commission", "sec", "taf", "cat", "other", "total"})
        fees = _fees({**components, "source_hash": source_hash})
        result = read_execution_receipts(root, checkpoint_hash, repository_root)
        order = _order(result, order_hash)
        descriptor = _open_root(root, repository_root)
        terminal, received_at = _terminal(descriptor, checkpoint_hash, order_hash)
        references = cast(list[str], result["reference_hashes"])
        _check(
            cast(int, result["retained_source_bytes"])
            + (0 if source_hash in references else len(source))
            <= MAX_SOURCE_BYTES
        )
        row: dict[str, object] = {
            "schema": "etf-terminal-fee-attachment-v1",
            "checkpoint_hash": checkpoint_hash,
            "clock_session_hash": result["clock_session_hash"],
            "order_hash": order_hash,
            "terminal_hash": terminal,
            "source_hash": source_hash,
            "charged_fees": fees,
            "evidence_promotable": False,
        }
        binding = _binding(row)
        # Descriptor-relative stat distinguishes absent bindings from corrupt ones.
        try:
            os.stat(binding, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            existing = _mapping(
                _decode(_read(descriptor, binding, MAX_BODY_BYTES)), {"schema", "attachment_hash"}
            )
            digest = _string(_digest(existing["attachment_hash"]))
            read_fee_attachment(root, digest, repository_root)
            prior = _mapping(_decode(_read_source(descriptor, digest)), _KEYS)
            _check({k: v for k, v in prior.items() if k != "observed_at"} == row)
            # A prior hard-link may have succeeded just before directory fsync
            # failed. Re-publication verifies the exact binding and repairs its
            # durability without sampling a new fee or execution clock.
            _publish(descriptor, binding, _binding_bytes(digest))
            return digest
        now = require_utc(clock.now())
        observed_at = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
        _check(parse_timestamp_ns(observed_at) >= parse_timestamp_ns(received_at))
        row["observed_at"] = observed_at
        # Validate derived arithmetic before installing an authoritative binding.
        # A syntactically bounded fee can still overflow a report calculation.
        order["charged_fees"] = fees
        measure_etf_cost_observations(canonical_json(result["cost_input"]).encode())
        body = canonical_json(row).encode()
        digest = source_digest(body)
        _publish(descriptor, source_hash + ".source", source)
        _publish(descriptor, digest + ".source", body)
        _publish(descriptor, binding, _binding_bytes(digest))
        read_fee_attachment(root, digest, repository_root)
        return digest
    except _ERRORS:
        raise EtfReceiptError() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
