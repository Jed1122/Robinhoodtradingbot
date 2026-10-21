"""One first-attempt lifecycle; not repeated-cycle or deployment composition.

The actual locked operations namespace must be empty. Uncertain CREATE/CID state
is retained, never retried. A persisted uncertain START is supervised under its
original fence. Stopped lifecycle evidence says nothing about research success.
"""

from pathlib import Path
from typing import NoReturn

from infra.hybrid.stock_attempts import AttemptStore
from infra.hybrid.stock_container import verify_engine_version, verify_image
from infra.hybrid.stock_engine import StockEngineReader
from infra.hybrid.stock_engine_mutation import _ERRORS, StockEngineMutator, _production_store
from infra.hybrid.stock_prestart import verify_created
from infra.hybrid.stock_release import load_release
from infra.hybrid.stock_supervisor import StockSupervisionResult, supervise_active


def _deny() -> NoReturn:
    raise ValueError("stock_launcher_unavailable") from None


def launch_fresh_attempt(store: AttemptStore, release_path: Path) -> StockSupervisionResult:
    """Launch once from a fresh initialized production store, with no state adoption."""
    try:
        _production_store(store)
        if store.snapshot() is not None:
            _deny()
        release = load_release(release_path)
        reader, mutator = StockEngineReader(), StockEngineMutator()
        engine = verify_engine_version(reader.version())
        image = verify_image(reader.image(release.image_digest), release.image_digest, engine)
        attempt = store.begin(release)
        container_id = mutator.create_worker(store, release, image)
        raw = reader.inspect(container_id)
        verified = verify_created(
            raw,
            release=release,
            image=image,
            attempt_id=attempt.attempt_id,
            container_id=container_id,
        )
        store.record_created(verified)
        try:
            mutator.start_worker(store)
        except _ERRORS:
            target = store.snapshot()
            if (
                target is None
                or target.attempt != attempt
                or target.container_id != container_id
                or target.created_sha256 is None
                or target.start_sha256 is None
                or target.start_fence is None
                or target.stopped_sha256 is not None
            ):
                _deny()
            # Never repeat START or prepare another fence after an ambiguous reply.
        return supervise_active(store)
    except _ERRORS:
        _deny()
