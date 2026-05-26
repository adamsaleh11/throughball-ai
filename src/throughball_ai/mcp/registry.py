from dataclasses import dataclass
from typing import Callable


@dataclass
class ToolDefinition:
    name: str
    handler: Callable
    timeout_ms: int
    cacheable: bool = True
    max_retry_count: int = 1
    description: str = ""

    def validate(self) -> None:
        if not self.name:
            raise ValueError("ToolDefinition.name must not be empty")
        if self.timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be positive, got {self.timeout_ms}")
        if self.max_retry_count < 0:
            raise ValueError(f"max_retry_count must be >= 0, got {self.max_retry_count}")
        if not callable(self.handler):
            raise ValueError(f"handler must be callable, got {type(self.handler)}")
