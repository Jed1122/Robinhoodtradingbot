from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RedactedReport:
    text: str


class ReadOnlyLlmReporter:
    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    def render(self, report: RedactedReport) -> str:
        return report.text


__all__ = ["ReadOnlyLlmReporter", "RedactedReport"]
