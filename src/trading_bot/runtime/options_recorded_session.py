"""Restartable, explicitly stepped synthetic replay backed by the existing trial journal.

This is NOT a broker runtime or streaming-data processor. The caller must retain the
immutable v1 input document; its full-script hash binds every checkpoint. Cash and orders
are reconstructed from that document plus the durable event count, never trusted from a
mutable snapshot. Every returned checkpoint is paused. No automatic next event, network,
account discovery, migration or file creation occurs here.
"""

from dataclasses import dataclass, field, replace
from typing import Literal

from trading_bot.domain import AccountId
from trading_bot.domain.decimal_utils import DomainValidationError
from trading_bot.market_data.recording import content_hash
from trading_bot.persistence.lease import ExecutionLease
from trading_bot.persistence.options_trial import OptionsTrialJournal, TrialJournalEvent
from trading_bot.risk.options_economics import TrialLossState
from trading_bot.simulation.options_replay import replay_options
from trading_bot.simulation.options_replay_models import OptionsReplayRequest, OptionsReplayResult
from trading_bot.simulation.options_replay_wire import encode_options_replay


@dataclass(frozen=True, slots=True)
class RecordedOptionsProgress:
    event_count: int
    result: OptionsReplayResult
    journal_head: str = "0" * 64
    paused: Literal[True] = field(default=True, init=False)


def _checkpoint(request: OptionsReplayRequest, count: int) -> RecordedOptionsProgress:
    return RecordedOptionsProgress(count, replay_options(request, event_count=count))


def _event(
    request: OptionsReplayRequest, progress: RecordedOptionsProgress, account_id: AccountId
) -> TrialJournalEvent:
    result, count = progress.result, progress.event_count
    if result.entry_intent_hash is None:
        raise DomainValidationError("recorded replay entry denied")
    episode = result.trial.episodes[-1]
    # Journal genesis is a reservation before any simulated acceptance, not a completed
    # zero-P&L episode. Subsequent records carry the reconstructed exact net cash flow.
    if count == 0:
        episode = replace(episode, net_cash_flow=None)
    identity = content_hash({"account_id": account_id, "input_hash": result.input_hash})
    return TrialJournalEvent(
        f"options-replay-{identity}-{count}",
        request.as_of if count == 0 else request.events[count - 1].at,
        result.config_hash,
        episode,
    )


def _state(
    request: OptionsReplayRequest, progress: RecordedOptionsProgress, account_id: AccountId
) -> TrialLossState:
    return TrialLossState((*request.trial.episodes, _event(request, progress, account_id).episode))


class RecordedOptionsSession:
    """One event per explicit operator step; account-wide compare-and-append is atomic.

    Other writers changing trial history cause a stop, not automatic merging/rebasing.
    The journal's existing lease, fencing and hash-chain rules remain authoritative.
    """

    def __init__(self, journal: OptionsTrialJournal) -> None:
        if type(journal) is not OptionsTrialJournal:
            raise DomainValidationError("exact options trial journal required")
        self._journal = journal

    async def restore(
        self, account_id: AccountId, request: OptionsReplayRequest
    ) -> RecordedOptionsProgress | None:
        # Round-trip through the existing strict codec to enforce canonical config,
        # byte/depth/record bounds and synthetic provenance before any persistence use.
        encode_options_replay(request)
        initial = _checkpoint(request, 0)
        episode_id = "synthetic-episode-" + initial.result.input_hash
        snapshot = await self._journal.snapshot(account_id)
        events = snapshot.events
        own = tuple(event for event in events if event.episode.episode_id == episode_id)
        if not own:
            return None
        if len(own) > len(request.events) + 1:
            raise DomainValidationError("recorded replay checkpoint count exceeds input")
        progress = initial
        for count, event in enumerate(own):
            progress = _checkpoint(request, count)
            if event != _event(request, progress, account_id):
                raise DomainValidationError("recorded replay checkpoint does not match input")
        if snapshot.state != _state(request, progress, account_id):
            raise DomainValidationError("recorded replay trial history changed")
        return replace(progress, journal_head=snapshot.head_hash)

    async def start(
        self, lease: ExecutionLease, request: OptionsReplayRequest
    ) -> RecordedOptionsProgress:
        restored = await self.restore(lease.account_id, request)
        if restored is not None:
            # Exact retry is read-only and never starts another simulated submission.
            return restored
        # This first durable slice cannot infer cross-episode portfolio/session counts.
        # Never reset those counters by treating another script as a new trial account.
        if request.trial.episodes or await self._journal.events(lease.account_id):
            raise DomainValidationError("only one recorded script per isolated trial account")
        initial = _checkpoint(request, 0)
        receipt = await self._journal.append(
            lease,
            _event(request, initial, lease.account_id),
            expected_state=request.trial,
            expected_head=initial.journal_head,
        )
        return replace(initial, journal_head=receipt)

    async def advance(
        self,
        lease: ExecutionLease,
        request: OptionsReplayRequest,
        *,
        expected_event_count: int,
        resume_recorded_replay: bool = False,
    ) -> RecordedOptionsProgress:
        if resume_recorded_replay is not True:
            raise DomainValidationError("recorded replay is paused")
        progress = await self.restore(lease.account_id, request)
        if (
            progress is None
            or type(expected_event_count) is not int
            or progress.event_count != expected_event_count
            or expected_event_count >= len(request.events)
        ):
            raise DomainValidationError("recorded replay event count mismatch or exhausted")
        if progress.result.status == "completed_synthetic_replay":
            raise DomainValidationError("completed recorded replay cannot be reopened")
        following = _checkpoint(request, expected_event_count + 1)
        receipt = await self._journal.append(
            lease,
            _event(request, following, lease.account_id),
            expected_state=_state(request, progress, lease.account_id),
            expected_head=progress.journal_head,
        )
        return replace(following, journal_head=receipt)
