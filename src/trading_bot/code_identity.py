"""Deterministic, fail-closed source and deployment code identity."""

import hashlib
import json
import os
import re
import stat
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trading_bot.domain.decimal_utils import _require_sha256_hex
from trading_bot.domain.identifiers import CodeHash

_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_RELEASE_KEY = re.compile(r"[0-9a-f]{64}-[0-9a-f]{64}-[0-9a-f]{64}\Z")
_RELEVANT_UNTRACKED_PREFIXES = (b"src/", b"configs/", b"migrations/", b"scripts/")
_NON_SOURCE_PATH_PARTS = {
    b".mypy_cache",
    b".pytest_cache",
    b".ruff_cache",
    b"__pycache__",
}


class CodeIdentityError(RuntimeError):
    """Raised when a complete deterministic code identity cannot be resolved."""


class InvalidImageDigest(CodeIdentityError):
    """Raised when a configured OCI image digest is not immutable SHA-256."""


class UnsafeCodeIdentity(CodeIdentityError):
    """Raised when code identity cannot support live execution or promotion."""


@dataclass(frozen=True, slots=True)
class DeployedImageAttestation:
    """Root-controlled binding between a release and one immutable image ID."""

    image_digest: str
    deployment_config_hash: str
    compose_sha256: str
    release_key: str

    def __post_init__(self) -> None:
        _validate_image_digest(self.image_digest)
        _require_sha256_hex(self.deployment_config_hash, "deployment_config_hash")
        _require_sha256_hex(self.compose_sha256, "compose_sha256")
        if _RELEASE_KEY.fullmatch(self.release_key) is None:
            raise CodeIdentityError("release_key is invalid")
        expected_release_key = (
            f"{self.image_digest.removeprefix('sha256:')}-"
            f"{self.deployment_config_hash}-{self.compose_sha256}"
        )
        if self.release_key != expected_release_key:
            raise CodeIdentityError("release_key does not match deployment identity")

    @property
    def code_hash(self) -> CodeHash:
        return deployed_image_code_hash(self.image_digest)


@dataclass(frozen=True, slots=True)
class CodeIdentity:
    code_hash: CodeHash
    git_commit: str | None
    dirty: bool
    image_digest: str | None
    non_promotable: bool

    def __post_init__(self) -> None:
        _require_sha256_hex(self.code_hash, "code_hash")
        if self.git_commit is not None and _GIT_COMMIT.fullmatch(self.git_commit) is None:
            raise CodeIdentityError("git_commit must be a full lowercase Git object ID")
        _validate_image_digest(self.image_digest)


def deployed_image_code_hash(image_digest: str) -> CodeHash:
    """Return the canonical promotion identity for one immutable OCI image."""

    _validate_image_digest(image_digest)
    return CodeHash(hashlib.sha256(f"oci-image:{image_digest}".encode()).hexdigest())


def verify_deployed_image_attestation(
    path: str | Path,
    *,
    expected_image_digest: str,
) -> DeployedImageAttestation:
    """Verify a canonical artifact produced outside the unprivileged container."""

    return _verify_deployed_image_attestation(
        path,
        expected_image_digest=expected_image_digest,
        trusted_owner_uid=0,
    )


