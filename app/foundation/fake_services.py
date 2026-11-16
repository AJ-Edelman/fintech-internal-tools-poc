"""In-process fake receivers for the demo and tests. Owner after stage 0: worker A."""


class FakeService:
    def __init__(self, name: str):
        self.name = name
        self.fail = False  # when True, every call raises
        self.calls = 0  # every call, including failed and duplicate ones
        self.received: dict[str, dict] = {}  # idempotency key -> payload, applied once

    def receive(self, idempotency_key: str, payload: dict) -> str:
        self.calls += 1
        if self.fail:
            raise ConnectionError(f"{self.name} is unavailable")
        if idempotency_key in self.received:
            return "duplicate"
        self.received[idempotency_key] = payload
        return "accepted"

    def reset(self) -> None:
        self.fail, self.calls, self.received = False, 0, {}


FAKES = {"payments": FakeService("payments"), "ledger": FakeService("ledger")}


def get_fake(name: str) -> FakeService:
    return FAKES[name]


def reset_all() -> None:
    for fake in FAKES.values():
        fake.reset()
