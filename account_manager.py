import base64
import ctypes
import ctypes.wintypes
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
    """Quản lý và trích xuất thông tin tài khoản Antigravity & OpenAI Codex."""

    def __init__(self):
        self._cache: dict[str, tuple[float, AccountInfo]] = {}
        self._cache_ttl = 60  # Cache 60 giây

    def get_antigravity_account(self) -> AccountInfo:
        """Lấy thông tin tài khoản Google Antigravity hiện tại từ Windows Credential Manager."""
        now = time.time()
        if "antigravity" in self._cache:
            ts, cached = self._cache["antigravity"]
            if now - ts < self._cache_ttl:
                return cached

        info = AccountInfo(agent_name="Google Antigravity")
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
            # 1 = CRED_TYPE_GENERIC
            res = advapi32.CredReadW("gemini:antigravity", 1, 0, ctypes.byref(pcred))
            if res:
                cred = pcred.contents
                blob = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
                data = json.loads(blob.decode("utf-8"))
                tok = data.get("token", {})
                auth_method = data.get("auth_method", "consumer")
                acc_tok = tok.get("access_token", "")

                info.is_logged_in = True
                info.auth_mode = f"Google OAuth ({auth_method})"
                info.plan_type = "Google AI Studio / Consumer" if auth_method == "consumer" else auth_method.capitalize()

                # Gọi UserInfo API để lấy Email và Name
                if acc_tok:
                    try:
                        req = urllib.request.Request(
                            "https://www.googleapis.com/oauth2/v3/userinfo",
                            headers={"Authorization": f"Bearer {acc_tok}"},
                        )
                        with urllib.request.urlopen(req, timeout=3.5) as resp:
                            uinfo = json.loads(resp.read().decode("utf-8"))
                            info.email = uinfo.get("email", info.email)
                            info.name = uinfo.get("name", "")
                    except Exception as e:
                        logger.debug(f"Could not fetch google userinfo: {e}")
        except Exception as e:
            logger.debug(f"Error reading antigravity credentials: {e}")

        self._cache["antigravity"] = (now, info)
        return info

    def get_codex_account(self) -> AccountInfo:
        """Lấy thông tin tài khoản OpenAI Codex từ ~/.codex/auth.json."""
        now = time.time()
        if "codex" in self._cache:
            ts, cached = self._cache["codex"]
            if now - ts < self._cache_ttl:
                return cached

        info = AccountInfo(agent_name="OpenAI Codex")
        auth_file = Path(os.path.expanduser("~/.codex/auth.json"))

        try:
            if auth_file.exists():
                with open(auth_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                auth_mode = data.get("auth_mode", "chatgpt")
                tokens = data.get("tokens", {})
                id_token = tokens.get("id_token", "")

                info.is_logged_in = True
                info.auth_mode = auth_mode.upper() if auth_mode else "ChatGPT"

                if id_token and "." in id_token:
                    parts = id_token.split(".")
                    if len(parts) > 1:
                        payload_raw = base64.urlsafe_b64decode(parts[1] + "===")
                        payload = json.loads(payload_raw.decode("utf-8", errors="replace"))

                        info.email = payload.get("email", info.email)
                        info.name = payload.get("name", "")

                        openai_auth = payload.get("https://api.openai.com/auth", {})
                        plan_type = openai_auth.get("chatgpt_plan_type", "free")
                        info.plan_type = plan_type.upper()  # FREE, PLUS, PRO, TEAM, ENTERPRISE
                elif data.get("OPENAI_API_KEY"):
                    info.plan_type = "API Key"
                    info.email = "API Key Authentication"
        except Exception as e:
            logger.debug(f"Error reading codex auth.json: {e}")

        self._cache["codex"] = (now, info)
        return info

    def get_all_accounts_summary(self) -> str:
        """Tạo đoạn văn bản tổng kết thông tin tài khoản của cả 2 Engine."""
        agy_acc = self.get_antigravity_account()
        codex_acc = self.get_codex_account()

        agy_status = "🟢 Đã đăng nhập" if agy_acc.is_logged_in else "🔴 Chưa đăng nhập"
        codex_status = "🟢 Đã đăng nhập" if codex_acc.is_logged_in else "🔴 Chưa đăng nhập"

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
            f"• **Đổi tài khoản Antigravity:** Mở Antigravity IDE hoặc xóa phiên xác thực cũ để đăng nhập lại."
        )
        return msg


# Singleton instance
account_mgr = AccountManager()
