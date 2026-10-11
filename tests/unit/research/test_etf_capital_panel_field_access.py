"""Bounded panel data admission must not regain unresolved reflection."""

from dataclasses import fields, is_dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import get_args, get_type_hints

import pytest

from tests.unit.research.test_etf_capital_panel_models import training
from trading_bot.research import etf_capital_panel_models as models


def panel_schemas():
    """Discover reachable declaration schemas, not implementation reader entries."""
    pending = [*models._TAGS, models.CapitalPanelLabel]
    seen = set()
    while pending:
        schema = pending.pop()
        if isinstance(schema, type) and is_dataclass(schema):
            if schema in seen:
                continue
            seen.add(schema)
            pending.extend(get_type_hints(schema).values())
        else:
            pending.extend(get_args(schema))
    return sorted(seen, key=lambda schema: schema.__name__)


def test_all_panel_fields_preserve_objects_and_preimage_declaration_order():
    # A reader typo, omitted nested schema or field-order change must fail.
    reader = getattr(models, "_field_value", None)
    assert callable(reader), "bounded data-field admission is missing"
    for schema in panel_schemas():
        value = object.__new__(schema)
        for item in fields(schema):
            object.__setattr__(value, item.name, object())
        for item in fields(schema):
            assert reader(value, item.name) is getattr(value, item.name)
        expected = tuple(
            getattr(value, item.name)
            for item in fields(schema)
            if item.name not in (*models._FLAGS, "input_hash")
        )
        actual = models._values(value)
        assert len(actual) == len(expected)
        assert all(a is b for a, b in zip(actual, expected, strict=True))


@pytest.mark.parametrize("name", ("place_order", "__dict__", "unknown", "", None, 0))
def test_unknown_and_non_string_field_access_denies_instead_of_reflecting(name):
    reader = getattr(models, "_field_value", None)
    assert callable(reader), "bounded data-field admission is missing"
    with pytest.raises(ValueError, match="capital_economic_panel_invalid"):
        reader(SimpleNamespace(place_order="must not be read"), name)


@pytest.mark.parametrize("flag", models._FLAGS)
@pytest.mark.parametrize("impostor", (True, 0, None, Decimal(0)))
def test_false_flag_check_requires_false_identity_for_every_flag(flag, impostor):
    check = getattr(models, "_false_flags", None)
    assert callable(check), "literal five-flag admission is missing"
    value = training()
    assert check(value) is True
    object.__setattr__(value, flag, impostor)
    assert check(value) is False


def test_existing_training_literal_identity_is_unchanged():
    assert training().input_hash == (
        "197adc3998c5e96c327b0686caaf6d7361148278481adfe06d557080937be9ab"
    )
