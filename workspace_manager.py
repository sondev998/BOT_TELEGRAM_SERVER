import json
import os
from pathlib import Path
from typing import Optional
from config import Config


class WorkspaceManager:
    """Quản lý các workspace dự án trên máy tính."""

    def __init__(self):
        self._user_workspaces: dict[int, str] = {}
        self._agy_settings_path = Path(
            os.path.expandvars(r"%USERPROFILE%\.gemini\antigravity-cli\settings.json")
        )
        self._codex_config_path = Path(
            os.path.expanduser("~/.codex/config.toml")
        )

    def get_known_workspaces(self) -> list[str]:
        """Đọc danh sách các workspace đã được cấu hình từ Antigravity và Codex."""
        workspaces: list[str] = []
        seen_lower: set[str] = set()

        def add_workspace(path_str: str, insert_first: bool = False):
            try:
                clean_p = str(Path(path_str.strip()).resolve())
                if clean_p.lower() not in seen_lower and os.path.isdir(clean_p):
                    seen_lower.add(clean_p.lower())
                    if insert_first:
                        workspaces.insert(0, clean_p)
                    else:
                        workspaces.append(clean_p)
            except Exception:
                pass

        # 1. Thêm workspace mặc định
        if Config.DEFAULT_WORKSPACE:
            add_workspace(Config.DEFAULT_WORKSPACE)

        # 2. Đọc từ Antigravity settings.json
        try:
            if self._agy_settings_path.exists():
                with open(self._agy_settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    trusted = data.get("trustedWorkspaces", [])
                    for p in trusted:
                        add_workspace(p)
        except Exception:
            pass

        # 3. Đọc từ OpenAI Codex config.toml
        try:
            if self._codex_config_path.exists():
                try:
                    import tomllib

                    with open(self._codex_config_path, "rb") as f:
                        data = tomllib.load(f)
                        projects = data.get("projects", {})
                        for p in projects.keys():
                            add_workspace(p)
                except Exception:
                    pass
        except Exception:
            pass

        return workspaces

    def get_current_workspace(self, user_id: int) -> str:
        """Lấy thư mục làm việc hiện tại của user."""
        ws = self._user_workspaces.get(user_id)
        if ws and os.path.isdir(ws):
            return ws
        # Trả về default workspace
        default_ws = Config.DEFAULT_WORKSPACE
        if default_ws and os.path.isdir(default_ws):
            return str(Path(default_ws).resolve())
        return str(Path.cwd())

    def set_workspace(self, user_id: int, path: str) -> tuple[bool, str]:
        """Chuyển đổi thư mục làm việc cho user."""
        clean_path = os.path.abspath(path.strip().strip('"').strip("'"))
        if not os.path.exists(clean_path):
            return False, f"❌ Đường dẫn không tồn tại:\n`{clean_path}`"
        if not os.path.isdir(clean_path):
            return False, f"❌ Đường dẫn không phải là thư mục:\n`{clean_path}`"

        self._user_workspaces[user_id] = clean_path
        return True, clean_path

    def list_files(self, workspace_path: str, subpath: str = "") -> tuple[bool, str]:
        """Liệt kê danh sách file/thư mục."""
        target_dir = Path(workspace_path) / subpath
        target_dir = target_dir.resolve()

        if not target_dir.exists():
            return False, "❌ Thư mục không tồn tại."
        if not target_dir.is_dir():
            return False, "❌ Đường dẫn không phải là thư mục."

        try:
            items = list(target_dir.iterdir())
            # Sắp xếp thư mục lên trước, sau đó tới file
            items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))

            lines = [f"📂 **Thư mục:** `{target_dir}`\n"]
            if not items:
                lines.append("*(Thư mục trống)*")
            else:
                for item in items[:40]:  # Giới hạn 40 mục
                    if item.is_dir():
                        lines.append(f"📁 `{item.name}/`")
                    else:
                        size_kb = item.stat().st_size / 1024
                        if size_kb > 1024:
                            size_str = f"{size_kb / 1024:.1f} MB"
                        else:
                            size_str = f"{size_kb:.1f} KB"
                        lines.append(f"📄 `{item.name}` ({size_str})")

                if len(items) > 40:
                    lines.append(f"\n*... và {len(items) - 40} mục khác.*")

            return True, "\n".join(lines)
        except Exception as e:
            return False, f"❌ Lỗi khi đọc thư mục: {e}"

    def read_file(self, workspace_path: str, filepath: str, max_chars: int = 3500) -> tuple[bool, str]:
        """Đọc nội dung của một file trong workspace."""
        target_file = Path(workspace_path) / filepath
        target_file = target_file.resolve()

        if not target_file.exists():
            return False, f"❌ File không tồn tại: `{filepath}`"
        if not target_file.is_file():
            return False, f"❌ `{filepath}` không phải là file."

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars + 100)

            truncated = False
            if len(content) > max_chars:
                content = content[:max_chars]
                truncated = True

            ext = target_file.suffix.lstrip(".")
            res = f"📄 **File:** `{target_file.name}`\n\n```{ext}\n{content}\n```"
            if truncated:
                res += "\n\n⚠️ *(File quá dài, đã rút gọn hiển thị)*"
            return True, res
        except Exception as e:
            return False, f"❌ Lỗi khi đọc file: {e}"


# Singleton instance
workspace_mgr = WorkspaceManager()
