import logging
import re
from typing import AsyncGenerator, Callable, Optional

from agent_base import AgentEvent, AgentSession, AgentType, BaseAgentRunner
from antigravity_runner import AntigravityRunner
from codex_runner import CodexRunner
from config import Config

logger = logging.getLogger(__name__)


class AgentManager:
    """Quản trị viên điều phối các Agent Engine (Antigravity & OpenAI Codex)."""

    def __init__(self):
        self.runners: dict[str, BaseAgentRunner] = {
            AgentType.ANTIGRAVITY: AntigravityRunner(),
            AgentType.CODEX: CodexRunner(),
        }
        # Lưu agent đang chọn cho từng user: user_id -> "antigravity" | "codex"
        self._user_active_agent: dict[int, str] = {}
        # Lưu phiên làm việc độc lập: (user_id, agent_type) -> AgentSession
        self._sessions: dict[tuple[int, str], AgentSession] = {}

    def get_active_agent_type(self, user_id: int) -> str:
        """Lấy loại Agent hiện tại của user."""
        return self._user_active_agent.get(user_id, Config.DEFAULT_AGENT)

    def set_active_agent_type(self, user_id: int, agent_type: str) -> bool:
        """Chuyển đổi Agent cho user."""
        if agent_type not in self.runners:
            return False
        self._user_active_agent[user_id] = agent_type
        return True

    def get_active_runner(self, user_id: int) -> BaseAgentRunner:
        """Lấy runner tương ứng với Agent hiện tại."""
        agent_type = self.get_active_agent_type(user_id)
        return self.runners.get(agent_type, self.runners[AgentType.ANTIGRAVITY])

    def get_session(
        self, user_id: int, agent_type: Optional[str] = None
    ) -> AgentSession:
        """Lấy phiên làm việc của user cho Agent cụ thể."""
        if agent_type is None:
            agent_type = self.get_active_agent_type(user_id)

        key = (user_id, agent_type)
        if key not in self._sessions:
            if agent_type == AgentType.CODEX:
                self._sessions[key] = AgentSession(
                    user_id=user_id,
                    agent_type=AgentType.CODEX,
                    model=Config.DEFAULT_CODEX_MODEL,
                    effort=Config.DEFAULT_CODEX_EFFORT,
                    mode="auto",
                )
            else:
                self._sessions[key] = AgentSession(
                    user_id=user_id,
                    agent_type=AgentType.ANTIGRAVITY,
                    model=Config.DEFAULT_ANTIGRAVITY_MODEL,
                    effort=Config.DEFAULT_EFFORT,
                    mode=Config.DEFAULT_MODE,
                )
        return self._sessions[key]

    def reset_session(
        self, user_id: int, agent_type: Optional[str] = None
    ) -> None:
        """Làm mới ngữ cảnh của Agent hiện tại (hoặc Agent chỉ định)."""
        session = self.get_session(user_id, agent_type)
        session.conversation_id = None
        session.history.clear()

    def reset_all_sessions(self, user_id: int) -> None:
        """Làm mới tất cả phiên làm việc của user."""
        for agent_t in AgentType.ALL:
            self.reset_session(user_id, agent_t)

    def set_model(
        self, user_id: int, model_name: str, agent_type: Optional[str] = None
    ) -> None:
        """Cài đặt Model cho Agent."""
        session = self.get_session(user_id, agent_type)
        session.model = model_name.strip()

    def set_effort(
        self, user_id: int, effort: str, agent_type: Optional[str] = None
    ) -> None:
        """Cài đặt Reasoning Effort cho Agent."""
        session = self.get_session(user_id, agent_type)
        session.effort = effort.strip().lower()

        # Nếu là Antigravity và model có dạng "Tên (Effort)", cập nhật lại chuỗi model
        if session.agent_type == AgentType.ANTIGRAVITY:
            effort_map = {"high": "High", "medium": "Medium", "low": "Low"}
            target_effort = effort_map.get(session.effort, "High")
            if session.model and "(" in session.model:
                if re.search(
                    r"\((High|Medium|Low)\)", session.model, re.IGNORECASE
                ):
                    session.model = re.sub(
                        r"\((High|Medium|Low)\)",
                        f"({target_effort})",
                        session.model,
                        flags=re.IGNORECASE,
                    )

    def set_mode(
        self, user_id: int, mode: str, agent_type: Optional[str] = None
    ) -> None:
        """Cài đặt Mode thực thi cho Agent."""
        session = self.get_session(user_id, agent_type)
        session.mode = mode.strip().lower()

    def cancel_active_task(self, user_id: int) -> bool:
        """Hủy tác vụ đang chạy trên bất kỳ Agent nào của user này."""
        cancelled = False
        for agent_t in AgentType.ALL:
            session = self.get_session(user_id, agent_t)
            runner = self.runners[agent_t]
            if runner.cancel_active_task(session):
                cancelled = True
        return cancelled

    def is_running(self, user_id: int) -> bool:
        """Kiểm tra xem user có tác vụ nào đang chạy trên các Agent không."""
        for agent_t in AgentType.ALL:
            session = self.get_session(user_id, agent_t)
            runner = self.runners[agent_t]
            if runner.is_running(session):
                return True
        return False

    async def execute_prompt(
        self,
        user_id: int,
        prompt: str,
        workspace_dir: str,
        on_status_update: Optional[Callable[[str], None]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Điều phối thực thi prompt tới Runner đang được chọn."""
        runner = self.get_active_runner(user_id)
        session = self.get_session(user_id, runner.agent_type)

        async for event in runner.execute_prompt(
            session=session,
            prompt=prompt,
            workspace_dir=workspace_dir,
            on_status_update=on_status_update,
        ):
            yield event


# Singleton instance
agent_mgr = AgentManager()
