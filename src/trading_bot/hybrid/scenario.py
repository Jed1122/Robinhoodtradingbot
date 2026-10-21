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
    next_index = 0
    for index, step in enumerate(scenario.steps):
        if index < next_index:
            continue
        request: dict[str, object] = {"scenario_hash": digest, "step": index}
        if isinstance(step, QuoteStep):
            # Consecutive simultaneous quotes form one observation. Never value a
            # restored multi-symbol account from the first incomplete fragment.
            batch: dict[str, Quote] = {}
            next_index = index
            while next_index < len(scenario.steps):
                candidate = scenario.steps[next_index]
                if not isinstance(candidate, QuoteStep) or candidate.at != step.at:
                    break
                if candidate.quote.as_of > candidate.at:
                    raise ValueError("future quote cannot enter scenario")
                symbol = candidate.quote.symbol
                if symbol in batch and batch[symbol] != candidate.quote:
                    raise ValueError("conflicting simultaneous quote")
                batch[symbol] = candidate.quote
                next_index += 1
            quotes.update(batch)
            if next_index > index + 1:
                # Existing pre-batch journal requests conflict rather than silently
                # adopting a different transition under an old idempotency key.
                request["quote_steps"] = list(range(index, next_index))

        def transition(account: Account, event: Step = step) -> Account:
            if isinstance(event, QuoteStep):
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
                request,
                transition,
            )
            if owner is not None
            else transition(state)
        )
    return state
