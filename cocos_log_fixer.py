import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CocosIssue:
    issue_id: str
    workspace_path: str
    title: str
    error_log: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    created_at: float = field(default_factory=time.time)


class CocosLogFixer:
    """
    Trích xuất và quản lý lỗi Runtime / Compiler / Build của Cocos Creator,
    đồng thời tạo Prompt tối ưu để AI Agent tự động sửa lỗi và kiểm thử.
    """

    def __init__(self):
        self._issues: dict[str, CocosIssue] = {}

    def register_issue(
        self,
        workspace_path: str,
        title: str,
        error_log: str,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
    ) -> str:
        """Đăng ký một lỗi mới vào bộ nhớ và trả về issue_id."""
        issue_id = uuid.uuid4().hex[:8]

        # Tự động parse file và line number từ log nếu chưa có
        if not file_path or not line_number:
            detected_file, detected_line = self._parse_stack_trace(error_log)
            if detected_file:
                file_path = file_path or detected_file
                line_number = line_number or detected_line

        issue = CocosIssue(
            issue_id=issue_id,
            workspace_path=workspace_path,
            title=title,
            error_log=error_log,
            file_path=file_path,
            line_number=line_number,
        )
        self._issues[issue_id] = issue
        return issue_id

    def get_issue(self, issue_id: str) -> Optional[CocosIssue]:
        """Lấy thông tin lỗi theo issue_id."""
        return self._issues.get(issue_id)

    def _parse_stack_trace(self, log_text: str) -> tuple[Optional[str], Optional[int]]:
        """Phân tích nội dung log để tìm file và dòng gây lỗi."""
        # 1. Pattern TypeScript compiler: assets/scripts/Player.ts(42,15): error TS2339...
        ts_match = re.search(r"([\w\\/\.\-_]+\.ts)\((\d+),\d+\)", log_text)
        if ts_match:
            return ts_match.group(1), int(ts_match.group(2))

        # 2. Pattern JavaScript / Node stack: at Object.foo (assets/scripts/Game.js:50:12)
        js_match = re.search(r"at .*?\((.*?\.([tj]s)):(\d+):\d+\)", log_text)
        if js_match:
            return js_match.group(1), int(js_match.group(3))

        # 3. Pattern Cocos direct log: [ERROR] (assets/scripts/Test.ts:25)
        cocos_match = re.search(r"\(([\w\\/\.\-_]+\.([tj]s)):(\d+)\)", log_text)
        if cocos_match:
            return cocos_match.group(1), int(cocos_match.group(3))

        return None, None

    def generate_fix_prompt(self, issue_id: str) -> Optional[str]:
        """Tạo Prompt tự động sửa lỗi cho AI Agent."""
        issue = self.get_issue(issue_id)
        if not issue:
            return None

        file_hint = f"📂 Tệp tin nghi vấn: `{issue.file_path}` (Dòng: {issue.line_number})" if issue.file_path else ""

        prompt = (
            f"🛠️ **YÊU CẦU SỬA LỖI DỰ ÁN COCOS CREATOR**\n\n"
            f"**Tên lỗi:** {issue.title}\n"
            f"{file_hint}\n\n"
            f"**Chi tiết Stack Trace / Log lỗi:**\n"
            f"```\n{issue.error_log[:2000]}\n```\n\n"
            f"👉 **Nhiệm vụ của bạn:**\n"
            f"1. Kiểm tra nguyên nhân gây lỗi trong dự án tại thư mục hiện tại.\n"
            f"2. Nếu có chỉ định tệp nguồn ({issue.file_path or 'liên quan'}), hãy đọc tệp và chỉnh sửa sửa chữa triệt để lỗi.\n"
            f"3. Đảm bảo tuân thủ cú pháp TypeScript của Cocos Creator và không làm hỏng các logic xung quanh."
        )
        return prompt


# Singleton instance
cocos_log_fixer = CocosLogFixer()
