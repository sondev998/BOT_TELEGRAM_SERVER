import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("CocosPerfAnalyzer")


@dataclass
class PerfIssue:
    file_path: str
    line_number: int
    severity: str  # "HIGH", "MEDIUM", "LOW"
    category: str
    message: str
    snippet: str
    recommendation: str


@dataclass
class AuditReport:
    workspace_path: str
    scanned_files_count: int
    score: int  # 0 to 100
    issues: list[PerfIssue] = field(default_factory=list)


class CocosPerfAnalyzer:
    """
    Quét mã nguồn TypeScript / JavaScript của dự án Cocos Creator để phát hiện
    các lỗi phổ biến gây tụt khung hình (FPS Drop), rò rỉ bộ nhớ (Memory Leak) và GC Spikes.
    """

    # Các quy tắc kiểm tra Anti-pattern
    RULES = [
        {
            "id": "FIND_IN_UPDATE",
            "severity": "HIGH",
            "category": "⚡ Hiệu năng Update (FPS Drop)",
            "regex": r"(cc\.find|find|getChildByName|getChildByPath)\s*\(",
            "in_update_only": True,
            "message": "Gọi hàm tìm kiếm Node (`find` / `getChildByName`) liên tục trong hàm `update()`.",
            "recommendation": "Hãy lưu tham chiếu Node vào biến (`private playerNode: cc.Node = null`) tại `onLoad()` hoặc `start()` để tái sử dụng.",
        },
        {
            "id": "GET_COMPONENT_IN_UPDATE",
            "severity": "MEDIUM",
            "category": "⚡ Hiệu năng Update",
            "regex": r"getComponent\s*\(",
            "in_update_only": True,
            "message": "Gọi hàm `getComponent()` liên tục trong hàm `update()`.",
            "recommendation": "Hãy cache component vào biến thành viên tại `onLoad()` thay vì gọi lấy lại mỗi frame.",
        },
        {
            "id": "INSTANTIATE_IN_UPDATE",
            "severity": "HIGH",
            "category": "🗑️ Áp lực Garbage Collection (GC)",
            "regex": r"(cc\.instantiate|instantiate)\s*\(",
            "in_update_only": True,
            "message": "Khởi tạo đối tượng (`instantiate`) liên tục trong hàm `update()` mà không dùng Object Pool.",
            "recommendation": "Sử dụng `cc.NodePool` / `NodePool` để tái chế đối tượng (đạn, quái, hiệu ứng), tránh giật lag khi chơi lâu.",
        },
        {
            "id": "ALLOC_IN_UPDATE",
            "severity": "MEDIUM",
            "category": "🗑️ Áp lực Garbage Collection (GC)",
            "regex": r"new\s+(cc\.)?(Vec2|Vec3|Color|Rect)\s*\(",
            "in_update_only": True,
            "message": "Khởi tạo đối tượng Vector / Color mới (`new Vec2 / Vec3`) trong hàm `update()`.",
            "recommendation": "Sử dụng biến tạm dùng chung (`v2_temp.set(...)`) hoặc `cc.v2()` để tránh sinh rác bộ nhớ mỗi frame.",
        },
        {
            "id": "LOG_IN_UPDATE",
            "severity": "LOW",
            "category": "⚠️ Debug Logging",
            "regex": r"(console\.log|cc\.log|cc\.warn|log)\s*\(",
            "in_update_only": True,
            "message": "Để hàm ghi log (`console.log`) chạy mỗi frame trong `update()`.",
            "recommendation": "Xóa hoặc tắt log debug khi xuất bản game để tránh làm chậm vòng lặp render.",
        },
    ]

    @classmethod
    def audit_workspace(cls, workspace_path: str, max_files: int = 100) -> AuditReport:
        """Quét và phân tích toàn bộ file mã nguồn trong thư mục scripts của dự án."""
        ws = Path(workspace_path)
        assets_dir = ws / "assets"
        if not assets_dir.exists():
            assets_dir = ws

        report = AuditReport(workspace_path=str(ws), scanned_files_count=0, score=100)
        script_files = []

        for ext in ("*.ts", "*.js"):
            for f in assets_dir.rglob(ext):
                # Bỏ qua library, node_modules, temp, build, declaration files
                if any(p in f.parts for p in ("library", "node_modules", "temp", "build", "local")):
                    continue
                if f.name.endswith(".d.ts") or f.name.endswith(".meta"):
                    continue
                script_files.append(f)
                if len(script_files) >= max_files:
                    break

        report.scanned_files_count = len(script_files)
        total_deduction = 0

        for file_path in script_files:
            rel_path = str(file_path.relative_to(ws)).replace("\\", "/")
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as sf:
                    lines = sf.readlines()

                # Kiểm tra rò rỉ sự kiện: có node.on mà không có onDestroy hoặc node.off
                full_content = "".join(lines)
                has_on = "node.on(" in full_content or "systemEvent.on(" in full_content or "EventTarget.on(" in full_content
                has_off = "node.off(" in full_content or "targetOff(" in full_content or "onDestroy" in full_content

                if has_on and not has_off:
                    report.issues.append(
                        PerfIssue(
                            file_path=rel_path,
                            line_number=1,
                            severity="HIGH",
                            category="🛡️ Rò rỉ bộ nhớ (Event Leak)",
                            message="Tệp có lắng nghe sự kiện (`node.on`) nhưng không thấy hàm hủy (`node.off` hoặc `onDestroy`).",
                            snippet="node.on(...) without node.off",
                            recommendation="Bổ sung hàm `onDestroy()` và gọi `this.node.targetOff(this)` để tránh memory leak khi chuyển Scene.",
                        )
                    )
                    total_deduction += 10

                # Quét từng dòng tìm hàm update()
                in_update_block = False
                update_brace_depth = 0

                for idx, line in enumerate(lines, 1):
                    stripped = line.strip()

                    # Phát hiện bắt đầu hàm update
                    if re.search(r"\bupdate\s*\([^)]*\)\s*\{?", stripped):
                        in_update_block = True
                        update_brace_depth = stripped.count("{") - stripped.count("}")
                        continue

                    if in_update_block:
                        update_brace_depth += stripped.count("{") - stripped.count("}")
                        if update_brace_depth <= 0 and "}" in stripped:
                            in_update_block = False

                        # Kiểm tra các quy tắc trong update()
                        for rule in cls.RULES:
                            if re.search(rule["regex"], stripped):
                                severity_deduction = 10 if rule["severity"] == "HIGH" else (5 if rule["severity"] == "MEDIUM" else 2)
                                total_deduction += severity_deduction

                                report.issues.append(
                                    PerfIssue(
                                        file_path=rel_path,
                                        line_number=idx,
                                        severity=rule["severity"],
                                        category=rule["category"],
                                        message=rule["message"],
                                        snippet=stripped[:80],
                                        recommendation=rule["recommendation"],
                                    )
                                )

            except Exception as e:
                logger.debug(f"Error reading file {file_path}: {e}")

        # Tính điểm tối ưu (0 - 100)
        report.score = max(0, 100 - total_deduction)
        return report

    @classmethod
    def format_report_text(cls, report: AuditReport) -> str:
        """Tạo định dạng văn bản báo cáo thẩm định tối ưu mã nguồn cho Telegram."""
        score = report.score
        if score >= 90:
            score_badge = f"🟢 **{score}/100** (Tuyệt vời)"
        elif score >= 70:
            score_badge = f"🟡 **{score}/100** (Khá tốt - Cần cải thiện)"
        else:
            score_badge = f"🔴 **{score}/100** (Cần tối ưu ngay)"

        high_issues = [i for i in report.issues if i.severity == "HIGH"]
        med_issues = [i for i in report.issues if i.severity == "MEDIUM"]
        low_issues = [i for i in report.issues if i.severity == "LOW"]

        lines = [
            f"⚡ **BÁO CÁO THẨM ĐỊNH HIỆU NĂNG CODE COCOS**\n",
            f"📊 **Điểm tối ưu:** {score_badge}",
            f"📁 **Số tệp đã quét:** `{report.scanned_files_count}` tệp TypeScript/JavaScript",
            f"⚠️ **Tổng số cảnh báo:** `{len(report.issues)}` (🔴 `{len(high_issues)}` cao | 🟡 `{len(med_issues)}` vừa | 🟢 `{len(low_issues)}` nhẹ)",
            "━━━━━━━━━━━━━━━━━━\n",
        ]

        if not report.issues:
            lines.append("🎉 **Chúc mừng! Không phát hiện anti-pattern nghiêm trọng nào.** Mã nguồn của bạn rất sạch và tối ưu.")
            return "\n".join(lines)

        # Liệt kê tối đa 5 lỗi quan trọng nhất
        lines.append("🔍 **CÁC VẤN ĐỀ CẦN TỐI ƯU HÀNG ĐẦU:**\n")
        for idx, issue in enumerate(report.issues[:5], 1):
            sev_icon = "🔴" if issue.severity == "HIGH" else ("🟡" if issue.severity == "MEDIUM" else "🟢")
            lines.append(f"{idx}. {sev_icon} **{issue.category}**")
            lines.append(f"   📂 `{issue.file_path}` (Dòng {issue.line_number})")
            lines.append(f"   💬 `{issue.message}`")
            lines.append(f"   📝 `Code:` `{issue.snippet}`")
            lines.append(f"   💡 *Gợi ý:* {issue.recommendation}\n")

        if len(report.issues) > 5:
            lines.append(f"*(Còn `{len(report.issues) - 5}` cảnh báo khác... Bấm nút bên dưới để xem toàn bộ hoặc nhờ AI tối ưu)*")

        return "\n".join(lines)


# Singleton instance
cocos_perf_analyzer = CocosPerfAnalyzer()
