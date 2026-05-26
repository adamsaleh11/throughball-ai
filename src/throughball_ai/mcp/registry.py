from dataclasses import dataclass
from typing import Any, Callable, Type

from pydantic import BaseModel


@dataclass
class ToolDefinition:
    name: str
    handler: Callable
    timeout_ms: int
    cacheable: bool = True
    max_retry_count: int = 1
    description: str = ""
