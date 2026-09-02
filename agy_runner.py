import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncGenerator, Callable, Optional
from config import Config

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    event_type: str  # "init", "tool_start", "tool_done", "thought", "text_delta", "result", "error"
    content: str = ""
    conversation_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    duration_seconds: Optional[float] = None
    tokens_used: Optional[int] = None
    raw_data: Optional[dict] = None


@dataclass
class UserSession:
    user_id: int
    conversation_id: Optional[str] = None
    model: str = Config.DEFAULT_MODEL
    effort: str = Config.DEFAULT_EFFORT
    mode: str = Config.DEFAULT_MODE
    current_process: Optional[asyncio.subprocess.Process] = None
    history: list[dict] = field(default_factory=list)


class AntigravityRunner:
    """Điều khiển và giao tiếp với Antigravity CLI."""

    def __init__(self):
        self.sessions: dict[int, UserSession] = {}

    def get_session(self, user_id: int) -> UserSession:
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id=user_id)
        return self.sessions[user_id]

    def reset_session(self, user_id: int) -> None:
        session = self.get_session(user_id)
        session.conversation_id = None

    def set_conversation_id(self, user_id: int, conv_id: str) -> None:
        session = self.get_session(user_id)
        session.conversation_id = conv_id.strip()

    def set_model(self, user_id: int, model_name: str) -> None:
        session = self.get_session(user_id)
        session.model = model_name.strip()

    def set_effort(self, user_id: int, effort: str) -> None:
        session = self.get_session(user_id)
        session.effort = effort.strip().lower()
        # Nếu model hiện tại có dạng "Tên Model (Effort)", cập nhật lại tên model tương ứng
        import re
        effort_map = {"high": "High", "medium": "Medium", "low": "Low"}
        target_effort = effort_map.get(session.effort, "High")
        if session.model and "(" in session.model:
            if re.search(r'\((High|Medium|Low)\)', session.model, re.IGNORECASE):
                session.model = re.sub(r'\((High|Medium|Low)\)', f"({target_effort})", session.model, flags=re.IGNORECASE)

    def set_mode(self, user_id: int, mode: str) -> None:
        session = self.get_session(user_id)
        session.mode = mode.strip().lower()

    def cancel_active_task(self, user_id: int) -> bool:
        """Hủy tiến trình Antigravity đang chạy cho người dùng này."""
        session = self.get_session(user_id)
        if session.current_process and session.current_process.returncode is None:
            try:
                # Trên Windows cần kill process
                session.current_process.kill()
                logger.info(f"Killed process for user {user_id}")
                return True
            except Exception as e:
                logger.error(f"Error killing process: {e}")
                return False
        return False

    def is_running(self, user_id: int) -> bool:
        session = self.get_session(user_id)
        return session.current_process is not None and session.current_process.returncode is None

    def _format_tool_action(self, tool_name: str, params: dict) -> str:
        """Tạo thông báo thân thiện khi Antigravity thực thi công cụ."""
        if tool_name == "run_command":
            cmd = params.get("CommandLine", "")
            return f"⚡ **Đang chạy lệnh:** `{cmd[:120]}`"
        elif tool_name == "write_to_file":
            tgt = params.get("TargetFile", "")
            fname = os.path.basename(tgt) if tgt else "file"
            return f"📝 **Đang tạo/ghi file:** `{fname}`"
        elif tool_name in ("replace_file_content", "multi_replace_file_content"):
            tgt = params.get("TargetFile", "")
            fname = os.path.basename(tgt) if tgt else "file"
            return f"✏️ **Đang sửa file:** `{fname}`"
        elif tool_name in ("view_file", "list_dir", "find_by_name", "grep_search"):
            return f"🔍 **Đang tra cứu:** `{tool_name}`"
        elif tool_name in ("search_web", "read_url_content", "open_browser_url"):
            return f"🌐 **Đang tìm kiếm web:** `{tool_name}`"
        elif tool_name == "generate_image":
            return f"🎨 **Đang tạo hình ảnh AI...**"
        elif tool_name == "ask_question":
            return f"❓ **Antigravity đặt câu hỏi:** {params.get('question', '')[:100]}"
        else:
            return f"⚙️ **Đang chạy công cụ:** `{tool_name}`"

    async def execute_prompt(
        self,
        user_id: int,
        prompt: str,
        workspace_dir: str,
        on_status_update: Optional[Callable[[str], None]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Thực thi prompt qua Antigravity CLI và stream các sự kiện trả về.
        """
        session = self.get_session(user_id)

        # Xây dựng lệnh gọi CLI
        cmd = [
            Config.AGY_PATH,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]

        if session.conversation_id:
            cmd.extend(["--conversation", session.conversation_id])

        if session.model:
            cmd.extend(["--model", session.model])
        elif session.effort:
            # Chỉ truyền --effort nếu không chỉ định model cụ thể (tránh lỗi xung đột flag)
            cmd.extend(["--effort", session.effort])

        if session.mode:
            cmd.extend(["--mode", session.mode])

        logger.info(f"Spawning agy for user {user_id} in {workspace_dir}: {' '.join(cmd[:4])}...")

        try:
            # Tạo subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            session.current_process = process

            final_response = ""
            current_conv_id = session.conversation_id
            total_duration = 0.0
            total_tokens = 0

            # Đọc từng dòng NDJSON từ stdout
            while True:
                line = await process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                event_type = data.get("event")

                # 1. Sự kiện khởi tạo
                if event_type == "init":
                    conv_id = data.get("conversation_id")
                    if conv_id:
                        session.conversation_id = conv_id
                        current_conv_id = conv_id
                    yield AgentEvent(
                        event_type="init",
                        conversation_id=conv_id,
                        raw_data=data,
                    )

                # 2. Sự kiện cập nhật bước (Tool execution / Agent response)
                elif event_type == "step_update":
                    step = data.get("step_update", {})
                    step_type = step.get("step_type")
                    state = step.get("state")

                    if step_type == "tool":
                        tool_name = step.get("tool_name", "")
                        tool_info = step.get("tool_info", {})
                        params = tool_info.get("parameters", {})

                        if state == "ACTIVE":
                            status_msg = self._format_tool_action(tool_name, params)
                            yield AgentEvent(
                                event_type="tool_start",
                                tool_name=tool_name,
                                tool_args=params,
                                content=status_msg,
                                raw_data=data,
                            )
                        elif state == "DONE":
                            yield AgentEvent(
                                event_type="tool_done",
                                tool_name=tool_name,
                                tool_args=params,
                                content=f"✅ Hoàn thành {tool_name}",
                                raw_data=data,
                            )

                    elif step_type == "agent_response":
                        text_delta = step.get("text_delta", "")
                        if text_delta:
                            final_response += text_delta
                            yield AgentEvent(
                                event_type="text_delta",
                                content=text_delta,
                                raw_data=data,
                            )

                # 3. Sự kiện kết quả cuối cùng
                elif event_type == "result":
                    res = data.get("result", {})
                    conv_id = res.get("conversation_id")
                    if conv_id:
                        session.conversation_id = conv_id
                        current_conv_id = conv_id

                    resp_text = res.get("response", "")
                    if resp_text:
                        final_response = resp_text

                    total_duration = res.get("duration_seconds", 0.0)
                    usage = res.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)

                    status = res.get("status", "")
                    error_msg = res.get("error", "")

                    if status == "ERROR" or error_msg:
                        yield AgentEvent(
                            event_type="error",
                            content=f"❌ Antigravity gặp lỗi:\n{error_msg or 'Không rõ nguyên nhân cụ thể.'}",
                            raw_data=data,
                        )
                        return

                    yield AgentEvent(
                        event_type="result",
                        content=final_response,
                        conversation_id=current_conv_id,
                        duration_seconds=total_duration,
                        tokens_used=total_tokens,
                        raw_data=data,
                    )

            # Chờ tiến trình kết thúc
            await process.wait()

            # Nếu không có kết quả dạng NDJSON mà process kết thúc có lỗi
            if process.returncode != 0 and not final_response:
                stderr_data = await process.stderr.read()
                err_msg = stderr_data.decode("utf-8", errors="replace").strip()
                yield AgentEvent(
                    event_type="error",
                    content=f"❌ Antigravity gặp lỗi (Code {process.returncode}):\n{err_msg or 'Tiến trình kết thúc mà không trả về kết quả.'}",
                )

        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.kill()
            yield AgentEvent(
                event_type="error",
                content="🛑 Tác vụ đã bị hủy theo yêu cầu.",
            )
        except Exception as e:
            logger.exception("Exception in Antigravity execution")
            yield AgentEvent(
                event_type="error",
                content=f"❌ Lỗi hệ thống khi gọi Antigravity: {str(e)}",
            )
        finally:
            session.current_process = None


# Singleton instance
agy_runner = AntigravityRunner()
