"""Deterministic execution scenarios, explicitly synthetic and non-promotable."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from trading_bot.clock import require_utc
from trading_bot.config.hybrid import HybridSettings
from trading_bot.hybrid.execution import (
    cancel_order,
    fill_order,
    mark_account,
    reserve_order,
    settle,
)
from trading_bot.hybrid.models import Account, Fact, FillFact, PaperOrder, Quote
from trading_bot.hybrid.worker import Journal


class TimedStep(Fact):
    at: datetime
    _utc = field_validator("at")(require_utc)


class QuoteStep(TimedStep):
    kind: Literal["quote"]
    quote: Quote


class OrderStep(TimedStep):
    kind: Literal["order"]
    order: PaperOrder


class FillStep(TimedStep):
    kind: Literal["fill"]
    fill: FillFact
    settlement_at: datetime | None = None


class CancelStep(TimedStep):
    kind: Literal["cancel"]
    order_id: str


class SettleStep(TimedStep):
    kind: Literal["settle"]


Step = Annotated[
    QuoteStep | OrderStep | FillStep | CancelStep | SettleStep, Field(discriminator="kind")
]


class Scenario(Fact):
    steps: tuple[Step, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if any(a.at > b.at for a, b in zip(self.steps, self.steps[1:], strict=False)):
            raise ValueError("scenario clock cannot reverse")
        if any(isinstance(step, FillStep) and step.fill.at != step.at for step in self.steps):
            raise ValueError("fill clock must match event clock")
        return self


async def replay(
    scenario: Scenario,
    policy: HybridSettings,
    initial: Account,
    *,
    owner: Journal | None = None,
) -> Account:
    quotes: dict[str, Quote] = {}
    state = initial
    digest = hashlib.sha256(scenario.model_dump_json().encode()).hexdigest()
    for index, step in enumerate(scenario.steps):
        if isinstance(step, QuoteStep):
            if step.quote.as_of > step.at:
                raise ValueError("future quote cannot enter scenario")
            quotes[step.quote.symbol] = step.quote

        def transition(account: Account, event: Step = step) -> Account:
            if isinstance(event, QuoteStep):
                if account.valuation_at is not None and event.at <= account.valuation_at:
                    return account
                return mark_account(account, quotes, event.at)
            if isinstance(event, OrderStep):
                if event.order.symbol not in quotes:
                    raise ValueError("order has no quote")
                return reserve_order(
                    account,
                    event.order,
                    quotes[event.order.symbol],
                    event.at,
                    policy,
                    exposure_quotes=quotes,
                )
            if isinstance(event, FillStep):
                return fill_order(account, event.fill, policy, settlement_at=event.settlement_at)
            if isinstance(event, CancelStep):
                return cancel_order(account, event.order_id)
            return settle(account, event.at)

        kind = "mark" if step.kind == "quote" else step.kind
        state = (
            await owner.change(
                f"scenario:{digest}:{index}",
                kind,
                {"scenario_hash": digest, "step": index},
                transition,
            )
            if owner is not None
            else transition(state)
        )
    return state
