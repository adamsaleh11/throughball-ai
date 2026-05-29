import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple


@dataclass
class RequestContext:
    request_id: str
    trace_id: str
    max_tool_calls: int = 5
    allow_external: bool = False
    tool_call_count: int = 0
    _cache: dict = field(default_factory=dict, repr=False)

    def _normalize_inputs(self, inputs: dict) -> dict:
        return {
            key: value
            for key, value in inputs.items()
            if value is not None and value is not False
        }

    def _cache_key(self, tool_name: str, inputs: dict) -> Tuple[str, str]:
        canonical = json.dumps(
            self._normalize_inputs(inputs),
            sort_keys=True,
            separators=(",", ":"),
        )
        input_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return (tool_name, input_hash)

    def get_cached(self, tool_name: str, inputs: dict) -> Optional[Any]:
        return self._cache.get(self._cache_key(tool_name, inputs))

    def set_cached(self, tool_name: str, inputs: dict, result: Any) -> None:
        self._cache[self._cache_key(tool_name, inputs)] = result
