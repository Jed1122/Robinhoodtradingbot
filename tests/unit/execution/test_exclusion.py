"""Unit tests for fail-fast in-process submission exclusion."""

import pytest

from trading_bot.domain import AccountId, DomainValidationError
from trading_bot.execution.exclusion import (
    InProcessSubmissionExclusion,
    SubmissionAlreadyInProgress,
)


@pytest.mark.asyncio
async def test_same_account_overlap_is_rejected_without_waiting() -> None:
    exclusion = InProcessSubmissionExclusion()
    account_id = AccountId("paper-account")

    async with exclusion.acquire(account_id):
        with pytest.raises(SubmissionAlreadyInProgress):
            async with exclusion.acquire(account_id):
                pytest.fail("overlapping account exclusion must never be acquired")


@pytest.mark.asyncio
async def test_different_accounts_can_be_held_independently() -> None:
    exclusion = InProcessSubmissionExclusion()

    async with (
        exclusion.acquire(AccountId("paper-account-1")),
        exclusion.acquire(AccountId("paper-account-2")),
    ):
        pass


@pytest.mark.asyncio
async def test_account_is_released_after_body_exception() -> None:
    exclusion = InProcessSubmissionExclusion()
    account_id = AccountId("paper-account")

    with pytest.raises(RuntimeError, match="test failure"):
        async with exclusion.acquire(account_id):
            raise RuntimeError("test failure")

    async with exclusion.acquire(account_id):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("account_id", ["", 1, None])
async def test_invalid_account_id_is_rejected(account_id: object) -> None:
    exclusion = InProcessSubmissionExclusion()

    with pytest.raises(DomainValidationError, match="account_id"):
        async with exclusion.acquire(account_id):  # type: ignore[arg-type]
            pytest.fail("invalid account id must never acquire exclusion")


def test_submission_overlap_error_is_generic_and_slotted() -> None:
    error = SubmissionAlreadyInProgress()

    assert error.args == ("submission already in progress",)
    assert SubmissionAlreadyInProgress.__slots__ == ()
    assert vars(error) == {}
