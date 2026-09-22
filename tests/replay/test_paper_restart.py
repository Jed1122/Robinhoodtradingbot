from pathlib import Path


def test_paper_restart_store_checks_cycle_before_running() -> None:
    source = (Path(__file__).parents[2] / "src/trading_bot/runtime/paper.py").read_text()
    assert source.index("await self._store.get(cycle_id)") < source.index(
        "await self._cycle_service.run_cycle(request)"
    )
