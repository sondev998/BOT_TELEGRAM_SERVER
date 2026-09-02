import argparse
import hashlib
import json
import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from config import Config

# Đảm bảo xuất UTF-8 an toàn trên Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logger = logging.getLogger("AuthManager")


class Permission(str, Enum):
    """Danh sách quyền hạn trong hệ thống Local Controller."""
    READ_STATUS = "READ_STATUS"
    READ_WORKSPACE = "READ_WORKSPACE"
    RUN_AI_AGENT = "RUN_AI_AGENT"
    START_COCOS = "START_COCOS"
    STOP_COCOS = "STOP_COCOS"
    EXECUTE_SHELL = "EXECUTE_SHELL"
    SCREENSHOT = "SCREENSHOT"
    FULL_ADMIN = "FULL_ADMIN"


@dataclass
class AuthSession:
    """Phiên xác thực của một người dùng Telegram (chỉ lưu trong bộ nhớ RAM)."""
    user_id: int
    authenticated: bool = False
    authenticated_at: Optional[float] = None
    last_activity_at: float = field(default_factory=time.time)
    failed_attempts: int = 0
    locked_until: float = 0.0
    awaiting_pin: bool = False
    permissions: set[Permission] = field(default_factory=lambda: {Permission.FULL_ADMIN})


class SecurityEventType(str, Enum):
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILED = "AUTH_FAILED"
    AUTH_LOCKED = "AUTH_LOCKED"
    AUTH_LOGOUT = "AUTH_LOGOUT"
    UNAUTHORIZED_USER = "UNAUTHORIZED_USER"
    UNAUTHORIZED_COMMAND = "UNAUTHORIZED_COMMAND"
    DANGEROUS_ACTION_REQUESTED = "DANGEROUS_ACTION_REQUESTED"
    DANGEROUS_ACTION_CONFIRMED = "DANGEROUS_ACTION_CONFIRMED"


