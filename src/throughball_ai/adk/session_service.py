from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


_RETRIEVAL_REF_KEYS = ("document_id", "chunk_id", "source_path", "summary")


@dataclass
class AdkSession:
    session_id: str
    request_id: str
    agent_name: str
    selected_model: str
    task_state: dict[str, Any] = field(default_factory=dict)
    retrieval_refs: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    iteration_count: int = 0
    tool_call_count: int = 0
    retry_count: int = 0
    degraded: bool = False


class InMemorySessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, AdkSession] = {}

    def create_session(
        self,
        *,
        session_id: str,
        request_id: str,
        agent_name: str,
        selected_model: str,
    ) -> AdkSession:
        session = AdkSession(
            session_id=session_id,
            request_id=request_id,
            agent_name=agent_name,
            selected_model=selected_model,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> AdkSession:
        return self._sessions[session_id]

    def update_task_state(self, session_id: str, task_state: Mapping[str, Any]) -> None:
        self.get_session(session_id).task_state = dict(task_state)

    def add_summary(self, session_id: str, summary: str) -> None:
        self.get_session(session_id).summary = summary

    def add_retrieval_reference(
        self,
        session_id: str,
        retrieval_ref: Mapping[str, Any],
    ) -> None:
        compact_ref = {
            key: retrieval_ref[key]
            for key in _RETRIEVAL_REF_KEYS
            if key in retrieval_ref and retrieval_ref[key] is not None
        }
        self.get_session(session_id).retrieval_refs.append(compact_ref)

    def increment_iteration(self, session_id: str) -> None:
        self.get_session(session_id).iteration_count += 1

    def increment_tool_calls(self, session_id: str, count: int = 1) -> None:
        self.get_session(session_id).tool_call_count += count

    def increment_retry_count(self, session_id: str, count: int = 1) -> None:
        self.get_session(session_id).retry_count += count

    def mark_degraded(self, session_id: str, degraded: bool = True) -> None:
        self.get_session(session_id).degraded = degraded


def create_session_service(
    sessions: Optional[dict[str, AdkSession]] = None,
) -> InMemorySessionService:
    service = InMemorySessionService()
    if sessions:
        service._sessions.update(sessions)
    return service
