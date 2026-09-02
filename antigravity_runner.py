import asyncio
import json
import logging
import os
import re
from typing import AsyncGenerator, Callable, Optional

from agent_base import AgentEvent, AgentSession, AgentType, BaseAgentRunner
from config import Config

logger = logging.getLogger(__name__)


class AntigravityRunner(BaseAgentRunner):
    """Bộ điều khiển và giao tiếp với Google Antigravity CLI (agy)."""

    @property
    def agent_type(self) -> str:
        return AgentType.ANTIGRAVITY

    @property
    def display_name(self) -> str:
        return "🤖 Antigravity"

    @property
    def emoji(self) -> str:
        return "🤖"

    def get_available_models(self) -> list[tuple[str, str]]:
        return [
            ("Gemini 3.7 Flash (High)", "⚡ Gemini 3.7 Flash"),
            ("Gemini 3.1 Pro (High)", "🧠 Gemini 3.1 Pro"),
            ("Claude Sonnet 4.6 (Thinking)", "🎭 Claude Sonnet 4.6"),
            ("Claude Opus 4.6 (Thinking)", "🦁 Claude Opus 4.6"),
        ]

    def get_available_efforts(self) -> list[tuple[str, str]]:
        return [
            ("high", "High 🔴"),
            ("medium", "Medium 🟡"),
            ("low", "Low 🟢"),
        ]

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
            return f"❓ **Antigravity hỏi:** {params.get('question', '')[:100]}"
        else:
            return f"⚙️ **Đang chạy công cụ:** `{tool_name}`"

    async def execute_prompt(
        self,
        session: AgentSession,
        prompt: str,
        workspace_dir: str,
        on_status_update: Optional[Callable[[str], None]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Thực thi prompt qua Antigravity CLI và stream các sự kiện trả về."""
        # Thêm chỉ dẫn an toàn cho phiên làm việc mới
        effective_prompt = prompt
        if not session.conversation_id:
            safety_prefix = (
                f"[SYSTEM SAFETY CONSTRAINT: You must NEVER execute destructive OS operations "
                f"such as formatting disks, running diskpart, clearing partitions, deleting Windows system directories, "
                f"modifying HKLM registry, or shutting down PC. Strictly confine file operations to: {workspace_dir}]\n\n"
            )
            effective_prompt = safety_prefix + prompt

        cmd = [
            Config.AGY_PATH,
            "-p",
            effective_prompt,
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]

        if session.conversation_id:
            cmd.extend(["--conversation", session.conversation_id])

        if session.model:
            cmd.extend(["--model", session.model])
        elif session.effort:
            cmd.extend(["--effort", session.effort])

        if session.mode:
            cmd.extend(["--mode", session.mode])

        logger.info(
            f"Spawning agy for user {session.user_id} in {workspace_dir}: {' '.join(cmd[:4])}..."
        )

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
            session.current_process = process

            final_response = ""
            current_conv_id = session.conversation_id
            total_duration = 0.0
            total_tokens = 0

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
                        agent_type=AgentType.ANTIGRAVITY,
                        conversation_id=conv_id,
                        raw_data=data,
                    )

                # 2. Sự kiện cập nhật bước
                elif event_type == "step_update":
                    step = data.get("step_update", {})
                    step_type = step.get("step_type")
                    state = step.get("state")

                    if step_type == "tool":
                        tool_name = step.get("tool_name", "")
                        tool_info = step.get("tool_info", {})
                        params = tool_info.get("parameters", {})

                        if state == "ACTIVE":
                            status_msg = self._format_tool_action(
                                tool_name, params
                            )
                            yield AgentEvent(
                                event_type="tool_start",
                                agent_type=AgentType.ANTIGRAVITY,
                                tool_name=tool_name,
                                tool_args=params,
                                content=status_msg,
                                raw_data=data,
                            )
                        elif state == "DONE":
                            yield AgentEvent(
                                event_type="tool_done",
                                agent_type=AgentType.ANTIGRAVITY,
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
                                agent_type=AgentType.ANTIGRAVITY,
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
                            agent_type=AgentType.ANTIGRAVITY,
                            content=f"❌ Antigravity gặp lỗi:\n{error_msg or 'Không rõ nguyên nhân cụ thể.'}",
                            raw_data=data,
                        )
                        return

                    yield AgentEvent(
                        event_type="result",
                        agent_type=AgentType.ANTIGRAVITY,
                        content=final_response,
                        conversation_id=current_conv_id,
                        duration_seconds=total_duration,
                        tokens_used=total_tokens,
                        raw_data=data,
                    )

            await process.wait()

            if process.returncode != 0 and not final_response:
                stderr_data = await process.stderr.read()
                err_msg = stderr_data.decode("utf-8", errors="replace").strip()
                yield AgentEvent(
                    event_type="error",
                    agent_type=AgentType.ANTIGRAVITY,
                    content=f"❌ Antigravity gặp lỗi (Code {process.returncode}):\n{err_msg or 'Tiến trình kết thúc mà không có kết quả.'}",
                )

        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.kill()
            yield AgentEvent(
                event_type="error",
                agent_type=AgentType.ANTIGRAVITY,
                content="🛑 Tác vụ Antigravity đã bị hủy theo yêu cầu.",
            )
        except Exception as e:
            logger.exception("Exception in Antigravity execution")
            yield AgentEvent(
                event_type="error",
                agent_type=AgentType.ANTIGRAVITY,
                content=f"❌ Lỗi hệ thống khi gọi Antigravity: {str(e)}",
            )
        finally:
            session.current_process = None
