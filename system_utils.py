import asyncio
import io
import os
import platform
import subprocess
import time
from datetime import timedelta
import psutil
from PIL import ImageGrab

from account_manager import account_mgr
from security_guard import security_guard


class SystemUtils:
    """Công cụ theo dõi hệ thống máy tính và chạy lệnh an toàn."""

    START_TIME = time.time()

    @classmethod
    def get_system_status(
        cls,
        current_workspace: str = "",
        conversation_id: str = "",
        active_agent: str = "",
        model_name: str = "",
    ) -> str:
        """Lấy thông tin tổng quan về tài nguyên máy tính và agent hiện tại."""
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.2)
        cpu_count = psutil.cpu_count(logical=True)

        # RAM
        ram = psutil.virtual_memory()
        ram_used_gb = ram.used / (1024**3)
        ram_total_gb = ram.total / (1024**3)

        # Uptime
        uptime_sec = int(time.time() - cls.START_TIME)
        uptime_str = str(timedelta(seconds=uptime_sec))

        # Disks
        disk_lines = []
        for partition in psutil.disk_partitions():
            try:
                if "fixed" in partition.opts.lower() or "rw" in partition.opts.lower():
                    usage = psutil.disk_usage(partition.mountpoint)
                    free_gb = usage.free / (1024**3)
                    total_gb = usage.total / (1024**3)
                    disk_lines.append(
                        f"  💾 Ổ `{partition.device}`: {usage.percent}% (Trống {free_gb:.1f}/{total_gb:.1f} GB)"
                    )
            except Exception:
                continue

        disks_str = (
            "\n".join(disk_lines)
            if disk_lines
            else "  Không lấy được thông tin ổ đĩa"
        )

        # Thông tin tài khoản
        agy_acc = account_mgr.get_antigravity_account()
        codex_acc = account_mgr.get_codex_account()

        agent_info = f"🤖 **Agent Đang Dùng:** `{active_agent}`\n" if active_agent else ""
        model_info = f"🧠 **Model:** `{model_name}`\n" if model_name else ""

        status_text = (
            f"🖥️ **THÔNG TIN HỆ THỐNG PC & TÀI KHOẢN**\n\n"
            f"{agent_info}"
            f"{model_info}"
            f"👤 **Google Account:** `{agy_acc.email}` ({agy_acc.plan_type})\n"
            f"⚡ **Codex Account:** `{codex_acc.email}` (Gói {codex_acc.plan_type})\n\n"
            f"💻 **Hệ điều hành:** {platform.system()} {platform.release()} ({platform.machine()})\n"
            f"⏱️ **Bot Uptime:** `{uptime_str}`\n"
            f"⚡ **CPU ({cpu_count} cores):** `{cpu_percent}%`\n"
            f"🧠 **RAM:** `{ram_used_gb:.1f} / {ram_total_gb:.1f} GB` ({ram.percent}%)\n\n"
            f"💽 **Ổ đĩa:**\n{disks_str}\n\n"
            f"📂 **Workspace:**\n`{current_workspace or 'Mặc định'}`\n\n"
            f"💬 **Session ID:**\n`{conversation_id or 'Chưa có phiên (Sẽ tạo mới)'}`"
        )
        return status_text

    @classmethod
    def capture_screenshot(cls) -> tuple[bool, io.BytesIO | str]:
        """Chụp ảnh màn hình máy tính."""
        try:
            screenshot = ImageGrab.grab(all_screens=True)
            bio = io.BytesIO()
            bio.name = "desktop_screenshot.png"
            screenshot.save(bio, "PNG")
            bio.seek(0)
            return True, bio
        except Exception as e:
            return False, f"Không thể chụp ảnh màn hình: {e}"

    @classmethod
    async def run_shell_command(
        cls, command: str, cwd: str, timeout: int = 60
    ) -> tuple[int, str]:
        """
        Thực thi lệnh PowerShell trực tiếp trên máy sau khi đã qua màng lọc kiểm duyệt an toàn.
        """
        # 1. Kiểm tra an toàn trước khi thực thi
        is_safe, error_msg = security_guard.is_command_safe(command)
        if not is_safe:
            return -1, error_msg

        # 2. Thực thi lệnh nếu an toàn
        try:
            process = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
                output = stdout.decode("utf-8", errors="replace")
                return process.returncode or 0, output
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                return -1, f"❌ Lệnh đã vượt quá thời gian chờ ({timeout}s)."
        except Exception as e:
            return -1, f"❌ Lỗi thực thi lệnh: {e}"
