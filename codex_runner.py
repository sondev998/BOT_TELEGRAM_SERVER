import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator, Callable, Optional

from agent_base import AgentEvent, AgentSession, AgentType, BaseAgentRunner
from config import Config

logger = logging.getLogger(__name__)


class CodexRunner(BaseAgentRunner):
    """Bộ điều khiển và giao tiếp với OpenAI Codex CLI (codex)."""

    @property
    def agent_type(self) -> str:
        return AgentType.CODEX

    @property
    def display_name(self) -> str:
        return "⚡ OpenAI Codex"

    @property
    def emoji(self) -> str:
        return "⚡"

    def get_available_models(self) -> list[tuple[str, str]]:
        return [
            ("gpt-5.6-terra", "🧠 GPT-5.6 Terra"),
            ("o3", "🚀 OpenAI o3"),
            ("o3-mini", "⚡ OpenAI o3-mini"),
            ("gpt-4.1", "🌟 GPT-4.1"),
            ("default", "⚙️ Mặc định (config.toml)"),
        ]

    def get_available_efforts(self) -> list[tuple[str, str]]:
        return [
            ("high", "High 🔴"),
            ("medium", "Medium 🟡"),
            ("low", "Low 🟢"),
        ]

    async def execute_prompt(
        self,
        session: AgentSession,
        prompt: str,
        workspace_dir: str,
        on_status_update: Optional[Callable[[str], None]] = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Thực thi prompt qua OpenAI Codex CLI và stream các sự kiện trả về."""
        start_time = time.time()

        # Nếu đã có thread_id (conversation_id), dùng lệnh resume
        if session.conversation_id:
            cmd = [
                Config.CODEX_PATH,
                "exec",
                "resume",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
            ]
            if session.model and session.model.lower() != "default":
                cmd.extend(["-m", session.model])
            if session.effort:
                cmd.extend(["-c", f'model_reasoning_effort="{session.effort}"'])
            cmd.extend([session.conversation_id, prompt])
        else:
            # Tạo phiên mới với thư mục làm việc --cd
            cmd = [
                Config.CODEX_PATH,
                "exec",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
                "--cd",
                workspace_dir,
            ]
            if session.model and session.model.lower() != "default":
                cmd.extend(["-m", session.model])
            effective_prompt = prompt
            if not session.conversation_id:
                safety_prefix = (
                    f"[SYSTEM SAFETY CONSTRAINT: You must NEVER execute destructive OS operations "
                    f"such as formatting disks, running diskpart, clearing partitions, deleting Windows system directories, "
                    f"modifying HKLM registry, or shutting down PC. Strictly confine file operations to: {workspace_dir}]\n\n"
                )
                effective_prompt = safety_prefix + prompt
            cmd.append(effective_prompt)

        logger.info(
            f"Spawning codex for user {session.user_id} in {workspace_dir}: {' '.join(cmd[:5])}..."
        )

        process = None
        agent_messages: list[str] = []
        turn_completed = False

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
            )
            session.current_process = process

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

                event_type = data.get("type")

                # 1. Thread khởi tạo / bắt đầu
                if event_type == "thread.started":
                    thread_id = data.get("thread_id")
                    if thread_id:
                        session.conversation_id = thread_id
                    yield AgentEvent(
                        event_type="init",
                        agent_type=AgentType.CODEX,
                        conversation_id=thread_id,
                        raw_data=data,
                    )

                # 2. Bắt đầu một item (lệnh chạy, file thao tác, v.v.)
                elif event_type == "item.started":
                    item = data.get("item", {})
                    item_type = item.get("type", "")

                    if item_type == "command_execution":
                        cmd_str = item.get("command", "")
                        yield AgentEvent(
                            event_type="tool_start",
                            agent_type=AgentType.CODEX,
                            tool_name="command_execution",
                            content=f"⚡ **Đang chạy lệnh:** `{cmd_str[:120]}`",
                            raw_data=data,
                        )
                    elif item_type in ("file_edit", "file_write", "apply_patch"):
                        path = item.get("path", "")
                        fname = os.path.basename(path) if path else "file"
                        yield AgentEvent(
                            event_type="tool_start",
                            agent_type=AgentType.CODEX,
                            tool_name=item_type,
                            content=f"📝 **Đang thao tác file:** `{fname}`",
                            raw_data=data,
                        )
                    elif item_type == "web_search":
                        yield AgentEvent(
                            event_type="tool_start",
                            agent_type=AgentType.CODEX,
                            tool_name="web_search",
                            content="🌐 **Đang tìm kiếm web...**",
                            raw_data=data,
                        )
                    elif item_type in ("mcp_tool_call", "tool_execution"):
                        tool_name = item.get("tool", "mcp")
                        yield AgentEvent(
                            event_type="tool_start",
                            agent_type=AgentType.CODEX,
                            tool_name=f"mcp:{tool_name}",
                            content=f"⚙️ **Đang gọi MCP:** `{tool_name}`",
                            raw_data=data,
                        )

                # 3. Hoàn thành item
                elif event_type == "item.completed":
                    item = data.get("item", {})
                    item_type = item.get("type", "")

                    if item_type == "command_execution":
                        code = item.get("exit_code", 0)
                        yield AgentEvent(
                            event_type="tool_done",
                            agent_type=AgentType.CODEX,
                            tool_name="command_execution",
                            content=f"✅ Lệnh hoàn tất (Code {code})",
                            raw_data=data,
                        )
                    elif item_type == "agent_message":
                        text = item.get("text", "")
                        if text:
                            agent_messages.append(text)
                            yield AgentEvent(
                                event_type="text_delta",
                                agent_type=AgentType.CODEX,
                                content=text,
                                raw_data=data,
                            )
                    elif item_type == "reasoning":
                        thought = item.get("text", "")
                        if thought:
                            yield AgentEvent(
                                event_type="thought",
                                agent_type=AgentType.CODEX,
                                content=thought,
                                raw_data=data,
                            )

                # 4. Hoàn thành lượt chat
                elif event_type == "turn.completed":
                    turn_completed = True
                    usage = data.get("usage", {})
                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    tokens = inp + out
                    duration = time.time() - start_time
                    final_text = "\n\n".join(agent_messages)

                    yield AgentEvent(
                        event_type="result",
                        agent_type=AgentType.CODEX,
                        content=final_text,
                        conversation_id=session.conversation_id,
                        duration_seconds=duration,
                        tokens_used=tokens,
                        raw_data=data,
                    )

                # 5. Sự kiện lỗi
                elif event_type == "error":
                    err_msg = data.get("message", "Lỗi không xác định")
                    yield AgentEvent(
                        event_type="error",
                        agent_type=AgentType.CODEX,
                        content=f"❌ Codex gặp lỗi:\n{err_msg}",
                        raw_data=data,
                    )
                    return

            await process.wait()

            # Nếu process thoát mà chưa có turn.completed
            if not turn_completed:
                if process.returncode != 0:
                    stderr_data = await process.stderr.read()
                    err_msg = stderr_data.decode("utf-8", errors="replace").strip()
                    yield AgentEvent(
                        event_type="error",
                        agent_type=AgentType.CODEX,
                        content=f"❌ Codex gặp lỗi (Code {process.returncode}):\n{err_msg or 'Tiến trình kết thúc bất thường.'}",
                    )
                elif agent_messages:
                    duration = time.time() - start_time
                    yield AgentEvent(
                        event_type="result",
                        agent_type=AgentType.CODEX,
                        content="\n\n".join(agent_messages),
                        conversation_id=session.conversation_id,
                        duration_seconds=duration,
                        tokens_used=0,
                    )

        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.kill()
            yield AgentEvent(
                event_type="error",
                agent_type=AgentType.CODEX,
                content="🛑 Tác vụ Codex đã bị hủy theo yêu cầu.",
            )
        except Exception as e:
            logger.exception("Exception in Codex execution")
            yield AgentEvent(
                event_type="error",
                agent_type=AgentType.CODEX,
                content=f"❌ Lỗi hệ thống khi gọi Codex: {str(e)}",
            )
        finally:
            session.current_process = None
