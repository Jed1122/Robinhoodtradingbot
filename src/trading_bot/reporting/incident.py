from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IncidentReport:
    trigger: str
    masked_account: str
    timeline: tuple[str, ...]
    unresolved_items: tuple[str, ...]


def mask_account(value: str) -> str:
    return f"***{value[-4:]}" if len(value) >= 4 else "***"


__all__ = ["IncidentReport", "mask_account"]
