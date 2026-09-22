from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaxRow:
    fill_id: str
    cost_basis_status: str
    cost_basis: str | None


def build_tax_rows(fills):  # type: ignore[no-untyped-def]
    return tuple(
        TaxRow(
            str(fill.id),
            "known" if getattr(fill, "cost_basis", None) is not None else "unknown",
            getattr(fill, "cost_basis", None),
        )
        for fill in fills
    )


__all__ = ["TaxRow", "build_tax_rows"]
