"""Account-scoped submission exclusion for single-process simulation."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from trading_bot.domain import AccountId, DomainValidationError


class SubmissionAlreadyInProgress(RuntimeError):
    """Indicate that an account already owns the local submission slot."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("submission already in progress")


class SubmissionExclusion(Protocol):
    """Acquire a non-waiting account-scoped submission critical section."""

    def acquire(
        self,
        account_id: AccountId,
    ) -> AbstractAsyncContextManager[None]: ...


class InProcessSubmissionExclusion:
    """Event-loop-local exclusion for fake brokers; never a live-host mutex."""

    __slots__ = ("_active_accounts",)

    def __init__(self) -> None:
        self._active_accounts: set[AccountId] = set()

    @asynccontextmanager
    async def acquire(self, account_id: AccountId) -> AsyncIterator[None]:
        if type(account_id) is not str or not account_id.strip():
            raise DomainValidationError("account_id must be a nonempty exact string")
        if account_id in self._active_accounts:
            raise SubmissionAlreadyInProgress() from None
        self._active_accounts.add(account_id)
        try:
            yield
        finally:
            self._active_accounts.remove(account_id)


__all__ = [
    "InProcessSubmissionExclusion",
    "SubmissionAlreadyInProgress",
    "SubmissionExclusion",
]
