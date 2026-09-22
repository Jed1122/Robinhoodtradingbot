import hashlib

import pytest

from trading_bot.domain import AccountId
from trading_bot.execution import SubmissionAlreadyInProgress
from trading_bot.persistence.submission_mutex import AccountSubmissionMutex


@pytest.mark.asyncio
async def test_account_mutex_is_nonblocking_and_hides_account_id(tmp_path) -> None:
    tmp_path.chmod(0o700)
    mutex = AccountSubmissionMutex(tmp_path)
    account = AccountId("secret-account-reference")
    async with mutex.acquire(account):
        with pytest.raises(SubmissionAlreadyInProgress):
            async with mutex.acquire(account):
                pytest.fail("nested acquisition unexpectedly succeeded")
    names = [path.name for path in tmp_path.iterdir()]
    assert names == [f"{hashlib.sha256(account.encode()).hexdigest()}.lock"]
    assert "secret-account-reference" not in names[0]
    assert (tmp_path / names[0]).stat().st_mode & 0o777 == 0o600
