import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Tải cấu hình từ .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)


class Config:
    BASE_DIR: Path = BASE_DIR
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    # Danh sách User ID được phép truy cập
    _allowed_raw: str = os.getenv("ALLOWED_USER_IDS", "").strip()
    ALLOWED_USER_IDS: set[int] = set()
    if _allowed_raw:
        for uid in _allowed_raw.replace(";", ",").split(","):
            uid = uid.strip()
            if uid.isdigit():
                ALLOWED_USER_IDS.add(int(uid))

    # Workspace mặc định
    DEFAULT_WORKSPACE: str = os.getenv(
        "DEFAULT_WORKSPACE", str(BASE_DIR)
    ).strip()

    # Agent mặc định ("antigravity" hoặc "codex")
    DEFAULT_AGENT: str = os.getenv("DEFAULT_AGENT", "antigravity").strip().lower()

    # Cấu hình Antigravity CLI
    DEFAULT_ANTIGRAVITY_MODEL: str = os.getenv(
        "DEFAULT_MODEL", "Gemini 3.7 Flash (High)"
    ).strip()
    DEFAULT_MODEL: str = DEFAULT_ANTIGRAVITY_MODEL  # Giữ tương thích
    DEFAULT_EFFORT: str = os.getenv("DEFAULT_EFFORT", "high").strip()
    DEFAULT_MODE: str = os.getenv("DEFAULT_MODE", "accept-edits").strip()
    TASK_TIMEOUT: int = int(os.getenv("TASK_TIMEOUT", "600"))

    # Cấu hình OpenAI Codex CLI
    DEFAULT_CODEX_MODEL: str = os.getenv(
        "DEFAULT_CODEX_MODEL", "gpt-5.6-terra"
    ).strip()
    DEFAULT_CODEX_EFFORT: str = os.getenv("DEFAULT_CODEX_EFFORT", "medium").strip()

    # Cấu hình Cocos Creator Engine
    COCOS_CREATOR_PATH: str = os.getenv("COCOS_CREATOR_PATH", "").strip()
    COCOS_CREATOR_2X_PATH: str = os.getenv("COCOS_CREATOR_2X_PATH", "").strip()
    COCOS_CREATOR_3X_PATH: str = os.getenv("COCOS_CREATOR_3X_PATH", "").strip()
    DEFAULT_PREVIEW_PORT: int = int(os.getenv("DEFAULT_PREVIEW_PORT", "7456"))

    # Cấu hình Cloudflare Tunnel
    CLOUDFLARED_PATH: str = os.getenv("CLOUDFLARED_PATH", "").strip()
    CLOUDFLARE_MODE: str = os.getenv("CLOUDFLARE_MODE", "quick").strip().lower()
    CLOUDFLARE_TUNNEL_NAME: str = os.getenv("CLOUDFLARE_TUNNEL_NAME", "").strip()
    CLOUDFLARE_HOSTNAME: str = os.getenv("CLOUDFLARE_HOSTNAME", "").strip()

    # Tự động tìm đường dẫn agy.exe
    _agy_env = os.getenv("AGY_PATH", "").strip()
    if _agy_env and os.path.exists(_agy_env):
        AGY_PATH: str = _agy_env
    else:
        _which_agy = shutil.which("agy") or shutil.which("agy.exe")
        _appdata_agy = os.path.expandvars(r"%LOCALAPPDATA%\agy\bin\agy.exe")
        if _which_agy:
            AGY_PATH = _which_agy
        elif os.path.exists(_appdata_agy):
            AGY_PATH = _appdata_agy
        else:
            AGY_PATH = "agy"

    # Tự động tìm đường dẫn codex.cmd / codex.exe
    _codex_env = os.getenv("CODEX_PATH", "").strip()
    if _codex_env and os.path.exists(_codex_env):
        CODEX_PATH: str = _codex_env
    else:
        _which_codex = (
            shutil.which("codex.cmd")
            or shutil.which("codex.exe")
            or shutil.which("codex")
        )
        _npm_codex = os.path.expandvars(r"%APPDATA%\npm\codex.cmd")
        _appdata_codex = os.path.expandvars(
            r"%LOCALAPPDATA%\OpenAI\Codex\bin\codex.exe"
        )
        if _which_codex and os.path.exists(_which_codex):
            CODEX_PATH = _which_codex
        elif os.path.exists(_npm_codex):
            CODEX_PATH = _npm_codex
        elif os.path.exists(_appdata_codex):
            CODEX_PATH = _appdata_codex
        else:
            CODEX_PATH = "codex"

    # Tự động tìm cloudflared.exe nếu chưa có cấu hình
    if not CLOUDFLARED_PATH or not os.path.exists(CLOUDFLARED_PATH):
        _cf_candidates = [
            r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
            r"C:\Program Files\cloudflared\cloudflared.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\cloudflared\cloudflared.exe"),
            os.path.expandvars(r"%APPDATA%\cloudflared\cloudflared.exe"),
        ]
        for c in _cf_candidates:
            if os.path.exists(c):
                CLOUDFLARED_PATH = c
                break
        if not CLOUDFLARED_PATH:
            _which_cf = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
            if _which_cf:
                CLOUDFLARED_PATH = _which_cf

    @classmethod
    def reload(cls):
        """Tải lại file .env khi có thay đổi."""
        load_dotenv(BASE_DIR / ".env", override=True)
        cls.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        cls._allowed_raw = os.getenv("ALLOWED_USER_IDS", "").strip()
        cls.ALLOWED_USER_IDS = set()
        if cls._allowed_raw:
            for uid in cls._allowed_raw.replace(";", ",").split(","):
                uid = uid.strip()
                if uid.isdigit():
                    cls.ALLOWED_USER_IDS.add(int(uid))
        cls.DEFAULT_WORKSPACE = os.getenv(
            "DEFAULT_WORKSPACE", str(BASE_DIR)
        ).strip()
        cls.DEFAULT_AGENT = os.getenv("DEFAULT_AGENT", "antigravity").strip().lower()
        cls.DEFAULT_ANTIGRAVITY_MODEL = os.getenv(
            "DEFAULT_MODEL", "Gemini 3.7 Flash (High)"
        ).strip()
        cls.DEFAULT_MODEL = cls.DEFAULT_ANTIGRAVITY_MODEL
        cls.DEFAULT_CODEX_MODEL = os.getenv(
            "DEFAULT_CODEX_MODEL", "gpt-5.6-terra"
        ).strip()
        cls.DEFAULT_EFFORT = os.getenv("DEFAULT_EFFORT", "high").strip()
        cls.DEFAULT_MODE = os.getenv("DEFAULT_MODE", "accept-edits").strip()
        cls.COCOS_CREATOR_PATH = os.getenv("COCOS_CREATOR_PATH", "").strip()
        cls.COCOS_CREATOR_2X_PATH = os.getenv("COCOS_CREATOR_2X_PATH", "").strip()
        cls.COCOS_CREATOR_3X_PATH = os.getenv("COCOS_CREATOR_3X_PATH", "").strip()
        cls.CLOUDFLARED_PATH = os.getenv("CLOUDFLARED_PATH", "").strip()
        cls.CLOUDFLARE_MODE = os.getenv("CLOUDFLARE_MODE", "quick").strip().lower()
        cls.CLOUDFLARE_TUNNEL_NAME = os.getenv("CLOUDFLARE_TUNNEL_NAME", "").strip()
        cls.CLOUDFLARE_HOSTNAME = os.getenv("CLOUDFLARE_HOSTNAME", "").strip()

    @classmethod
    def is_user_allowed(cls, user_id: int) -> bool:
        """Kiểm tra quyền truy cập của người dùng."""
        if not cls.ALLOWED_USER_IDS:
            return False
        return user_id in cls.ALLOWED_USER_IDS
