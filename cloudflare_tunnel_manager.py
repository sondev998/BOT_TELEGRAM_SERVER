import asyncio
import logging
import os
import re
import shutil
import time
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


class TunnelState:
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class CloudflareTunnelManager:
    """Quản lý vòng đời tiến trình Cloudflare Tunnel (cloudflared)."""

    def __init__(self):
        self.state: str = TunnelState.IDLE
        self.public_url: Optional[str] = None
        self.port: Optional[int] = None
        self.process: Optional[asyncio.subprocess.Process] = None
        self.started_at: Optional[float] = None
        self.error_message: str = ""
        self._monitor_task: Optional[asyncio.Task] = None

    @classmethod
    def get_cloudflared_path(cls) -> Optional[str]:
        """Tự động tìm kiếm vị trí thực thi của cloudflared."""
        if hasattr(Config, "CLOUDFLARED_PATH") and Config.CLOUDFLARED_PATH:
            if os.path.exists(Config.CLOUDFLARED_PATH):
                return Config.CLOUDFLARED_PATH

        candidates = [
            r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
            r"C:\Program Files\cloudflared\cloudflared.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\cloudflared\cloudflared.exe"),
            os.path.expandvars(r"%APPDATA%\cloudflared\cloudflared.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c

        which_cf = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
        if which_cf:
            return which_cf

        return None

    def get_status(self) -> str:
        return self.state

    def get_public_url(self) -> Optional[str]:
        return self.public_url

    async def start(
        self,
        port: int,
        mode: str = "quick",
        tunnel_name: str = "",
        hostname: str = "",
        timeout_seconds: int = 30,
    ) -> tuple[bool, str]:
        """Khởi động Cloudflare Tunnel trỏ tới port preview."""
        if self.state == TunnelState.RUNNING and self.public_url:
            logger.info(f"[Cloudflare] Tunnel already running at {self.public_url}")
            return True, self.public_url

        cf_path = self.get_cloudflared_path()
        if not cf_path:
            self.state = TunnelState.ERROR
            self.error_message = (
                "Không tìm thấy cloudflared.exe trên hệ thống! Vui lòng cài đặt Cloudflare Tunnel."
            )
            logger.error(f"[Cloudflare] ERROR: {self.error_message}")
            return False, self.error_message

        self.state = TunnelState.STARTING
        self.port = port
        self.public_url = None
        self.error_message = ""
        logger.info(f"[Cloudflare] Starting tunnel for port {port} using {cf_path}...")

        # Xây dựng lệnh gọi cloudflared
        if mode == "named" and tunnel_name:
            cmd = [cf_path, "tunnel", "run", tunnel_name]
        else:
            # Quick Tunnel (trycloudflare.com)
            cmd = [
                cf_path,
                "tunnel",
                "--url",
                f"http://127.0.0.1:{port}",
                "--no-autoupdate",
            ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL,
            )
            self.process = process
            self.started_at = time.time()

            # Lắng nghe stdout/stderr để bắt URL
            found_url = None
            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            start_wait = time.time()

            while time.time() - start_wait < timeout_seconds:
                if process.returncode is not None:
                    break

                try:
                    line_bytes = await asyncio.wait_for(
                        process.stdout.readline(), timeout=1.5
                    )
                except asyncio.TimeoutError:
                    continue

                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line:
                    logger.debug(f"[Cloudflare] {line}")

                if mode == "named" and hostname:
                    found_url = (
                        f"https://{hostname}"
                        if not hostname.startswith("http")
                        else hostname
                    )
                    break

                match = url_pattern.search(line)
                if match:
                    found_url = match.group(0)
                    break

            if found_url:
                self.public_url = found_url
                self.state = TunnelState.RUNNING
                logger.info(f"[Cloudflare] Public URL: {self.public_url}")

                # Khởi động background monitor để phát hiện khi tunnel chết
                self._start_monitor()
                return True, found_url
            else:
                self.state = TunnelState.ERROR
                self.error_message = "Không nhận được public URL từ Cloudflare Tunnel sau thời gian chờ."
                logger.error(f"[Cloudflare] ERROR: {self.error_message}")
                await self.stop()
                return False, self.error_message

        except Exception as e:
            self.state = TunnelState.ERROR
            self.error_message = f"Lỗi khởi động Cloudflare Tunnel: {e}"
            logger.exception("[Cloudflare] Exception during tunnel start")
            await self.stop()
            return False, self.error_message

    def _start_monitor(self):
        """Giám sát tiến trình tunnel trong nền."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()

        async def _monitor():
            try:
                if self.process:
                    await self.process.wait()
                    if self.state == TunnelState.RUNNING:
                        logger.warning(
                            f"[Cloudflare] Tunnel process exited unexpectedly with code {self.process.returncode}"
                        )
                        self.state = TunnelState.ERROR
                        self.public_url = None
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[Cloudflare] Monitor error: {e}")

        self._monitor_task = asyncio.create_task(_monitor())

    async def stop(self) -> bool:
        """Dừng Cloudflare Tunnel an toàn."""
        self.state = TunnelState.STOPPING
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()

        if self.process:
            try:
                if self.process.returncode is None:
                    self.process.terminate()
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        self.process.kill()
                logger.info("[Cloudflare] Tunnel stopped successfully.")
            except Exception as e:
                logger.error(f"[Cloudflare] Error stopping tunnel process: {e}")
            finally:
                self.process = None

        self.state = TunnelState.IDLE
        self.public_url = None
        self.port = None
        return True


# Singleton instance
cloudflare_mgr = CloudflareTunnelManager()