class AuthManager:
    """
    Hệ thống Xác thực & Phân quyền đa lớp cho Local Controller.
    - Lớp 1: Telegram User ID Whitelist
    - Lớp 2: PIN Authentication (Mã hóa scrypt an toàn, chống Brute-force)
    - Lớp 3: Tự động khóa sau thời gian không hoạt động (Inactivity Auto-Lock, mặc định 30 phút)
    - Lớp 4: Role/Permission Authorization
    - Lớp 5: Security Logging & Rate Limiting
    """

    def __init__(self):
        # Lưu trữ phiên xác thực theo user_id trong RAM (mất khi restart server)
        self._sessions: dict[int, AuthSession] = {}
        self._pin_hash: Optional[str] = None
        self._init_pin_hash()

    def _init_pin_hash(self):
        """Khởi tạo mã hash của PIN từ cấu hình .env (scrypt)."""
        env_hash = os.getenv("AUTH_PIN_HASH", "").strip()
        env_pin = os.getenv("AUTH_PIN", "").strip()

        if env_hash and ":" in env_hash:
            self._pin_hash = env_hash
        elif env_pin:
            # Tự động băm PIN thành scrypt hash và xóa biến plaintext
            self._pin_hash = self.hash_pin(env_pin)
            os.environ.pop("AUTH_PIN", None)
        else:
            # PIN mặc định (123456) khi chưa cấu hình
            default_pin = "123456"
            self._pin_hash = self.hash_pin(default_pin)
            logger.warning(
                "⚠️ Chưa cấu hình AUTH_PIN_HASH trong .env! Đang sử dụng PIN mặc định (123456). "
                "Vui lòng chạy 'python auth_manager.py --set-pin <mã_pin>' để tạo hash bảo mật."
            )

    @classmethod
    def hash_pin(cls, pin: str) -> str:
        """Băm mã PIN bằng thuật toán scrypt bảo mật với salt ngẫu nhiên 16 bytes."""
        salt = secrets.token_bytes(16)
        key = hashlib.scrypt(
            pin.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            maxmem=33554432,
        )
        return f"{salt.hex()}:{key.hex()}"

    @classmethod
    def verify_pin_hash(cls, pin: str, stored_hash: str) -> bool:
        """Xác thực mã PIN với chuỗi hash scrypt đã lưu (bảo vệ chống timing attack)."""
        try:
            if not stored_hash or ":" not in stored_hash:
                return False
            salt_hex, key_hex = stored_hash.split(":", 1)
            salt = bytes.fromhex(salt_hex)
            expected_key = bytes.fromhex(key_hex)

            computed_key = hashlib.scrypt(
                pin.encode("utf-8"),
                salt=salt,
                n=16384,
                r=8,
                p=1,
                maxmem=33554432,
            )
            return secrets.compare_digest(computed_key, expected_key)
        except Exception as e:
            logger.error(f"Error during PIN verification: {e}")
            return False

    def get_session(self, user_id: int) -> AuthSession:
        """Lấy hoặc tạo phiên làm việc trong RAM cho user_id."""
        if user_id not in self._sessions:
            self._sessions[user_id] = AuthSession(user_id=user_id)
        return self._sessions[user_id]

    def update_activity(self, user_id: int):
        """Cập nhật mốc thời gian hoạt động mới nhất của user."""
        session = self.get_session(user_id)
        session.last_activity_at = time.time()

    def is_whitelisted(self, user_id: int) -> bool:
        """Kiểm tra xem User ID có nằm trong danh sách trắng (Whitelist) không."""
        return Config.is_user_allowed(user_id)

    def is_authenticated(self, user_id: int) -> bool:
        """Kiểm tra xem user đã mở khóa Controller chưa và kiểm tra tự động khóa khi không hoạt động."""
        if not self.is_whitelisted(user_id):
            return False
        session = self.get_session(user_id)
        if not session.authenticated:
            return False

        # Kiểm tra Inactivity Auto-Lock
        auto_lock_minutes = getattr(Config, "AUTH_AUTO_LOCK_MINUTES", 30)
        if auto_lock_minutes > 0:
            elapsed = time.time() - session.last_activity_at
            if elapsed > auto_lock_minutes * 60:
                session.authenticated = False
                session.authenticated_at = None
                self.log_security_event(
                    SecurityEventType.AUTH_LOCKED,
                    user_id,
                    f"Auto-locked after {auto_lock_minutes}m of inactivity",
                )
                return False

        return True

    def is_locked_out(self, user_id: int) -> tuple[bool, int]:
        """
        Kiểm tra xem user có đang bị tạm khóa do nhập sai PIN quá nhiều lần không.
        Trả về: (is_locked, remaining_seconds)
        """
        session = self.get_session(user_id)
        now = time.time()
        if session.locked_until > now:
            return True, int(session.locked_until - now)
        return False, 0

    def verify_pin(self, user_id: int, pin_candidate: str) -> tuple[bool, str]:
        """
        Xác thực mã PIN người dùng nhập vào.
        Trả về: (thành_công, thông_báo)
        """
        if not self.is_whitelisted(user_id):
            self.log_security_event(SecurityEventType.UNAUTHORIZED_USER, user_id, "Attempted PIN entry")
            return False, "❌ Bạn không có quyền truy cập hệ thống."

        session = self.get_session(user_id)

        # Kiểm tra rate limit
        is_locked, remaining = self.is_locked_out(user_id)
        if is_locked:
            self.log_security_event(SecurityEventType.AUTH_LOCKED, user_id, f"Blocked. Locked for {remaining}s")
            return False, f"🔒 Bạn đã nhập sai quá nhiều lần. Vui lòng đợi {remaining} giây trước khi thử lại."

        # Kiểm tra PIN
        max_attempts = getattr(Config, "AUTH_MAX_ATTEMPTS", 5)
        lockout_seconds = getattr(Config, "AUTH_LOCKOUT_SECONDS", 300)

        pin_clean = pin_candidate.strip()
        is_valid = self.verify_pin_hash(pin_clean, self._pin_hash)

        if is_valid:
            session.authenticated = True
            session.authenticated_at = time.time()
            session.last_activity_at = time.time()
            session.failed_attempts = 0
            session.locked_until = 0.0
            session.awaiting_pin = False
            self.log_security_event(SecurityEventType.AUTH_SUCCESS, user_id, "Successfully authenticated")
            return True, "🟢 Xác thực thành công! Bảng điều khiển đã được mở khóa."
        else:
            session.failed_attempts += 1
            remaining_attempts = max(0, max_attempts - session.failed_attempts)
            self.log_security_event(
                SecurityEventType.AUTH_FAILED,
                user_id,
                f"Failed attempt {session.failed_attempts}/{max_attempts}",
            )

            if session.failed_attempts >= max_attempts:
                session.locked_until = time.time() + lockout_seconds
                session.failed_attempts = 0
                self.log_security_event(
                    SecurityEventType.AUTH_LOCKED,
                    user_id,
                    f"Account temporarily locked for {lockout_seconds}s",
                )
                return (
                    False,
                    f"🔒 **BỊ TẠM KHÓA:** Bạn đã nhập sai PIN {max_attempts} lần liên tiếp.\n"
                    f"Hệ thống tạm khóa quyền nhập mã trong {lockout_seconds // 60} phút.",
                )

            return (
                False,
                f"❌ **Mã PIN không chính xác!**\n"
                f"Bạn còn `{remaining_attempts}` lần thử trước khi bị tạm khóa.",
            )

    def lock(self, user_id: int):
        """Khóa phiên điều khiển của người dùng."""
        session = self.get_session(user_id)
        session.authenticated = False
        session.authenticated_at = None
        session.awaiting_pin = False
        self.log_security_event(SecurityEventType.AUTH_LOGOUT, user_id, "Controller locked by user")

    def logout(self, user_id: int):
        """Đăng xuất hoàn toàn (tương đương Lock)."""
        self.lock(user_id)

    def set_awaiting_pin(self, user_id: int, status: bool = True):
        """Đặt trạng thái đang chờ người dùng nhập mã PIN."""
        session = self.get_session(user_id)
        session.awaiting_pin = status

    def is_awaiting_pin(self, user_id: int) -> bool:
        """Kiểm tra người dùng có đang trong trạng thái chờ nhập PIN không."""
        session = self.get_session(user_id)
        return session.awaiting_pin and not session.authenticated

    def authorize(self, user_id: int, required_permission: Optional[Permission] = None) -> tuple[bool, str]:
        """
        Middleware kiểm tra quyền hạn thực thi lệnh.
        Trả về: (được_phép, lý_do_từ_chối)
        """
        if not self.is_whitelisted(user_id):
            self.log_security_event(SecurityEventType.UNAUTHORIZED_USER, user_id, "Blocked at authorization")
            return False, "⛔ **BẠN CHƯA ĐƯỢC PHÂN QUYỀN TRUY CẬP**\nVui lòng liên hệ quản trị viên."

        session = self.get_session(user_id)
        if not self.is_authenticated(user_id):
            self.log_security_event(SecurityEventType.UNAUTHORIZED_COMMAND, user_id, "Blocked: Controller locked")
            return False, "🔒 **LOCAL CONTROLLER ĐANG BỊ KHÓA**\nVui lòng nhập mã PIN để mở khóa trước khi thực hiện lệnh này."

        # Cập nhật thời gian hoạt động
        session.last_activity_at = time.time()

        if required_permission and Permission.FULL_ADMIN not in session.permissions:
            if required_permission not in session.permissions:
                return False, "⛔ Bạn không có quyền thực hiện hành động này."

        return True, ""

    def log_security_event(self, event_type: SecurityEventType, user_id: int, details: str = ""):
        """Ghi nhật ký bảo mật (Tuyệt đối không ghi mã PIN hoặc bí mật vào log)."""
        logger.info(f"[SECURITY - {event_type.value}] User ID: {user_id} | {details}")


# Singleton instance
auth_mgr = AuthManager()


# CLI Helper để người dùng tự tạo hash PIN an toàn
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tạo chuỗi hash mã PIN bảo mật cho CocosDevBot")
    parser.add_argument("--set-pin", type=str, help="Mã PIN mới cần tạo hash")
    args = parser.parse_args()

    if args.set_pin:
        pin = args.set_pin.strip()
        if len(pin) < 4:
            print("❌ Mã PIN phải có ít nhất 4 ký tự!")
            sys.exit(1)
        hashed = AuthManager.hash_pin(pin)
        print("=" * 60)
        print("🔐 ĐÃ TẠO MÃ HASH SCRYPT THÀNH CÔNG:")
        print(f"AUTH_PIN_HASH={hashed}")
        print("=" * 60)
        print("👉 Hãy sao chép dòng trên và dán vào file .env trong thư mục bot.")
    else:
        parser.print_help()
