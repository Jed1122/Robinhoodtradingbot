"""Closed maintenance dependency receipts and read-only local trust checks.

The caller captures facts with the target interpreter using only the standard
library, and independently supplies the frozen source and recipe identities.
The two verification flags record retained successful installer/check evidence;
this module neither performs nor proves those operations. A receipt is not a
signature, image attestation, binary measurement, or execution/liveness proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import NoReturn

_ERROR = "stock_maintenance_runtime_unavailable"
_PATH_TYPE = type(Path())
_RUNTIME_ROOT = Path("/opt/hybrid-stock-research/maintenance")
_SOURCE_ROOT = Path("/opt/hybrid-stock-research/source")
_INTERPRETER = Path("/usr/bin/python3.12")
_HELPER_GID = 10001
_MAX_RECEIPT_BYTES = 65536
_MAX_TREE_ENTRIES = 50000
_MAX_TREE_DEPTH = 32
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PYTHON_VERSION = re.compile(r"3\.12\.(?:0|[1-9][0-9]{0,5})\Z")
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}\Z")
_IDENTITIES = frozenset(
    {
        "source_commit",
        "source_archive_sha256",
        "uv_lock_sha256",
        "requirements_sha256",
        "config_hash",
    }
)
_FACT_FIELDS = _IDENTITIES | {
    "python_implementation",
    "python_version",
    "platform",
    "architecture",
    "include_system_site_packages",
    "sys_prefix",
    "site_packages",
    "distributions",
    "expected_distributions",
    "hashed_install_verified",
    "pip_check_verified",
}


def _deny() -> NoReturn:
    raise ValueError(_ERROR)


def _require(condition: bool) -> None:
    if not condition:
        _deny()


def _identity(value: object, *, commit: bool = False) -> str:
    _require(type(value) is str)
    if not isinstance(value, str):
        _deny()
    _require((_COMMIT if commit else _HASH).fullmatch(value) is not None)
    return value


def _inventory(value: object) -> list[dict[str, object]]:
    _require(type(value) is list)
    if not isinstance(value, list):
        _deny()
    _require(1 <= len(value) <= 256)
    packages: dict[str, dict[str, object]] = {}
    for entry in value:
        _require(type(entry) is dict)
        if not isinstance(entry, dict):
            _deny()
        _require(set(entry) == {"name", "version", "direct_url_present", "editable"})
        name, version = entry["name"], entry["version"]
        _require(type(name) is str and type(version) is str)
        if not isinstance(name, str) or not isinstance(version, str):
            _deny()
        _require(_NAME.fullmatch(name) is not None and _VERSION.fullmatch(version) is not None)
        _require(entry["direct_url_present"] is False and entry["editable"] is False)
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        _require(normalized not in packages)
        packages[normalized] = {
            "name": normalized,
            "version": version,
            "direct_url_present": False,
            "editable": False,
        }
    _require("pip" in packages)
    return [packages[name] for name in sorted(packages)]


def build_runtime_receipt(facts: dict[str, object]) -> bytes:
    """Validate supplied target facts and return bounded canonical receipt bytes.

    Inventories must describe exactly the production export plus its pinned pip,
    with no direct/editable installs. Names are normalized and sorted without
    modifying caller facts. No filesystem access or interpreter execution occurs.
    """
    _require(type(facts) is dict and set(facts) == _FACT_FIELDS)
    clean: dict[str, object] = {}
    for key in _IDENTITIES:
        clean[key] = _identity(facts[key], commit=key == "source_commit")
    for key, fixed in (
        ("python_implementation", "cpython"),
        ("platform", "linux"),
        ("architecture", "x86_64"),
    ):
        _require(type(facts[key]) is str and facts[key] == fixed)
    version = facts["python_version"]
    _require(type(version) is str)
    if not isinstance(version, str):
        _deny()
    _require(_PYTHON_VERSION.fullmatch(version) is not None)
    _require(facts["include_system_site_packages"] is False)
    _require(facts["hashed_install_verified"] is True and facts["pip_check_verified"] is True)
    prefix = str(_RUNTIME_ROOT / str(clean["source_commit"]))
    _require(type(facts["sys_prefix"]) is str and facts["sys_prefix"] == prefix)
    _require(
        type(facts["site_packages"]) is str
        and facts["site_packages"] == prefix + "/lib/python3.12/site-packages"
    )
    actual = _inventory(facts["distributions"])
    expected = _inventory(facts["expected_distributions"])
    _require(actual == expected)
    clean.update({key: facts[key] for key in _FACT_FIELDS - _IDENTITIES})
    clean.update(
        {
            "distributions": actual,
            "expected_distributions": expected,
            "schema_version": 1,
            "kind": "stock_maintenance_runtime",
        }
    )
    body = (json.dumps(clean, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    _require(len(body) <= _MAX_RECEIPT_BYTES)
    return body


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _trusted(
    info: os.stat_result, uid: int, *, directory: bool = False, helper_readable: bool = True
) -> None:
    _require(info.st_uid == uid and info.st_mode & 0o022 == 0)
    _require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    # The helper has UID/GID10001 and no supplementary groups. Root ownership
    # alone cannot establish access: require deterministic other permissions.
    if directory:
        required = _helper_bits(info, 0o005)
        _require(info.st_mode & required == required)
    elif helper_readable:
        required = _helper_bits(info, 0o004)
        _require(info.st_mode & required == required)


def _helper_bits(info: os.stat_result, bits: int) -> int:
    # A matching primary group selects group permissions before other bits.
    return bits | (bits << 3 if info.st_gid == _HELPER_GID else 0)


def _path(
    path: Path,
    anchor: Path,
    uid: int,
    *,
    directory: bool = False,
    helper_readable: bool = True,
) -> os.stat_result:
    _require(type(path) is _PATH_TYPE and type(anchor) is _PATH_TYPE)
    _require(path.is_absolute() and anchor.is_absolute() and ".." not in path.parts)
    relative = path.relative_to(anchor)
    current = anchor
    info = current.lstat()
    _trusted(info, uid, directory=True)
    for index, part in enumerate(relative.parts):
        current = current / part
        info = current.lstat()
        _trusted(
            info,
            uid,
            directory=directory or index < len(relative.parts) - 1,
            helper_readable=helper_readable,
        )
    return info


def _read(
    path: Path,
    anchor: Path,
    uid: int,
    limit: int,
    *,
    receipt: bool = False,
    helper_readable: bool = True,
) -> bytes:
    before = _path(path, anchor, uid, helper_readable=helper_readable and not receipt)
    _require(0 < before.st_size <= limit)
    if receipt:
        _require(stat.S_IMODE(before.st_mode) == 0o400 and before.st_nlink == 1)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        _require(_fingerprint(os.fstat(descriptor)) == _fingerprint(before))
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        _require(len(data) == before.st_size and len(data) <= limit)
        _require(_fingerprint(os.fstat(descriptor)) == _fingerprint(before))
        _require(_fingerprint(path.lstat()) == _fingerprint(before))
        return bytes(data)
    finally:
        os.close(descriptor)


def _venv_configuration(body: bytes, version: object) -> None:
    fields: dict[str, str] = {}
    for line in body.decode("utf-8").splitlines():
        _require(" = " in line)
        key, value = line.split(" = ", 1)
        _require(
            key not in fields
            and key
            in {
                "home",
                "include-system-site-packages",
                "version",
                "executable",
                "command",
                "prompt",
            }
        )
        _require(bool(value) and "\x00" not in value)
        fields[key] = value
    _require(fields.keys() >= {"home", "include-system-site-packages", "version", "executable"})
    _require(
        fields["home"] == "/usr/bin"
        and fields["include-system-site-packages"] == "false"
        and fields["version"] == version
        and fields["executable"] == str(_INTERPRETER)
    )


def _python_link(path: Path, runtime: Path, target: Path, uid: int, anchor: Path) -> None:
    current = path
    seen: set[Path] = set()
    aliases = {runtime / "bin" / name for name in ("python", "python3", "python3.12")}
    while current != target:
        _require(current in aliases and current not in seen)
        seen.add(current)
        info = current.lstat()
        _require(stat.S_ISLNK(info.st_mode) and info.st_uid == uid)
        link = os.readlink(current)
        _require(_fingerprint(current.lstat()) == _fingerprint(info))
        if link in {"python", "python3", "python3.12"}:
            current = runtime / "bin" / link
        else:
            _require(link == str(target))
            current = target
    info = _path(target, anchor, uid)
    executable = _helper_bits(info, 0o001)
    _require(info.st_mode & executable == executable)


def _tree(root: Path, anchor: Path, uid: int, *, interpreter: Path | None = None) -> None:
    count = 0
    pending = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        _require(depth <= _MAX_TREE_DEPTH)
        before = _path(directory, anchor, uid, directory=True)
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                _require(count <= _MAX_TREE_ENTRIES)
                path = directory / entry.name
                info = entry.stat(follow_symlinks=False)
                _require(info.st_uid == uid)
                if stat.S_ISLNK(info.st_mode):
                    _require(interpreter is not None)
                    if path == root / "lib64":
                        _require(os.readlink(path) == "lib")
                        _path(root / "lib", anchor, uid, directory=True)
                    else:
                        if interpreter is None:
                            _deny()
                        _python_link(path, root, interpreter, uid, anchor)
                elif stat.S_ISDIR(info.st_mode):
                    _trusted(info, uid, directory=True)
                    pending.append((path, depth + 1))
                else:
                    # These root-only retained installer facts are not imported
                    # or read by the helper. All executable source/dependencies
                    # and pyvenv.cfg remain readable to its reduced identity.
                    metadata = interpreter is not None and path in {
                        root / "runtime-receipt.json",
                        root / "requirements.txt",
                    }
                    _trusted(info, uid, helper_readable=not metadata)
        _require(_fingerprint(directory.lstat()) == _fingerprint(before))


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def verify_runtime_receipt(
    path: Path,
    *,
    source_commit: str,
    source_archive_sha256: str,
    uv_lock_sha256: str,
    requirements_sha256: str,
    config_hash: str,
    actual_facts: dict[str, object],
) -> dict[str, object]:
    """Read and validate the fixed production receipt without invoking its runtime.

    Target facts must be freshly captured independently with a trusted standard
    library bootstrap. Expected archive/config hashes come from the verified
    release producer; source metadata trust is checked here, not archive contents.
    """
    return _verify_runtime_receipt(
        path,
        source_commit=source_commit,
        source_archive_sha256=source_archive_sha256,
        uv_lock_sha256=uv_lock_sha256,
        requirements_sha256=requirements_sha256,
        config_hash=config_hash,
        actual_facts=actual_facts,
        trusted_uid=0,
        runtime_root=_RUNTIME_ROOT,
        source_root=_SOURCE_ROOT,
        interpreter_target=_INTERPRETER,
        trusted_anchor=Path("/"),
    )


def _verify_runtime_receipt(
    path: Path,
    *,
    source_commit: str,
    source_archive_sha256: str,
    uv_lock_sha256: str,
    requirements_sha256: str,
    config_hash: str,
    actual_facts: dict[str, object],
    trusted_uid: int,
    runtime_root: Path,
    source_root: Path,
    interpreter_target: Path,
    trusted_anchor: Path,
) -> dict[str, object]:
    """Private filesystem seam for fictional metadata fixtures; never executes code."""
    try:
        expected = {
            "source_commit": _identity(source_commit, commit=True),
            "source_archive_sha256": _identity(source_archive_sha256),
            "uv_lock_sha256": _identity(uv_lock_sha256),
            "requirements_sha256": _identity(requirements_sha256),
            "config_hash": _identity(config_hash),
        }
        _require(type(trusted_uid) is int and trusted_uid >= 0)
        _require(
            all(
                type(item) is _PATH_TYPE
                for item in (
                    path,
                    runtime_root,
                    source_root,
                    interpreter_target,
                    trusted_anchor,
                )
            )
        )
        runtime, checkout = runtime_root / source_commit, source_root / source_commit
        _require(path == runtime / "runtime-receipt.json")
        before_runtime = _path(runtime, trusted_anchor, trusted_uid, directory=True)
        before_source = _path(checkout, trusted_anchor, trusted_uid, directory=True)
        body = _read(path, trusted_anchor, trusted_uid, _MAX_RECEIPT_BYTES, receipt=True)
        value = json.loads(
            body.decode("ascii"), object_pairs_hook=_object, parse_constant=lambda _: _deny()
        )
        _require(type(value) is dict and set(value) == _FACT_FIELDS | {"schema_version", "kind"})
        _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
        _require(value["kind"] == "stock_maintenance_runtime")
        facts = {key: value[key] for key in _FACT_FIELDS}
        _require(build_runtime_receipt(facts) == body)
        _require(all(value[key] == identity for key, identity in expected.items()))
        _require(build_runtime_receipt(actual_facts) == body)
        _require(
            hashlib.sha256(
                _read(checkout / "uv.lock", trusted_anchor, trusted_uid, 2097152)
            ).hexdigest()
            == uv_lock_sha256
        )
        _require(
            hashlib.sha256(
                _read(
                    runtime / "requirements.txt",
                    trusted_anchor,
                    trusted_uid,
                    524288,
                    helper_readable=False,
                )
            ).hexdigest()
            == requirements_sha256
        )
        _venv_configuration(
            _read(runtime / "pyvenv.cfg", trusted_anchor, trusted_uid, 8192),
            value["python_version"],
        )
        _path(runtime / "lib/python3.12/site-packages", trusted_anchor, trusted_uid, directory=True)
        for name in ("python", "python3", "python3.12"):
            _python_link(
                runtime / "bin" / name, runtime, interpreter_target, trusted_uid, trusted_anchor
            )
        _tree(runtime, trusted_anchor, trusted_uid, interpreter=interpreter_target)
        _tree(checkout, trusted_anchor, trusted_uid)
        _require(_fingerprint(runtime.lstat()) == _fingerprint(before_runtime))
        _require(_fingerprint(checkout.lstat()) == _fingerprint(before_source))
        _require(_read(path, trusted_anchor, trusted_uid, _MAX_RECEIPT_BYTES, receipt=True) == body)
        return dict(value)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise ValueError(_ERROR) from None
