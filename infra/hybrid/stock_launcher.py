"""One bounded stock research invocation; installation is a separate gate.

The held operations namespace admits at most one new lifecycle per invocation.
Uncertain CREATE/CID state is retained, never retried. A persisted uncertain START
is supervised under its original fence. Termination is not research success.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from infra.hybrid.stock_attempts import AttemptStore, operations
from infra.hybrid.stock_container import verify_engine_version, verify_image
from infra.hybrid.stock_engine import StockEngineReader
from infra.hybrid.stock_engine_mutation import _ERRORS, StockEngineMutator, _production_store
from infra.hybrid.stock_engine_retirement import StockEngineRetirer
from infra.hybrid.stock_prestart import verify_created
from infra.hybrid.stock_release import load_release
from infra.hybrid.stock_supervisor import StockSupervisionResult, _shutdown, supervise_active


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


@dataclass(frozen=True, slots=True, repr=False)
class StockCycleResult:
    status: str
    supervision: StockSupervisionResult | None


def _recover(
    store: AttemptStore, reader: StockEngineReader, shutdown: list[bool]
) -> StockCycleResult:
    target = store.recovery_snapshot()
    if target is None:
        return StockCycleResult("recovery_only", None)
    supervision = None
    if target.stopped_sha256 is not None:
        if target.container_id is None:
            _deny()
        store.record_stopped(reader.inspect(target.container_id))
    elif target.abandoned_sha256 is not None:
        pass
    elif target.attempt.schema_version == 2 and target.create_sha256 is None:
        if target.attempt.retirement_attempt_id is not None and target.removed_sha256 is None:
            StockEngineRetirer().retire_predecessor(store)
        store.record_abandoned_before_dispatch()
    elif target.start_fence is not None:
        supervision = supervise_active(store, shutdown=shutdown)
    else:
        raw = (
            reader.inspect(target.container_id)
            if target.container_id is not None
            else reader.inspect_attempt(target.attempt.attempt_id)
        )
        store.record_stopped(raw)
    return StockCycleResult("recovery_only", supervision)


def run_research_cycle(store: AttemptStore, release_path: Path) -> StockCycleResult:
    """A fresh cycle or one recovery, never both and never an automatic retry."""
    try:
        _production_store(store)
        with _shutdown() as shutdown:
            target = store.snapshot()
            reader = StockEngineReader()
            if (
                shutdown[0]
                or store._namespace["schema_version"] != 2
                or (
                    target is not None
                    and target.stopped_sha256 is None
                    and target.abandoned_sha256 is None
                )
            ):
                return _recover(store, reader, shutdown)
            release = load_release(release_path)
            engine = verify_engine_version(reader.version())
            if shutdown[0]:
                return _recover(store, reader, shutdown)
            image = verify_image(reader.image(release.image_digest), release.image_digest, engine)
            if shutdown[0]:
                return _recover(store, reader, shutdown)
            if target is not None:
                if target.stopped_sha256 is not None:
                    if target.container_id is None:
                        _deny()
                    store.record_stopped(reader.inspect(target.container_id))
                else:
                    store.acknowledge_abandoned_terminal()
            if shutdown[0]:
                return _recover(store, reader, shutdown)
            attempt = store.begin(release)
            if attempt.retirement_attempt_id is not None:
                StockEngineRetirer().retire_predecessor(store)
            if shutdown[0]:
                return _recover(store, reader, shutdown)
            mutator = StockEngineMutator()
            container_id = mutator.create_worker(store, release, image, shutdown=shutdown)
            if shutdown[0]:
                return _recover(store, reader, shutdown)
            verified = verify_created(
                reader.inspect(container_id),
                release=release,
                image=image,
                attempt_id=attempt.attempt_id,
                container_id=container_id,
            )
            store.record_created(verified)
            if shutdown[0]:
                return _recover(store, reader, shutdown)
            try:
                mutator.start_worker(store, shutdown=shutdown)
            except _ERRORS:
                if shutdown[0]:
                    return _recover(store, reader, shutdown)
                current = store.snapshot()
                if (
                    current is None
                    or current.attempt != attempt
                    or current.container_id != container_id
                    or current.created_sha256 is None
                    or current.start_sha256 is None
                    or current.start_fence is None
                    or current.stopped_sha256 is not None
                ):
                    _deny()
            return StockCycleResult("completed", supervise_active(store, shutdown=shutdown))
    except _ERRORS:
        _deny()


def main() -> int:
    """Fixed operations/transport roots; the only argument is a release manifest file."""
    try:
        if len(sys.argv) != 2:
            _deny()
        with operations() as store:
            result = run_research_cycle(store, Path(sys.argv[1]))
        print(json.dumps({"status": result.status}, sort_keys=True))
        return 0
    except _ERRORS:
        print('{"status": "unavailable"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
