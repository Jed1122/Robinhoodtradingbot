class MetricsRegistry:
    def __init__(self) -> None:
        self._values: dict[str, float] = {}

    def set(self, name: str, value: float) -> None:
        if not name.replace("_", "").isalnum():
            raise ValueError("unsafe metric name")
        self._values[name] = value

    def render(self) -> str:
        return "".join(f"{name} {value}\n" for name, value in sorted(self._values.items()))


__all__ = ["MetricsRegistry"]