def _verify_deployed_image_attestation(
    path: str | Path,
    *,
    expected_image_digest: str,
    trusted_owner_uid: int,
) -> DeployedImageAttestation:
    """Filesystem verifier with an injectable owner only for unprivileged tests."""

    _validate_image_digest(expected_image_digest)
    if type(trusted_owner_uid) is not int or trusted_owner_uid < 0:
        raise CodeIdentityError("trusted_owner_uid must be a nonnegative integer")
    source = Path(path)
    if not source.is_absolute():
        raise CodeIdentityError("deployment attestation path must be absolute")
    try:
        parent_metadata = source.parent.lstat()
    except OSError as exc:
        raise CodeIdentityError("deployment attestation is unavailable") from exc
    if not stat.S_ISDIR(parent_metadata.st_mode) or parent_metadata.st_uid != trusted_owner_uid:
        raise CodeIdentityError("deployment attestation parent is not trusted")
    if parent_metadata.st_mode & 0o022:
        raise CodeIdentityError("deployment attestation parent permissions are unsafe")
    descriptor = -1
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != trusted_owner_uid:
            raise CodeIdentityError(
                "deployment attestation must be a trusted-owner regular file"
            )
        if metadata.st_mode & 0o222 or metadata.st_size <= 0 or metadata.st_size > 2048:
            raise CodeIdentityError("deployment attestation file metadata is unsafe")
        with os.fdopen(descriptor, encoding="ascii") as stream:
            descriptor = -1
            raw = stream.read(2049)
        document: object = json.loads(raw)
    except CodeIdentityError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise CodeIdentityError("deployment attestation cannot be decoded") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    required_keys = {
        "compose_sha256",
        "deployment_config_hash",
        "image_digest",
        "release_key",
        "schema_version",
    }
    if type(document) is not dict or set(document) != required_keys:
        raise CodeIdentityError("deployment attestation schema is invalid")
    if type(document.get("schema_version")) is not int or document.get("schema_version") != 1:
        raise CodeIdentityError("deployment attestation schema version is unsupported")
    try:
        attestation = DeployedImageAttestation(
            image_digest=document["image_digest"],
            deployment_config_hash=document["deployment_config_hash"],
            compose_sha256=document["compose_sha256"],
            release_key=document["release_key"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CodeIdentityError("deployment attestation values are invalid") from exc
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    if raw != canonical:
        raise CodeIdentityError("deployment attestation is not canonical")
    if attestation.image_digest != expected_image_digest:
        raise CodeIdentityError("deployment attestation image does not match runtime image")
    return attestation


class _HashWriter(Protocol):
    def update(self, data: bytes, /) -> object:
        """Add bytes to the running digest."""
        ...


def resolve_code_identity(
    repo_root: str | Path,
    image_digest: str | None,
) -> CodeIdentity:
    """Hash the current tracked tree plus relevant untracked runtime content."""
    _validate_image_digest(image_digest)
    root = _resolve_repo_root(repo_root)
    tracked_paths = _nul_paths(_run_git(root, "ls-files", "--cached", "-z"))
    relevant_untracked = tuple(
        path
        for path in _nul_paths(_run_git(root, "ls-files", "--others", "-z"))
        if _is_relevant_untracked(path)
    )

    digest = hashlib.sha256()
    for relative_path in tracked_paths:
        marker, content = _read_worktree_content(root, relative_path)
        _write_record(digest, marker, relative_path, content)
    for relative_path in relevant_untracked:
        marker, content = _read_worktree_content(root, relative_path)
        if marker != b"PRESENT":
            raise CodeIdentityError("relevant untracked content changed during identity resolution")
        _write_record(digest, b"UNTRACKED", relative_path, content)

    tracked_dirty = bool(
        _run_git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=no",
            "--ignore-submodules=none",
        )
    )
    head = _try_resolve_head(root)
    dirty = tracked_dirty or bool(relevant_untracked) or head is None
    return CodeIdentity(
        code_hash=CodeHash(digest.hexdigest()),
        git_commit=None if dirty else head,
        dirty=dirty,
        image_digest=image_digest,
        non_promotable=dirty,
    )


def require_clean_live_identity(identity: CodeIdentity) -> None:
    """Reject any identity that cannot be tied to clean, promotable source."""
    if not isinstance(identity, CodeIdentity):
        raise UnsafeCodeIdentity("live execution requires a resolved CodeIdentity")
    if identity.dirty:
        raise UnsafeCodeIdentity("dirty source cannot supply live code identity")
    if identity.non_promotable:
        raise UnsafeCodeIdentity("non-promotable source cannot supply live code identity")
    if identity.git_commit is None:
        raise UnsafeCodeIdentity("live code identity requires a clean Git commit")


def _validate_image_digest(image_digest: str | None) -> None:
    if image_digest is not None and _IMAGE_DIGEST.fullmatch(image_digest) is None:
        raise InvalidImageDigest("image_digest must be sha256 followed by 64 lowercase hex digits")


def _resolve_repo_root(repo_root: str | Path) -> Path:
    try:
        root = Path(repo_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CodeIdentityError("repository root must be an existing directory") from exc
    if not root.is_dir():
        raise CodeIdentityError("repository root must be an existing directory")
    raw_top_level = _run_git(root, "rev-parse", "--show-toplevel")
    if raw_top_level.endswith(b"\n"):
        raw_top_level = raw_top_level[:-1]
    try:
        top_level = Path(os.fsdecode(raw_top_level)).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CodeIdentityError("Git top-level directory cannot be resolved") from exc
    if top_level != root:
        raise CodeIdentityError("repo_root must be the Git top-level directory")
    return root


def _run_git(root: Path, *arguments: str) -> bytes:
    try:
        # The executable and arguments are module-owned literals; root is used only as cwd.
        result = subprocess.run(  # nosec B603
            ("git", *arguments),
            cwd=root,
            check=False,
            capture_output=True,
            shell=False,
        )
    except OSError as exc:
        raise CodeIdentityError("Git is unavailable for code identity resolution") from exc
    if result.returncode != 0:
        raise CodeIdentityError("Git could not resolve the requested code identity metadata")
    return result.stdout


def _try_resolve_head(root: Path) -> str | None:
    try:
        raw_head = _run_git(root, "rev-parse", "--verify", "HEAD")
    except CodeIdentityError:
        return None
    head = raw_head.decode("ascii").strip()
    if _GIT_COMMIT.fullmatch(head) is None:
        raise CodeIdentityError("Git HEAD is not a full supported object ID")
    return head


def _nul_paths(raw_paths: bytes) -> tuple[bytes, ...]:
    return tuple(sorted(path for path in raw_paths.split(b"\0") if path))


def _is_relevant_untracked(relative_path: bytes) -> bool:
    if not relative_path.startswith(_RELEVANT_UNTRACKED_PREFIXES):
        return False
    path_parts = relative_path.split(b"/")
    if any(part in _NON_SOURCE_PATH_PARTS for part in path_parts):
        return False
    return path_parts[-1] != b".DS_Store" and not relative_path.endswith((b".pyc", b".pyo"))


def _read_worktree_content(root: Path, relative_path: bytes) -> tuple[bytes, bytes]:
    path = root / os.fsdecode(relative_path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return b"MISSING", b""
    except OSError as exc:
        raise CodeIdentityError("worktree content cannot be inspected") from exc

    if stat.S_ISLNK(metadata.st_mode):
        try:
            return b"SYMLINK", os.fsencode(os.readlink(path))
        except OSError as exc:
            raise CodeIdentityError("worktree symlink cannot be inspected") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise CodeIdentityError("tracked and relevant untracked paths must be regular files")
    try:
        return b"PRESENT", path.read_bytes()
    except OSError as exc:
        raise CodeIdentityError("worktree content cannot be read") from exc


def _write_record(
    digest: _HashWriter,
    marker: bytes,
    relative_path: bytes,
    content: bytes,
) -> None:
    for part in (marker, relative_path, content):
        digest.update(len(part).to_bytes(8, byteorder="big", signed=False))
        digest.update(part)
