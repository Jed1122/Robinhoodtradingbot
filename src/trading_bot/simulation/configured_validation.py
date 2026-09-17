"""Validate unique synthetic input streams before scheduling or drawing outcomes."""

from dataclasses import dataclass, replace
from datetime import timedelta

from trading_bot.domain import DataHash
from trading_bot.simulation.configured_codec import configured_hash
from trading_bot.simulation.configured_models import (
    ConfiguredErrorReason,
    ConfiguredOrderRequest,
    SyntheticCancelRequest,
    SyntheticInputEvent,
    SyntheticMarketEvent,
    checked,
    deny,
)


@dataclass(frozen=True, slots=True)
class IndexedEvent:
    event: SyntheticInputEvent
    digest: DataHash
    delivery_index: int
    duplicate_indices: tuple[int, ...] = ()


def validate_stream(request: ConfiguredOrderRequest) -> tuple[IndexedEvent, ...]:
    with checked():
        if type(request) is not ConfiguredOrderRequest or type(request.events) is not tuple:
            deny()
        records: list[IndexedEvent] = []
        seen: dict[str, int] = {}
        previous = request.initial.submitted
        previous_window = request.submission_window
        ack_at = previous.occurred_at + timedelta(
            milliseconds=request.simulation.latency_milliseconds
        )
        cancel_seen = False
        for index, event in enumerate(request.events):
            if type(event) not in (SyntheticMarketEvent, SyntheticCancelRequest):
                deny()
            event.__post_init__()
            digest = configured_hash("input_event", event)
            prior = seen.get(event.event_id)
            if prior is not None:
                original = records[prior]
                if original.digest != digest:
                    deny(ConfiguredErrorReason.DUPLICATE)
                records[prior] = replace(
                    original, duplicate_indices=(*original.duplicate_indices, index)
                )
                continue
            if (
                event.cursor.sequence <= previous.sequence
                or event.cursor.occurred_at < previous.occurred_at
                or event.cursor.occurred_at > request.end_at
            ):
                deny(ConfiguredErrorReason.ORDERING)
            if isinstance(event, SyntheticMarketEvent):
                if (
                    event.quote.instrument_id != request.initial.order.instrument_id
                    or event.clock.asset_class is not request.initial.position.asset_class
                ):
                    deny(ConfiguredErrorReason.IDENTITY)
                if (
                    event.window != previous_window
                    and event.window.starts_at < previous_window.ends_at
                ):
                    deny(ConfiguredErrorReason.ORDERING)
                previous_window = event.window
            else:
                if cancel_seen:
                    deny(ConfiguredErrorReason.UNSUPPORTED)
                if event.cursor.occurred_at < ack_at:
                    deny(ConfiguredErrorReason.ORDERING)
                # Even an acknowledgement beyond the horizon must be representable.
                event.cursor.occurred_at + timedelta(
                    milliseconds=request.simulation.latency_milliseconds
                )
                cancel_seen = True
            seen[event.event_id] = len(records)
            records.append(IndexedEvent(event, digest, index))
            previous = event.cursor
        return tuple(records)
