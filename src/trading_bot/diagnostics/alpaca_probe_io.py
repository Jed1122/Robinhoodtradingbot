"""Explicit private diagnostic files using the reviewed descriptor-relative primitives."""

import hashlib
import os
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import cast

from trading_bot.diagnostics.alpaca_probe import (
    MAX_RESPONSE_BYTES,
    ProbeCredential,
    ProbeError,
    ProbeReceipt,
    _canonical,
    _check,
    _json_object,
    _path,
)
from trading_bot.market_data.bundle_models import BundleError
from trading_bot.market_data.bundle_store import _open_root, _publish, _read


def _read_private_file(path: Path, *, repository_root: Path, max_bytes: int, code: str) -> bytes:
    _check(_path(path) and _path(repository_root), code)
    try:
        parent = _open_root(path.parent, repository_root)
        try:
            return _read(parent, path.name, max_bytes)
        finally:
            os.close(parent)
    except (BundleError, OSError):
        pass
    raise ProbeError(code)


def _publish_private_file(path: Path, body: bytes, *, repository_root: Path) -> None:
    _check(_path(path) and _path(repository_root), "probe_path_invalid")
    try:
        parent = _open_root(path.parent, repository_root)
        try:
            _publish(parent, path.name, body)
            return
        finally:
            os.close(parent)
    except (BundleError, OSError):
        pass
    raise ProbeError("probe_storage_failed")


def read_probe_credential(path: Path, *, repository_root: Path) -> ProbeCredential:
    """Read only the explicitly authorized private file; never discover credentials."""
    body = _read_private_file(
        path,
        repository_root=repository_root,
        max_bytes=4096,
        code="probe_credential_invalid",
    )
    value = _json_object(body, max_bytes=4096, code="probe_credential_invalid")
    _check(set(value) == {"key_id", "secret_key"}, "probe_credential_invalid")
    return ProbeCredential(cast(str, value["key_id"]), cast(str, value["secret_key"]))


def publish_probe_blob(root: Path, body: bytes, *, repository_root: Path) -> str:
    """Publish exact quarantined bytes; this performs no bundle/source acceptance."""
    _check(type(body) is bytes and 0 < len(body) <= MAX_RESPONSE_BYTES, "probe_response_too_large")
    digest = hashlib.sha256(body).hexdigest()
    _publish_private_file(root / (digest + ".raw"), body, repository_root=repository_root)
    return digest


def publish_probe_receipt(root: Path, receipt: ProbeReceipt, *, repository_root: Path) -> str:
    _check(type(receipt) is ProbeReceipt)
    receipt.__post_init__()
    payload: dict[str, object] = {}
    for item in fields(receipt):
        value = getattr(receipt, item.name)
        payload[item.name] = value.isoformat() if isinstance(value, datetime) else value
    body = _canonical(payload)
    digest = hashlib.sha256(body).hexdigest()
    _publish_private_file(root / (digest + ".receipt.json"), body, repository_root=repository_root)
    return digest
