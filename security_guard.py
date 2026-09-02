import logging
import re
from typing import Optional

logger = logging.getLogger("SecurityGuard")


class SecurityGuard:
    """
    Hệ thống kiểm soát và chặn các lệnh nguy hiểm (Command Guard & Safety Firewall).
    Ngăn chặn tuyệt đối các hành vi phá hoại hệ thống:
    - Format ổ đĩa, diskpart, xóa phân vùng
    - Xóa đệ quy toàn bộ ổ đĩa, thư mục Windows/System32
    - Tắt máy, khởi động lại, làm crash hệ điều hành
    - Sửa đổi Registry hệ thống (HKLM)
    - Tải và thực thi script độc hại từ xa (iex / irm downloadstring)
    - Tắt Windows Defender hoặc tạo user Admin trái phép
    """

    # Danh sách các quy tắc phát hiện lệnh nguy hiểm (Regex Rules)
    DANGEROUS_PATTERNS: list[tuple[str, str, str]] = [
        # 1. Format ổ đĩa & Phân vùng
        (
            r"\bformat\s+([a-zA-Z]:|/fs:)",
            "Format ổ đĩa",
            "Cấm lệnh Format ổ đĩa (Format [Drive]:)",
        ),
        (
            r"\b(format-volume|initialize-disk|clear-disk|remove-partition)\b",
            "PowerShell Disk Manipulation",
            "Cấm lệnh PowerShell định dạng hoặc xóa cấu trúc ổ đĩa",
        ),
        (
            r"\bdiskpart\b",
            "DiskPart Utility",
            "Cấm tiện ích phân vùng ổ đĩa DiskPart",
        ),
        (
            r"\bvssadmin\s+delete\s+shadows\b",
            "Delete Shadow Copies",
            "Cấm lệnh xóa bản sao lưu hệ thống Shadow Copies",
        ),
        (
            r"\b(bcdedit|bootrec)\b",
            "Boot Configuration",
            "Cấm lệnh can thiệp cấu hình khởi động Boot BCD",
        ),

        # 2. Xóa đệ quy toàn bộ ổ đĩa hoặc file hệ thống
        (
            r"\b(rmdir|rd)\s+.*\/s",
            "Mass Directory Deletion (rd /s)",
            "Cấm lệnh xóa đệ quy toàn bộ cây thư mục gốc qua cmd",
        ),
        (
            r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f\s+([a-zA-Z]:[\\/]?$|[\\/]$|\*|\.\.)",
            "Recursive Force Delete Root (rm -rf /)",
            "Cấm lệnh xóa đệ quy toàn bộ ổ đĩa gốc (rm -rf)",
        ),
        (
            r"\bremove-item\s+.*-(recurse|force).*[a-zA-Z]:[\\/]?$",
            "PowerShell Wipe Drive",
            "Cấm lệnh PowerShell xóa sạch toàn bộ ổ đĩa",
        ),
        (
            r"\bdel\s+.*\/f\s+.*\/s\s+.*[a-zA-Z]:\\",
            "Mass File Deletion",
            "Cấm lệnh xóa hàng loạt toàn bộ file trên ổ đĩa",
        ),
        (
            r"\b(del|rmdir|rd|remove-item)\s+.*[c-z]:\\windows",
            "Windows Directory Deletion",
            "Cấm hành vi xóa thư mục hệ điều hành C:\\Windows",
        ),
        (
            r"\b(takeown|icacls)\s+.*[c-z]:\\windows",
            "Windows Permissions Hijack",
            "Cấm lệnh chiếm quyền kiểm soát thư mục Windows",
        ),

        # 3. Can thiệp Registry hệ thống (HKLM)
        (
            r"\breg\s+delete\s+(hklm|hkcr|hkey_local_machine)",
            "Registry Delete HKLM",
            "Cấm lệnh xóa Registry nhánh hệ thống HKLM",
        ),
        (
            r"\bremove-item(property)?\s+.*(hklm:|hkcr:)",
            "PowerShell Registry Deletion",
            "Cấm lệnh PowerShell xóa Registry hệ thống",
        ),

        # 4. Tắt máy, Khởi động lại hoặc Crash OS
        (
            r"\bshutdown\s+(\/s|\/r|-s|-r)",
            "Shutdown / Restart OS",
            "Cấm lệnh tắt máy hoặc khởi động lại PC từ xa",
        ),
        (
            r"\b(stop-computer|restart-computer)\b",
            "PowerShell Shutdown/Restart",
            "Cấm lệnh PowerShell tắt hoặc khởi động lại máy tính",
        ),
        (
            r"\b(taskkill|stop-process)\s+.*(svchost|csrss|winlogon|smss|lsass|services)\b",
            "Critical Process Kill",
            "Cấm tắt các tiến trình lõi hệ thống Windows (gây sập máy BSOD)",
        ),

        # 5. Thực thi mã độc tải từ xa (IEX / Remote Script Injection)
        (
            r"\b(iex|invoke-expression)\s*\(.*(downloadstring|net\.webclient|iwr|curl)",
            "Remote Script Execution Pipe",
            "Cấm lệnh tải và thực thi script ẩn danh từ Internet qua pipe IEX",
        ),
        (
            r"\b(irm|iwr|curl)\s+.*\|\s*(iex|powershell|cmd)\b",
            "Piped Remote Script",
            "Cấm lệnh chuyển tiếp script từ web vào trình thông dịch",
        ),

        # 6. Leo thang đặc quyền & Tắt Antivirus
        (
            r"\bnet\s+user\s+.*\/add\b",
            "Unauthorized User Creation",
            "Cấm lệnh tự tạo tài khoản người dùng Windows mới",
        ),
        (
            r"\bnet\s+localgroup\s+administrators\s+.*\/add\b",
            "Admin Privilege Escalation",
            "Cấm lệnh tự thêm tài khoản vào nhóm Administrators",
        ),
        (
            r"\bset-mppreference\s+.*-disablerealtimemonitoring\s+\$true\b",
            "Disable Windows Defender",
            "Cấm lệnh tắt tính năng bảo vệ thời gian thực của Windows Defender",
        ),
    ]

    @classmethod
    def is_command_safe(cls, command: str) -> tuple[bool, str]:
        """
        Kiểm tra tính an toàn của lệnh trước khi cho phép thực thi.
        Trả về: (is_safe, error_message_if_unsafe)
        """
        if not command or not command.strip():
            return True, ""

        # Chuẩn hóa chuỗi lệnh: viết thường, loại bỏ khoảng trắng thừa
        cmd_normalized = " ".join(command.strip().lower().split())

        for pattern, rule_name, rule_desc in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, cmd_normalized, re.IGNORECASE):
                logger.warning(
                    f"⛔ [SECURITY ALERT] Blocked dangerous command: '{command}' | Rule: {rule_name}"
                )
                error_msg = (
                    f"⛔ **LỆNH BỊ CHẶN VÌ LÝ DO AN TOÀN:**\n\n"
                    f"• **Lý do:** {rule_desc}\n"
                    f"• **Quy tắc vi phạm:** `{rule_name}`\n"
                    f"• **Lệnh đã thử:** `{command}`\n\n"
                    f"🛡️ *Hệ thống tự động từ chối để bảo vệ máy tính và dữ liệu ổ đĩa của bạn.*"
                )
                return False, error_msg

        return True, ""


# Singleton instance
security_guard = SecurityGuard()
