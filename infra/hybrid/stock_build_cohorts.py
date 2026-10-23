"""Private immutable original-source cohorts; no registration or native authority."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _Cohort:
    source_sha256: str
    commit: str
    tree: str
    profile_id: str
    modules: tuple[tuple[str, str], ...]


_COHORTS = (
    _Cohort(
        "a54a71ab93bbddb9b098678ba4fe638c12faefc0157ddc7cc3a7f7d1e120b674",
        "479fca6ce789692d2a088b162fe6bcfeb2ad8336",
        "98257c8083cc6395fde92c600b1683b783952955",
        "stock-producer-causal-479-v1",
        (
            (
                "stock_build_engine.py",
                "9ad12baf09172fbd485b08b2ec1df3ca76119ecf34ec452759f3ba5782e12064",
            ),
            (
                "stock_compose_render.py",
                "fbaba8973249e0b9afecab75c6c5a02868a68821e41639e1a51d11af00cc6d13",
            ),
            (
                "stock_probe_controller.py",
                "40929e4f45c695b0429373fea2e77e32ba1d4ec15c9e2b0fefed3db144b5a3f8",
            ),
            (
                "stock_producer.py",
                "8729100585927dd9588bd02fa6ef488e08202e8c5f4089987a7f16c7e85576dc",
            ),
            (
                "stock_release_producer.py",
                "2ff1bee7bc22173a61f27c8f4ae14254bd9723bed417a14e7efaf9e53746d6fa",
            ),
            (
                "stock_release_publication.py",
                "5a1dd309a61226df3dfae6403b19653a96147bf2496076b527e99144f409d1e7",
            ),
            (
                "stock_source_prepare.py",
                "10d3fba54190e9861eac997bf7990a17f78194dc627482254a1379a7b5f8803c",
            ),
        ),
    ),
    _Cohort(
        "829465b9fcdc5efd10f61ee18ba7eea342cc697f5c3323486283c0c943a56e29",
        "bac162fd6eb6178516a212d30846fb1a055c90fb",
        "21953af2db3189b5a3a9c03c22b3e35baea29683",
        "stock-producer-causal-bac-v1",
        (
            (
                "stock_build_engine.py",
                "849beb35913a0168429517dc381bc4ee9bca2c8d6aaee92a7170afcc1dada3e8",
            ),
            (
                "stock_compose_render.py",
                "fbaba8973249e0b9afecab75c6c5a02868a68821e41639e1a51d11af00cc6d13",
            ),
            (
                "stock_probe_controller.py",
                "40929e4f45c695b0429373fea2e77e32ba1d4ec15c9e2b0fefed3db144b5a3f8",
            ),
            (
                "stock_producer.py",
                "017b16d2a3371c62a38df373686c075a222fd28c0089fcaf801624ee3a071c88",
            ),
            (
                "stock_release_producer.py",
                "5bbb909368b70a8619adaaca69e487423cedfa533dd6840247ffdc8cfefbac38",
            ),
            (
                "stock_release_publication.py",
                "5a1dd309a61226df3dfae6403b19653a96147bf2496076b527e99144f409d1e7",
            ),
            (
                "stock_source_prepare.py",
                "10d3fba54190e9861eac997bf7990a17f78194dc627482254a1379a7b5f8803c",
            ),
        ),
    ),
)


def _source_cohort(source_sha256: str) -> _Cohort:
    if type(source_sha256) is str:
        for cohort in _COHORTS:
            if source_sha256 == cohort.source_sha256:
                return cohort
    raise ValueError("stock_build_cohort_unavailable") from None


def _commit_cohort(commit: str) -> _Cohort:
    if type(commit) is str:
        for cohort in _COHORTS:
            if commit == cohort.commit:
                return cohort
    raise ValueError("stock_build_cohort_unavailable") from None
