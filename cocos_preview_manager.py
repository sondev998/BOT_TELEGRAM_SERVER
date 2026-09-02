import asyncio
import logging
import os
import socket
import time
import urllib.request
from typing import Callable, Optional

from cloudflare_tunnel_manager import CloudflareTunnelManager, TunnelState, cloudflare_mgr
from cocos_detector import CocosCreatorDetector, CocosProjectInfo, cocos_detector
from config import Config

logger = logging.getLogger(__name__)


class CocosPreviewState:
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class CocosPreviewManager:
    """Điều khiển và quản lý vòng đời Cocos Creator Preview & Cloudflare Tunnel."""

    DEFAULT_PORTS = [7456, 7457, 7458, 8080, 3000]

    def __init__(self):
        self.state: str = CocosPreviewState.IDLE
        self.project_info: Optional[CocosProjectInfo] = None
        self.port: Optional[int] = None
        self.local_url: Optional[str] = None
        self.public_url: Optional[str] = None
        self.preview_process: Optional[asyncio.subprocess.Process] = None
        self.started_at: Optional[float] = None
        self.error_message: str = ""
        self._is_external_process: bool = False
        self._lock = asyncio.Lock()

    def get_status_data(self) -> dict:
        """Lấy toàn bộ trạng thái hiện tại dưới dạng dictionary."""
        uptime_str = "00:00:00"
        if self.started_at and self.state == CocosPreviewState.RUNNING:
            uptime_sec = int(time.time() - self.started_at)
            hours, rem = divmod(uptime_sec, 3600)
            mins, secs = divmod(rem, 60)
            uptime_str = f"{hours:02d}:{mins:02d}:{secs:02d}"

        return {
            "status": self.state,
            "project_path": self.project_info.project_path if self.project_info else "",
            "project_name": self.project_info.project_name if self.project_info else "Chưa chọn",
            "cocos_version": self.project_info.engine_version if self.project_info else "Unknown",
            "major_version": self.project_info.major_version if self.project_info else 2,
            "port": self.port or 7456,
            "local_url": self.local_url or "",
            "public_url": self.public_url or "",
            "uptime": uptime_str,
            "started_at": self.started_at,
            "error_message": self.error_message,
            "is_external": self._is_external_process,
        }

    def _is_port_open(self, port: int, host: str = "127.0.0.1") -> bool:
        """Kiểm tra xem port có đang lắng nghe không."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.6)
                res = s.connect_ex((host, port))
                return res == 0
        except Exception:
            return False

    def _health_check_http(self, port: int) -> bool:
        """Kiểm tra HTTP GET tới preview server."""
        try:
            url = f"http://127.0.0.1:{port}/"
            req = urllib.request.Request(url, headers={"User-Agent": "CocosPreviewBot/1.0"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status in (200, 301, 302, 304)
        except Exception:
            # Nếu port đang open nhưng trả về dữ liệu socket
            return self._is_port_open(port)

    def detect_active_preview_port(self) -> Optional[int]:
        """Tự động dò tìm port preview Cocos đang hoạt động."""
        for p in self.DEFAULT_PORTS:
            if self._health_check_http(p):
                return p
        return None

    async def start_preview(
        self,
        workspace_path: str,
        status_callback: Optional[Callable[[str], None]] = None,
        timeout_seconds: int = 60,
    ) -> tuple[bool, str]:
        """
        Khởi động Cocos Creator Preview cho project và mở Cloudflare Tunnel.
        """
        async with self._lock:
            # 1. Nếu đang chạy cùng project và tunnel vẫn sống
            if (
                self.state == CocosPreviewState.RUNNING
                and self.public_url
                and self.project_info
                and os.path.abspath(self.project_info.project_path) == os.path.abspath(workspace_path)
            ):
                if self.port and self._is_port_open(self.port):
                    return True, self.public_url

            self.state = CocosPreviewState.STARTING
            self.error_message = ""
            self.started_at = None

            if status_callback:
                status_callback("🔍 Đang phân tích cấu trúc dự án Cocos Creator...")

            # 2. Nhận diện dự án
            info = cocos_detector.detect_project(workspace_path)
            self.project_info = info

            if not info.is_cocos:
                self.state = CocosPreviewState.ERROR
                self.error_message = f"Thư mục `{os.path.basename(workspace_path)}` không phải là dự án Cocos Creator hợp lệ."
                logger.error(f"[Cocos] {self.error_message}")
                return False, self.error_message

            logger.info(
                f"[Cocos] Detected Cocos Project: {info.project_name} (Version: {info.engine_version}, Major: {info.major_version})"
            )

            # 3. Kiểm tra xem Preview Server đã chạy sẵn trên máy chưa
            detected_port = self.detect_active_preview_port()
            if detected_port:
                logger.info(f"[Cocos] Found active Preview Server on port {detected_port}")
                self.port = detected_port
                self._is_external_process = True
            else:
                # Cần khởi động Cocos Creator Editor
                if not info.executable_path or not os.path.exists(info.executable_path):
                    self.state = CocosPreviewState.ERROR
                    self.error_message = (
                        f"Không tìm thấy Cocos Creator Engine ({info.engine_version}) trên máy tính!\n"
                        f"Vui lòng cài đặt Cocos Creator hoặc cấu hình đường dẫn trong file `.env`."
                    )
                    logger.error(f"[Cocos] ERROR: {self.error_message}")
                    return False, self.error_message

                if status_callback:
                    status_callback(
                        f"🚀 Đang khởi động Cocos Creator {info.engine_version}..."
                    )

                logger.info(f"[Cocos] Starting Cocos Creator from {info.executable_path}...")

                # Chuẩn bị tham số dòng lệnh phù hợp với version 2.x hoặc 3.x
                if info.major_version == 3:
                    cmd = [info.executable_path, "--project", workspace_path]
                else:
                    cmd = [info.executable_path, "--path", workspace_path]

                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                        stdin=asyncio.subprocess.DEVNULL,
                    )
                    self.preview_process = proc
                    self._is_external_process = False
                except Exception as e:
                    self.state = CocosPreviewState.ERROR
                    self.error_message = f"Không thể khởi động Cocos Creator: {e}"
                    logger.exception("[Cocos] Failed to spawn Cocos Creator")
                    return False, self.error_message

                # 4. Đợi preview server mở port
                if status_callback:
                    status_callback("⏳ Đang đợi Cocos Preview Server khởi động (Port 7456)...")

                start_wait = time.time()
                found_port = None
                while time.time() - start_wait < timeout_seconds:
                    found_port = self.detect_active_preview_port()
                    if found_port:
                        break
                    await asyncio.sleep(1.5)

                if not found_port:
                    self.state = CocosPreviewState.ERROR
                    self.error_message = f"Cocos Creator không mở cổng preview sau {timeout_seconds}s chờ đợi."
                    logger.error(f"[Cocos] ERROR: {self.error_message}")
                    return False, self.error_message

                self.port = found_port
                logger.info(f"[Cocos] Preview ready on port {self.port}")

            self.local_url = f"http://127.0.0.1:{self.port}"

            # 5. Khởi động Cloudflare Tunnel
            if status_callback:
                status_callback("🌐 Đang thiết lập Cloudflare Tunnel bảo mật...")

            tunnel_mode = getattr(Config, "CLOUDFLARE_MODE", "quick")
            tunnel_name = getattr(Config, "CLOUDFLARE_TUNNEL_NAME", "")
            hostname = getattr(Config, "CLOUDFLARE_HOSTNAME", "")

            success, tunnel_res = await cloudflare_mgr.start(
                port=self.port,
                mode=tunnel_mode,
                tunnel_name=tunnel_name,
                hostname=hostname,
            )

            if not success:
                self.state = CocosPreviewState.ERROR
                self.error_message = f"Lỗi tạo Cloudflare Tunnel: {tunnel_res}"
                logger.error(f"[Cocos] ERROR: {self.error_message}")
                return False, self.error_message

            self.public_url = tunnel_res
            self.state = CocosPreviewState.RUNNING
            self.started_at = time.time()

            logger.info(
                f"[Preview] Cocos Preview is RUNNING!\n"
                f"  Project: {self.project_info.project_name}\n"
                f"  Local: {self.local_url}\n"
                f"  Public: {self.public_url}"
            )
            return True, self.public_url

    async def stop_preview(self) -> tuple[bool, str]:
        """Dừng Cloudflare Tunnel và tiến trình Cocos Preview nếu do bot khởi tạo."""
        async with self._lock:
            self.state = CocosPreviewState.STOPPING
            logger.info("[Cocos] Stopping Preview and Tunnel...")

            # 1. Dừng Cloudflare Tunnel
            await cloudflare_mgr.stop()

            # 2. Dừng Cocos Creator Process nếu do bot khởi tạo
            if self.preview_process and not self._is_external_process:
                try:
                    if self.preview_process.returncode is None:
                        self.preview_process.terminate()
                        try:
                            await asyncio.wait_for(self.preview_process.wait(), timeout=3.0)
                        except asyncio.TimeoutError:
                            self.preview_process.kill()
                    logger.info("[Cocos] Cocos Creator process terminated.")
                except Exception as e:
                    logger.error(f"[Cocos] Error stopping Cocos process: {e}")
                finally:
                    self.preview_process = None

            self.state = CocosPreviewState.IDLE
            self.port = None
            self.local_url = None
            self.public_url = None
            self.started_at = None
            self._is_external_process = False

            return True, "✅ Đã dừng Cocos Preview và Cloudflare Tunnel thành công."

    async def restart_preview(
        self,
        workspace_path: str,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> tuple[bool, str]:
        """Khởi động lại Preview và Tunnel."""
        await self.stop_preview()
        return await self.start_preview(workspace_path, status_callback)


# Singleton instance
cocos_preview_mgr = CocosPreviewManager()
