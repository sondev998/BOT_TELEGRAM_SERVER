import asyncio
import logging
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from cocos_detector import cocos_detector
from config import Config

logger = logging.getLogger("CocosBuilder")


class CocosBuilder:
    """
    Tự động hóa Build & Đóng gói Game Cocos Creator (2.x / 3.x) qua Command Line Interface (CLI).
    Hỗ trợ xuất bản Web-Mobile, Web-Desktop, nén file Zip và tạo đường dẫn tải về.
    """

    SUPPORTED_PLATFORMS = {
        "web-mobile": "📱 Web Mobile (HTML5)",
        "web-desktop": "💻 Web Desktop (HTML5)",
        "android": "🤖 Android APK",
        "ios": "🍏 iOS Xcode",
    }

    def __init__(self):
        self._build_processes: dict[str, asyncio.subprocess.Process] = {}
        self._is_building: dict[str, bool] = {}

    def is_building(self, workspace_path: str) -> bool:
        """Kiểm tra xem dự án tại workspace này có đang trong tiến trình build không."""
        return self._is_building.get(workspace_path, False)

    async def build_project(
        self,
        workspace_path: str,
        platform: str = "web-mobile",
        debug: bool = False,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> tuple[bool, str, Optional[str], Optional[str]]:
        """
        Thực thi đóng gói dự án Cocos Creator.
        
        Trả về: (thành_công, thông_báo, đường_dẫn_file_zip, nội_dung_log)
        """
        ws = str(Path(workspace_path).resolve())
        if self.is_building(ws):
            return False, "⏳ Dự án này đang trong quá trình build dở. Vui lòng đợi hoàn tất.", None, None

        info = cocos_detector.detect_project(ws)
        if not info.is_cocos:
            return False, f"❌ Thư mục không phải là dự án Cocos Creator: `{ws}`", None, None

        if not info.executable_path or not os.path.exists(info.executable_path):
            return False, f"❌ Không tìm thấy trình thực thi `CocosCreator.exe` phù hợp cho phiên bản `{info.engine_version}`.", None, None

        self._is_building[ws] = True
        start_time = time.time()
        exe_path = info.executable_path

        # Chuẩn bị tham số build CLI
        if info.major_version == 3:
            # Cocos Creator 3.x CLI parameters
            # Cú pháp: CocosCreator.exe --project <path> --build "platform=web-mobile;debug=false"
            build_params = f"platform={platform};debug={'true' if debug else 'false'}"
            cmd = [
                exe_path,
                "--project",
                ws,
                "--build",
                build_params,
            ]
        else:
            # Cocos Creator 2.x CLI parameters
            # Cú pháp: CocosCreator.exe --path <path> --build "platform=web-mobile;debug=false"
            build_params = f"platform={platform};debug={'true' if debug else 'false'}"
            cmd = [
                exe_path,
                "--path",
                ws,
                "--build",
                build_params,
            ]

        if status_callback:
            status_callback(f"🚀 Bắt đầu build `{info.project_name}` ({platform}) bằng Cocos Creator {info.engine_version}...")

        log_lines: list[str] = []
        process = None

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=ws,
            )
            self._build_processes[ws] = process

            # Đọc log đầu ra
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                log_lines.append(decoded)
                
                # Cập nhật tiến trình qua callback
                if status_callback:
                    if "Build successfully" in decoded or "Building" in decoded or "Compile" in decoded:
                        status_callback(f"📦 {decoded[:100]}")

            await process.wait()
            return_code = process.returncode
            duration = time.time() - start_time
            full_log = "\n".join(log_lines)

            # Kiểm tra kết quả build
            build_dir = Path(ws) / "build" / platform
            if not build_dir.exists():
                # Thử tìm các thư mục build con (ví dụ Cocos 3.x: build/web-mobile)
                alt_build = Path(ws) / "build"
                if alt_build.exists():
                    subdirs = [d for d in alt_build.iterdir() if d.is_dir()]
                    if subdirs:
                        build_dir = subdirs[0]

            # Kiểm tra xem có file index.html hoặc sản phẩm build không
            has_index = (build_dir / "index.html").exists() or (build_dir / "main.js").exists() or (build_dir / "assets").exists()

            if return_code == 0 or has_index:
                # Nén thư mục build thành file ZIP
                zip_name = f"{info.project_name}_{platform}_{int(time.time())}.zip"
                zip_path = Path(ws) / "build" / zip_name
                
                try:
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for root, _, files in os.walk(build_dir):
                            for file in files:
                                file_path = Path(root) / file
                                if file_path == zip_path:
                                    continue
                                arcname = file_path.relative_to(build_dir)
                                zf.write(file_path, arcname)
                    
                    zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
                    summary = (
                        f"✅ **BUILD GAME THÀNH CÔNG!**\n\n"
                        f"📂 **Dự án:** `{info.project_name}`\n"
                        f"🛠️ **Engine:** `Cocos Creator {info.engine_version}`\n"
                        f"📱 **Platform:** `{platform}`\n"
                        f"⏱️ **Thời gian:** `{duration:.1f}s`\n"
                        f"📦 **File Zip:** `{zip_name}` (`{zip_size_mb:.2f} MB`)\n"
                        f"📁 **Thư mục:** `{build_dir}`"
                    )
                    return True, summary, str(zip_path), full_log
                except Exception as ze:
                    logger.exception(f"Lỗi khi nén file zip: {ze}")
                    summary = (
                        f"✅ **BUILD GAME THÀNH CÔNG (Không nén được Zip: {ze})**\n\n"
                        f"📂 Thư mục build: `{build_dir}`\n"
                        f"⏱️ Thời gian: `{duration:.1f}s`"
                    )
                    return True, summary, None, full_log
            else:
                error_snippet = "\n".join(log_lines[-20:]) if log_lines else "Không có log chi tiết."
                summary = (
                    f"❌ **BUILD GAME THẤT BẠI (Mã thoát: {return_code})**\n\n"
                    f"📂 **Dự án:** `{info.project_name}`\n"
                    f"🛠️ **Engine:** `Cocos Creator {info.engine_version}`\n"
                    f"⏱️ **Thời gian:** `{duration:.1f}s`\n\n"
                    f"⚠️ **Trích xuất lỗi:**\n```\n{error_snippet[:800]}\n```"
                )
                return False, summary, None, full_log

        except Exception as e:
            logger.exception("Build execution error")
            return False, f"❌ Lỗi ngoại lệ trong quá trình build: {e}", None, "\n".join(log_lines)
        finally:
            self._is_building[ws] = False
            self._build_processes.pop(ws, None)

    def cancel_build(self, workspace_path: str) -> bool:
        """Hủy tiến trình build đang chạy."""
        ws = str(Path(workspace_path).resolve())
        proc = self._build_processes.get(ws)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                self._is_building[ws] = False
                return True
            except Exception:
                pass
        return False


# Singleton instance
cocos_builder = CocosBuilder()
