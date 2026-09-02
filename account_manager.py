import base64
import ctypes
import ctypes.wintypes
import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class AccountInfo:
    agent_name: str
    email: str = "Chưa đăng nhập / Không rõ"
    name: str = ""
    plan_type: str = "Tiêu chuẩn"
    auth_mode: str = "OAuth"
    is_logged_in: bool = False
    details: dict = None


class AccountManager:
    """Quản lý và trích xuất thông tin tài khoản Antigravity & OpenAI Codex với cơ chế đa lớp dự phòng (Multi-tier fallback)."""

    def __init__(self):
        self._cache_file = Config.BASE_DIR / ".account_cache.json"
        self._memory_cache: dict[str, tuple[float, AccountInfo]] = {}
        self._memory_cache_ttl = 30  # Giây

    def _load_persistent_cache(self) -> dict:
        """Đọc bộ nhớ cache lưu trên ổ đĩa."""
        try:
            if self._cache_file.exists():
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_persistent_cache(self, key: str, info: AccountInfo):
        """Lưu thông tin tài khoản hợp lệ vào ổ đĩa để tái sử dụng khi token tạm thời hết hạn."""
        if not info.is_logged_in or info.email == "Chưa đăng nhập / Không rõ":
            return
        try:
            data = self._load_persistent_cache()
            data[key] = {
                "email": info.email,
                "name": info.name,
                "plan_type": info.plan_type,
                "auth_mode": info.auth_mode,
                "saved_at": time.time(),
            }
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_antigravity_account(self) -> AccountInfo:
        """
        Lấy thông tin tài khoản Google Antigravity với 4 tầng dự phòng:
        1. Memory Cache
        2. Windows Credential Manager (gemini:antigravity) + Google UserInfo API
        3. Parse từ log Antigravity CLI (~/.gemini/antigravity-cli/cli.log)
        4. Persistent Cache file (.account_cache.json)
        """
        now = time.time()
        if "antigravity" in self._memory_cache:
            ts, cached = self._memory_cache["antigravity"]
            if now - ts < self._memory_cache_ttl and cached.is_logged_in:
                return cached

        info = AccountInfo(agent_name="Google Antigravity")
        found_email = ""
        found_name = ""
        found_method = "Google OAuth (consumer)"

        # Tầng 1: Đọc từ Windows Credential Manager
        try:
            advapi32 = ctypes.windll.advapi32

            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ("Flags", ctypes.wintypes.DWORD),
                    ("Type", ctypes.wintypes.DWORD),
                    ("TargetName", ctypes.wintypes.LPWSTR),
                    ("Comment", ctypes.wintypes.LPWSTR),
                    ("LastWritten", ctypes.wintypes.FILETIME),
                    ("CredentialBlobSize", ctypes.wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", ctypes.wintypes.DWORD),
                    ("AttributeCount", ctypes.wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", ctypes.wintypes.LPWSTR),
                    ("UserName", ctypes.wintypes.LPWSTR),
                ]

            pcred = ctypes.POINTER(CREDENTIAL)()
            res = advapi32.CredReadW("gemini:antigravity", 1, 0, ctypes.byref(pcred))
            if res:
                cred = pcred.contents
                blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
                data = json.loads(blob.decode("utf-8"))
                tok = data.get("token", {})
                auth_method = data.get("auth_method", "consumer")
                found_method = f"Google OAuth ({auth_method})"
                info.is_logged_in = True
                info.plan_type = "Google AI Studio / Consumer"

                acc_tok = tok.get("access_token", "")
                if acc_tok:
                    try:
                        req = urllib.request.Request(
                            "https://www.googleapis.com/oauth2/v3/userinfo",
                            headers={"Authorization": f"Bearer {acc_tok}"},
                        )
                        with urllib.request.urlopen(req, timeout=2.0) as resp:
                            uinfo = json.loads(resp.read().decode("utf-8"))
                            found_email = uinfo.get("email", "")
                            found_name = uinfo.get("name", "")
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"[AccountMgr] CredReadW failed: {e}")

        # Tầng 2: Nếu chưa lấy được email qua API, đọc từ cli.log của Antigravity
        if not found_email:
            cli_log_path = Path(
                os.path.expandvars(r"%USERPROFILE%\.gemini\antigravity-cli\cli.log")
            )
            if cli_log_path.exists():
                try:
                    with open(cli_log_path, "r", encoding="utf-8", errors="ignore") as f:
                        log_content = f.read()
                    matches = re.findall(
                        r"email=([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
                        log_content,
                    )
                    if matches:
                        found_email = matches[-1]
                        info.is_logged_in = True
                except Exception:
                    pass

        # Tầng 3: Đọc từ Persistent Cache file
        if not found_email:
            persisted = self._load_persistent_cache().get("antigravity", {})
            if persisted.get("email"):
                found_email = persisted["email"]
                found_name = persisted.get("name", "")
                info.is_logged_in = True

        if found_email:
            info.email = found_email
            info.name = found_name
            info.auth_mode = found_method
            info.is_logged_in = True
            self._save_persistent_cache("antigravity", info)

        self._memory_cache["antigravity"] = (now, info)
        return info

    def get_codex_account(self) -> AccountInfo:
        """Lấy thông tin tài khoản OpenAI Codex từ ~/.codex/auth.json hoặc persistent cache."""
        now = time.time()
        if "codex" in self._memory_cache:
            ts, cached = self._memory_cache["codex"]
            if now - ts < self._memory_cache_ttl and cached.is_logged_in:
                return cached

        info = AccountInfo(agent_name="OpenAI Codex")
        auth_file = Path(os.path.expanduser("~/.codex/auth.json"))

        found_email = ""
        found_name = ""
        found_plan = "FREE"
        found_mode = "ChatGPT"

        try:
            if auth_file.exists():
                with open(auth_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                auth_mode = data.get("auth_mode", "chatgpt")
                tokens = data.get("tokens", {})
                id_token = tokens.get("id_token", "")

                info.is_logged_in = True
                found_mode = auth_mode.upper() if auth_mode else "ChatGPT"

                if id_token and "." in id_token:
                    parts = id_token.split(".")
                    if len(parts) > 1:
                        payload_raw = base64.urlsafe_b64decode(parts[1] + "===")
                        payload = json.loads(
                            payload_raw.decode("utf-8", errors="replace")
                        )

                        found_email = payload.get("email", "")
                        found_name = payload.get("name", "")

                        openai_auth = payload.get(
                            "https://api.openai.com/auth", {}
                        )
                        found_plan = openai_auth.get(
                            "chatgpt_plan_type", "free"
                        ).upper()
                elif data.get("OPENAI_API_KEY"):
                    found_plan = "API Key"
                    found_email = "API Key Authentication"
        except Exception as e:
            logger.debug(f"[AccountMgr] Error reading codex auth.json: {e}")

        # Dự phòng persistent cache
        if not found_email:
            persisted = self._load_persistent_cache().get("codex", {})
            if persisted.get("email"):
                found_email = persisted["email"]
                found_name = persisted.get("name", "")
                found_plan = persisted.get("plan_type", "FREE")
                info.is_logged_in = True

        if found_email:
            info.email = found_email
            info.name = found_name
            info.plan_type = found_plan
            info.auth_mode = found_mode
            info.is_logged_in = True
            self._save_persistent_cache("codex", info)

        self._memory_cache["codex"] = (now, info)
        return info

    def get_all_accounts_summary(self) -> str:
        """Tạo đoạn văn bản tổng kết thông tin tài khoản của cả 2 Engine."""
        agy_acc = self.get_antigravity_account()
        codex_acc = self.get_codex_account()

        agy_status = (
            "🟢 Đã đăng nhập" if agy_acc.is_logged_in else "🔴 Chưa đăng nhập"
        )
        codex_status = (
            "🟢 Đã đăng nhập" if codex_acc.is_logged_in else "🔴 Chưa đăng nhập"
        )

        msg = (
            f"👤 **THÔNG TIN TÀI KHOẢN AI AGENT**\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🤖 **Google Antigravity:**\n"
            f"• Trạng thái: {agy_status}\n"
            f"• Email: `{agy_acc.email}`\n"
            f"• Chủ tài khoản: `{agy_acc.name or 'N/A'}`\n"
            f"• Gói tài khoản: `{agy_acc.plan_type}`\n"
            f"• Phương thức: `{agy_acc.auth_mode}`\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚡ **OpenAI Codex:**\n"
            f"• Trạng thái: {codex_status}\n"
            f"• Email: `{codex_acc.email}`\n"
            f"• Chủ tài khoản: `{codex_acc.name or 'N/A'}`\n"
            f"• Gói tài khoản: `{codex_acc.plan_type}`\n"
            f"• Phương thức: `{codex_acc.auth_mode}`\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 **Hướng dẫn đổi tài khoản:**\n"
            f"• **Đổi tài khoản Codex:** Mở Terminal gõ `codex logout` rồi `codex login`.\n"
            f"• **Đổi tài khoản Antigravity:** Mở Antigravity IDE hoặc xóa phiên xác thực cũ (`cmdkey /delete:gemini:antigravity`) để đăng nhập lại."
        )
        return msg


# Singleton instance
account_mgr = AccountManager()
