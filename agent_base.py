import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Optional


class AgentType:
    ANTIGRAVITY = "antigravity"
    CODEX = "codex"

    ALL = [ANTIGRAVITY, CODEX]

    DISPLAY_NAMES = {
        ANTIGRAVITY: "🤖 Antigravity",
        CODEX: "⚡ OpenAI Codex",
    }

    EMOJIS = {
        ANTIGRAVITY: "🤖",
        CODEX: "⚡",
    }


@dataclass
class AgentEvent:
    event_type: str  # "init", "tool_start", "tool_done", "thought", "text_delta", "result", "error"
    agent_type: str = AgentType.ANTIGRAVITY
    content: str = ""
    conversation_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    duration_seconds: Optional[float] = None
    tokens_used: Optional[int] = None
    raw_data: Optional[dict] = None


@dataclass
class AgentSession:
    user_id: int
    agent_type: str
    conversation_id: Optional[str] = None
    model: str = ""
    effort: str = ""
    mode: str = ""
    current_process: Optional[asyncio.subprocess.Process] = None
    history: list[dict] = field(default_factory=list)


class BaseAgentRunner(ABC):
    """Lớp trừu tượng định nghĩa giao diện chung cho các Agent Engine."""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        pass

    @property
    @abstractmethod
    def emoji(self) -> str:
        pass

    @abstractmethod
    async def execute_prompt(
        self,
        session: AgentSession,
        prompt: str,
        workspace_dir: str,
        on_status_update: Optional[Callable[[str], None]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Thực thi prompt và stream các sự kiện."""
        pass

    def cancel_active_task(self, session: AgentSession) -> bool:
        """Hủy tiến trình đang thực thi của session này."""
        if session.current_process and session.current_process.returncode is None:
            try:
                session.current_process.kill()
                return True
            except Exception:
                return False
        return False

    def is_running(self, session: AgentSession) -> bool:
        """Kiểm tra xem agent có đang chạy tiến trình không."""
        return (
            session.current_process is not None
            and session.current_process.returncode is None
        )

    @abstractmethod
    def get_available_models(self) -> list[tuple[str, str]]:
        """Danh sách (model_id, label) để hiển thị trên UI."""
        pass

    @abstractmethod
    def get_available_efforts(self) -> list[tuple[str, str]]:
        """Danh sách (effort_id, label)."""
        pass
