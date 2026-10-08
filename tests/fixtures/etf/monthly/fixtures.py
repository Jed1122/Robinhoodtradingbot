"""Stable fabricated issuer identities; ZIP creation times are not test inputs."""

from dataclasses import replace

from tests.unit.research.test_etf_benchmark_screen import inputs
from trading_bot.market_data.etf_issuer_distributions import _archive_hash
from trading_bot.market_data.recording import content_hash
from trading_bot.simulation.etf_history import _policy


def legacy_package():
    package = inputs()
    issuer = package.issuer
    source_hash = content_hash("fabricated monthly issuer source v1")
    rows = tuple(
        replace(
            row,
            row_hash=content_hash(
                (
                    "fabricated monthly issuer row v1",
                    row.ex_date,
                    row.record_date,
                    row.pay_date,
                    row.amount,
                )
            ),
        )
        for row in issuer.distributions
    )
    issuer = replace(
        issuer,
        source_hash=source_hash,
        distributions=rows,
        archive_hash=_archive_hash(
            source_hash,
            issuer.start_date,
            issuer.end_date,
            rows,
            issuer.excluded_spy_rows,
            issuer.limitations,
        ),
    )
    from trading_bot.research.etf_benchmark_screen import etf_benchmark_screen_plan_hash

    study = replace(
        package.study,
        policy=_policy(package.study),
        source_plan_hash=etf_benchmark_screen_plan_hash(package.archive, package.calendar, issuer),
    )
    return replace(package, study=study, issuer=issuer)
