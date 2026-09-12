from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4


class EventType(StrEnum):
    GITHUB = "github"
    CI = "ci"
    ENDPOINT = "endpoint"


@dataclass(frozen=True, slots=True)
class ControlPlaneEvent:
    event_type: EventType
    source: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


EventHandler = Callable[[ControlPlaneEvent], None]


class InMemoryEventBus:
    """Small deterministic event bus used by the control-plane core and tests.

    Production transports (Redis Streams, NATS, Kafka, SQS) can implement the same
    publish/subscribe boundary without changing orchestration logic.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._queue: deque[ControlPlaneEvent] = deque()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: ControlPlaneEvent) -> None:
        self._queue.append(event)

    def drain(self) -> int:
        processed = 0
        while self._queue:
            event = self._queue.popleft()
            for handler in self._handlers[event.event_type]:
                handler(event)
            processed += 1
        return processed
