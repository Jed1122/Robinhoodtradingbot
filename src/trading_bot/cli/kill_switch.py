CLEAR_ACK = "I CONFIRM THE INCIDENT IS RESOLVED"


def validate_clear(reason: str, acknowledgement: str) -> None:
    if not reason.strip():
        raise ValueError("reason is required")
    if acknowledgement != CLEAR_ACK:
        raise ValueError("exact acknowledgement is required")


__all__ = ["CLEAR_ACK", "validate_clear"]
