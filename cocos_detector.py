import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class CocosProjectInfo:
    is_cocos: bool = False
    project_path: str = ""
    project_name: str = ""
    engine_version: str = "Unknown"
    major_version: int = 2  # 2 hoặc 3
    executable_path: Optional[str] = None
    details: dict = None


class CocosCreatorDetector:
    """Tự động nhận diện cấu trúc dự án Cocos Creator (2.x / 3.x) và vị trí cài đặt Engine."""

    DEFAULT_EDITORS_DIR = Path(r"C:\ProgramData\cocos\editors\Creator")

    @classmethod
    def get_installed_editors(cls) -> dict[str, str]:
        """
        Tìm tất cả phiên bản Cocos Creator đã cài đặt trên máy.
        Trả về dict dạng: {"2.4.4": "C:\\ProgramData\\cocos\\editors\\Creator\\2.4.4\\CocosCreator.exe", ...}
        """
        installed: dict[str, str] = {}

        # 1. Quét thư mục chuẩn ProgramData\cocos\editors\Creator
        if cls.DEFAULT_EDITORS_DIR.exists():
            try:
                for ver_dir in cls.DEFAULT_EDITORS_DIR.iterdir():
                    if ver_dir.is_dir():
                        exe_file = ver_dir / "CocosCreator.exe"
                        if exe_file.exists():
                            installed[ver_dir.name] = str(exe_file.resolve())
            except Exception as e:
                logger.debug(f"Error scanning Cocos editors directory: {e}")

        # 2. Quét các đường dẫn cấu hình trong .env nếu có
        if hasattr(Config, "COCOS_CREATOR_2X_PATH") and Config.COCOS_CREATOR_2X_PATH:
            if os.path.exists(Config.COCOS_CREATOR_2X_PATH):
                installed["2.x_custom"] = Config.COCOS_CREATOR_2X_PATH
        if hasattr(Config, "COCOS_CREATOR_3X_PATH") and Config.COCOS_CREATOR_3X_PATH:
            if os.path.exists(Config.COCOS_CREATOR_3X_PATH):
                installed["3.x_custom"] = Config.COCOS_CREATOR_3X_PATH
        if hasattr(Config, "COCOS_CREATOR_PATH") and Config.COCOS_CREATOR_PATH:
            if os.path.exists(Config.COCOS_CREATOR_PATH):
                installed["custom"] = Config.COCOS_CREATOR_PATH

        return installed

    @classmethod
    def detect_project(cls, project_dir: str) -> CocosProjectInfo:
        """Kiểm tra và bóc tách thông tin Cocos Creator từ thư mục dự án."""
        pdir = Path(project_dir).resolve()
        info = CocosProjectInfo(project_path=str(pdir), project_name=pdir.name)

        if not pdir.exists() or not pdir.is_dir():
            return info

        # Các dấu hiệu nhận biết dự án Cocos Creator:
        # - Có project.json (2.x và một số 3.x)
        # - Có thư mục assets + settings (hoặc assets + packages)
        # - Có file creator.d.ts hoặc tsconfig.json chứa creator
        project_json_file = pdir / "project.json"
        assets_dir = pdir / "assets"
        settings_dir = pdir / "settings"
        package_json_file = pdir / "package.json"

        is_cocos = False
        version_str = ""
        project_name = pdir.name

        # Kiểm tra project.json
        if project_json_file.exists():
            try:
                with open(project_json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    is_cocos = True
                    version_str = data.get("version", "")
                    project_name = data.get("name", project_name)
            except Exception:
                is_cocos = True

        # Kiểm tra assets + settings
        if assets_dir.exists() and assets_dir.is_dir():
            if settings_dir.exists() or (pdir / "creator.d.ts").exists():
                is_cocos = True

        if not is_cocos:
            return info

        info.is_cocos = True
        info.project_name = project_name

        # Xác định Version
        if not version_str and package_json_file.exists():
            try:
                with open(package_json_file, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)
                    version_str = pkg_data.get("creator", {}).get("version", "")
                    if not version_str:
                        version_str = pkg_data.get("version", "")
            except Exception:
                pass

        if not version_str:
            # Đoán dựa vào cấu trúc: Cocos 3.x có settings/builder.json hoặc extensions
            if (settings_dir / "builder.json").exists() or (pdir / "native").exists():
                version_str = "3.x"
            else:
                version_str = "2.x"

        info.engine_version = version_str

        # Xác định Major version (2 hoặc 3)
        if version_str.startswith("3") or "3." in version_str:
            info.major_version = 3
        else:
            info.major_version = 2

        # Tìm executable phù hợp nhất
        installed_editors = cls.get_installed_editors()
        matched_exe = None

        # 1. Tìm chính xác phiên bản (ví dụ "2.4.4")
        if version_str in installed_editors:
            matched_exe = installed_editors[version_str]
        elif f"{info.major_version}.x_custom" in installed_editors:
            matched_exe = installed_editors[f"{info.major_version}.x_custom"]
        elif "custom" in installed_editors:
            matched_exe = installed_editors["custom"]
        else:
            # 2. Tìm phiên bản gần nhất cùng major (2.x hoặc 3.x)
            candidates = [
                v for v in installed_editors.keys() if v.startswith(str(info.major_version))
            ]
            if candidates:
                candidates.sort(reverse=True)  # Ưu tiên bản mới nhất
                matched_exe = installed_editors[candidates[0]]
            elif installed_editors:
                # Lấy bất kỳ bản nào có sẵn
                first_key = list(installed_editors.keys())[0]
                matched_exe = installed_editors[first_key]

        info.executable_path = matched_exe
        return info


# Singleton instance
cocos_detector = CocosCreatorDetector()
