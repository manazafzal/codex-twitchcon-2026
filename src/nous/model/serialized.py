"""Share local weights without allowing overlapping hook installation or model calls."""

from threading import Event, RLock
from typing import Any


class SerializedBackend:
    def __init__(self, backend: Any, lock: Any = None, stop: Event | None = None) -> None:
        self.backend, self.lock, self.stop = backend, lock or RLock(), stop

    def __getattr__(self, name: str) -> Any:
        value = getattr(self.backend, name)
        if not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            with self.lock:
                if self.stop is not None and self.stop.is_set():
                    raise RuntimeError("Topic build cancelled")
                return value(*args, **kwargs)

        return call
