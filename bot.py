import asyncio
import atexit
import io
import logging
import os
import sys
import time
from pathlib import Path
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Conflict, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from account_manager import account_mgr
from agent_base import AgentType
from agent_manager import agent_mgr
from auth_manager import AuthManager, Permission, SecurityEventType, auth_mgr
from cocos_detector import cocos_detector
from cocos_preview_manager import CocosPreviewState, cocos_preview_mgr
from config import Config
from system_utils import SystemUtils
from workspace_manager import workspace_mgr

# Đảm bảo xuất UTF-8 an toàn trên Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Cấu hình logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("DualAgentTelegramBot")


# ==========================================
# AUTHENTICATION & SECURITY HELPERS
# ==========================================

async def send_unauthorized_msg(update: Update):
    """Thông báo khi người dùng chưa được cấp quyền trong Whitelist (Anti-enumeration: không tiết lộ cấu hình)."""
    text = (
        "⛔ **BẠN CHƯA ĐƯỢC PHÂN QUYỀN TRUY CẬP**\n\n"
        "Tài khoản của bạn không nằm trong danh sách được phép điều khiển máy chủ này.\n"
        "Vui lòng liên hệ quản trị viên để được cấp quyền."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.answer("⛔ Bạn chưa được phân quyền!", show_alert=True)


async def send_locked_msg(update: Update):
    """Thông báo khi Controller đang bị khóa và yêu cầu nhập mã PIN."""
    user = update.effective_user
    if user:
        auth_mgr.set_awaiting_pin(user.id, True)

    msg, reply_markup = build_locked_view()
    if update.message:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)


def build_locked_view() -> tuple[str, InlineKeyboardMarkup]:
    """Tạo giao diện khi Controller đang ở trạng thái LOCKED."""
    msg = (
        "🔒 **LOCAL CONTROLLER LOCKED**\n\n"
        "🔴 **Trạng thái:** `Đang bị khóa (Locked)`\n\n"
        "👉 *Vui lòng gõ mã PIN bảo mật và gửi trực tiếp vào tin nhắn chat để mở khóa.*"
    )
    keyboard = [
        [InlineKeyboardButton("🔐 Mở khóa (Nhập PIN)", callback_data="auth_unlock")],
        [InlineKeyboardButton("❓ Trợ giúp bảo mật", callback_data="auth_help")],
    ]
    return msg, InlineKeyboardMarkup(keyboard)


async def send_smart_message(bot, chat_id: int, text: str, reply_to_message_id: int = None):
    """
    Gửi tin nhắn thông minh: tự động chia nhỏ nếu quá dài,
    fall-back về plain text nếu lỗi cú pháp Markdown,
    và đính kèm file nếu nội dung quá lớn.
    """
    if not text:
        return

    # Nếu quá dài (> 10000 ký tự), gửi tệp đính kèm
    if len(text) > 10000:
        summary = text[:1500] + "\n\n... *(Nội dung quá dài, vui lòng xem chi tiết trong file đính kèm)*"
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=summary,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception:
            await bot.send_message(chat_id=chat_id, text=summary, reply_to_message_id=reply_to_message_id)

        file_data = io.BytesIO(text.encode("utf-8"))
        file_data.name = f"agent_output_{int(time.time())}.md"
        await bot.send_document(
            chat_id=chat_id,
            document=file_data,
            caption="📄 Toàn bộ nội dung phản hồi từ Agent",
        )
        return

    # Chia nhỏ tin nhắn nếu dài hơn 3800 ký tự
    max_chunk = 3800
    chunks = []
    if len(text) <= max_chunk:
        chunks.append(text)
    else:
        lines = text.splitlines(keepends=True)
        cur_chunk = ""
        for line in lines:
            if len(cur_chunk) + len(line) > max_chunk:
                chunks.append(cur_chunk)
                cur_chunk = line
            else:
                cur_chunk += line
        if cur_chunk:
            chunks.append(cur_chunk)

    for chunk in chunks:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply_to_message_id,
            )
        except BadRequest:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_to_message_id=reply_to_message_id,
            )


def build_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Tạo bàn phím menu chính khi đã xác thực."""
    keyboard = [
        [
            InlineKeyboardButton("📁 Chọn Workspace", callback_data="menu_workspace"),
            InlineKeyboardButton("⚙️ Cấu hình Model", callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("🎮 Cocos Preview", callback_data="cocos_preview"),
            InlineKeyboardButton("📊 Trạng thái PC", callback_data="menu_status"),
        ],
        [
            InlineKeyboardButton("🔀 Đổi Agent", callback_data="menu_agent"),
            InlineKeyboardButton("👤 Tài khoản AI", callback_data="menu_account"),
        ],
        [
            InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
            InlineKeyboardButton("🔄 Phiên chat mới", callback_data="menu_reset"),
        ],
        [
            InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu_help"),
            InlineKeyboardButton("🔒 Khóa Controller", callback_data="auth_lock"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_main_dashboard_text(user_id: int, user_first_name: str = "Bạn") -> str:
    """Tạo nội dung text cho Dashboard chính khi đã AUTHENTICATED."""
    ws = workspace_mgr.get_current_workspace(user_id)
    active_type = agent_mgr.get_active_agent_type(user_id)
    runner = agent_mgr.get_active_runner(user_id)
    session = agent_mgr.get_session(user_id, active_type)

    agent_badge = f"{runner.emoji} **{runner.display_name}**"
    session_id_display = session.conversation_id[:12] + "..." if session.conversation_id else "Chưa có (sẽ tạo mới)"

    # Lấy tài khoản tương ứng
    if active_type == AgentType.ANTIGRAVITY:
        acc = account_mgr.get_antigravity_account()
        acc_text = f"👤 **Google Account:** `{acc.email}`"
    else:
        acc = account_mgr.get_codex_account()
        acc_text = f"⚡ **Codex Account:** `{acc.email}` (Gói `{acc.plan_type}`)"

    # Kiểm tra trạng thái Cocos Preview
    cocos_st = cocos_preview_mgr.get_status_data()
    cocos_badge = "🟢 Đang chạy" if cocos_st["status"] == CocosPreviewState.RUNNING else "⚪ Tắt"

    msg = (
        f"🟢 **LOCAL CONTROLLER - AUTHENTICATED**\n\n"
        f"Chào mừng **{user_first_name}**! Bạn có quyền điều khiển toàn diện hệ thống PC.\n\n"
        f"🛠️ **Agent Đang Dùng:** {agent_badge}\n"
        f"{acc_text}\n"
        f"🎮 **Cocos Preview:** `{cocos_badge}`\n"
        f"📂 **Workspace:** `{ws}`\n"
        f"🧠 **Model:** `{session.model or 'Mặc định'}`\n"
        f"⚡ **Effort:** `{session.effort or 'Mặc định'}`\n"
        f"💬 **Session ID:** `{session_id_display}`\n\n"
        f"👇 **Chọn chức năng bên dưới:**"
    )
    return msg


def build_cocos_preview_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Tạo giao diện điều khiển Cocos Creator Preview."""
    ws = workspace_mgr.get_current_workspace(user_id)
    st = cocos_preview_mgr.get_status_data()
    info = cocos_detector.detect_project(ws)

    # 1. Trường hợp đang chạy (RUNNING)
    if st["status"] == CocosPreviewState.RUNNING and st["public_url"]:
        msg = (
            f"🎮 **COCOS CREATOR PREVIEW**\n\n"
            f"🟢 **Trạng thái:** `Đang chạy (Running)`\n"
            f"📂 **Dự án:** `{st['project_name']}`\n"
            f"🛠️ **Engine:** `Cocos Creator {st['cocos_version']}`\n"
            f"🔌 **Cổng Local:** `{st['local_url']}`\n"
            f"🌐 **Public HTTPS:** `{st['public_url']}`\n"
            f"⏱️ **Uptime:** `{st['uptime']}`\n\n"
            f"👇 **Nhấn nút bên dưới để mở game trong điện thoại:**"
        )
        keyboard = [
            [
                InlineKeyboardButton("🎮 OPEN PREVIEW", web_app=WebAppInfo(url=st["public_url"])),
            ],
            [
                InlineKeyboardButton("🌐 Mở bằng Browser", url=st["public_url"]),
                InlineKeyboardButton("🔄 Làm mới", callback_data="cocos_status"),
            ],
            [
                InlineKeyboardButton("🔄 RESTART", callback_data="cocos_restart"),
                InlineKeyboardButton("⏹ STOP", callback_data="cocos_stop"),
            ],
            [
                InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
            ],
        ]
        return msg, InlineKeyboardMarkup(keyboard)

    # 2. Trường hợp thư mục không phải là dự án Cocos
    if not info.is_cocos:
        msg = (
            f"🎮 **COCOS CREATOR PREVIEW CONTROLLER**\n\n"
            f"⚠️ **Thư mục hiện tại không phải là dự án Cocos Creator:**\n"
            f"📂 `{ws}`\n\n"
            f"💡 *Vui lòng chọn một thư mục dự án Cocos Creator (2.x / 3.x) trong danh sách Workspace trước khi bật Preview.*"
        )
        keyboard = [
            [InlineKeyboardButton("📁 Chọn Workspace Cocos", callback_data="menu_workspace")],
            [InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")],
        ]
        return msg, InlineKeyboardMarkup(keyboard)

    # 3. Trường hợp dự án Cocos nhưng chưa chạy (IDLE / ERROR / STOPPING)
    status_label = "🔴 Lỗi: " + st["error_message"] if st["status"] == CocosPreviewState.ERROR else "⚪ Chưa chạy (IDLE)"
    msg = (
        f"🎮 **COCOS CREATOR PREVIEW CONTROLLER**\n\n"
        f"📂 **Dự án:** `{info.project_name}`\n"
        f"🛠️ **Phiên bản:** `Cocos Creator {info.engine_version}`\n"
        f"📁 **Thư mục:** `{info.project_path}`\n"
        f"⚙️ **Trình thực thi:** `{os.path.basename(info.executable_path) if info.executable_path else 'Chưa tìm thấy'}`\n\n"
        f"📊 **Trạng thái:** `{status_label}`\n\n"
        f"👇 Nhấn **START PREVIEW** để khởi động Preview Server & Cloudflare Tunnel:"
    )

    keyboard = [
        [
            InlineKeyboardButton("🚀 START PREVIEW", callback_data="cocos_start"),
        ],
        [
            InlineKeyboardButton("📁 Đổi Workspace", callback_data="menu_workspace"),
            InlineKeyboardButton("🔄 Làm mới", callback_data="cocos_status"),
        ],
        [
            InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
        ],
    ]
    return msg, InlineKeyboardMarkup(keyboard)


# ==========================================
# COMMAND HANDLERS
# ==========================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start - Menu điều khiển chính."""
    user = update.effective_user
    if not user or not auth_mgr.is_whitelisted(user.id):
        await send_unauthorized_msg(update)
        return

    if not auth_mgr.is_authenticated(user.id):
        await send_locked_msg(update)
        return

    msg = get_main_dashboard_text(user.id, user.first_name)
    reply_markup = build_main_menu_keyboard(user.id)

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /lock hoặc /logout - Khóa Controller an toàn."""
    user = update.effective_user
    if not user or not auth_mgr.is_whitelisted(user.id):
        await send_unauthorized_msg(update)
        return

    auth_mgr.lock(user.id)
    msg = (
        "🔒 **LOCAL CONTROLLER ĐÃ ĐƯỢC KHÓA**\n\n"
        "Tất cả quyền điều khiển và truy cập file đã được đóng an toàn.\n"
        "Nhập mã PIN để mở khóa lại bất cứ lúc nào."
    )
    keyboard = [
        [InlineKeyboardButton("🔐 Mở khóa (Nhập PIN)", callback_data="auth_unlock")],
    ]
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))


async def cmd_unlock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /unlock hoặc /auth [pin] - Mở khóa Controller."""
    user = update.effective_user
    if not user or not auth_mgr.is_whitelisted(user.id):
        await send_unauthorized_msg(update)
        return

    # Nếu người dùng truyền PIN trực tiếp (ví dụ: /unlock 123456)
    if context.args:
        pin = context.args[0]
        # Xóa tin nhắn chứa PIN nếu có quyền để bảo mật chat history
        try:
            await update.message.delete()
        except Exception:
            pass

        ok, res_msg = auth_mgr.verify_pin(user.id, pin)
        if ok:
            dashboard = get_main_dashboard_text(user.id, user.first_name)
            await update.message.reply_text(
                f"🟢 **XÁC THỰC THÀNH CÔNG!**\n\n{dashboard}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_main_menu_keyboard(user.id),
            )
        else:
            await update.message.reply_text(res_msg, parse_mode=ParseMode.MARKDOWN)
    else:
        auth_mgr.set_awaiting_pin(user.id, True)
        await update.message.reply_text(
            "🔐 **Vui lòng nhập mã PIN bảo mật:**\n\nGõ mã PIN của bạn và gửi vào đây.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_cocos_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /preview hoặc /cocos - Bảng điều khiển Cocos Creator Preview."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    msg, reply_markup = build_cocos_preview_view(user.id)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /agent - Chọn Agent Engine."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    active_type = agent_mgr.get_active_agent_type(user.id)
    agy_active = "✅ " if active_type == AgentType.ANTIGRAVITY else "▫️ "
    codex_active = "✅ " if active_type == AgentType.CODEX else "▫️ "

    agy_acc = account_mgr.get_antigravity_account()
    codex_acc = account_mgr.get_codex_account()

    msg = (
        f"🔀 **CHỌN AGENT ENGINE ĐIỀU KHIỂN**\n\n"
        f"• 🤖 **Google Antigravity:** Gemini 3.7 Flash/Pro, Claude Sonnet 4.6, Accept-Edits & Plan.\n"
        f"  👤 Account: `{agy_acc.email}`\n\n"
        f"• ⚡ **OpenAI Codex:** GPT-5.6 Terra, o3, o3-mini, elevated sandbox & MCP.\n"
        f"  ⚡ Account: `{codex_acc.email}` (Gói `{codex_acc.plan_type}`)\n\n"
        f"👇 Nhấn chọn Agent bạn muốn sử dụng:"
    )

    keyboard = [
        [
            InlineKeyboardButton(f"{agy_active}🤖 Antigravity", callback_data="set_agent_antigravity"),
            InlineKeyboardButton(f"{codex_active}⚡ OpenAI Codex", callback_data="set_agent_codex"),
        ],
        [
            InlineKeyboardButton("👤 Xem chi tiết tài khoản", callback_data="menu_account"),
            InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
        ],
    ]

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /account hoặc /profile - Xem thông tin tài khoản."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    summary = account_mgr.get_all_accounts_summary()
    keyboard = [
        [
            InlineKeyboardButton("🔄 Làm mới", callback_data="menu_account"),
            InlineKeyboardButton("🔀 Đổi Agent", callback_data="menu_agent"),
        ],
        [InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")],
    ]
    await update.message.reply_text(
        summary, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /help - Hướng dẫn chi tiết."""
    user = update.effective_user
    if not user or not auth_mgr.is_whitelisted(user.id):
        await send_unauthorized_msg(update)
        return

    if not auth_mgr.is_authenticated(user.id):
        help_locked = (
            "📖 **HƯỚNG DẪN MỞ KHÓA BOT**\n\n"
            "Controller hiện đang ở trạng thái **LOCKED** để bảo vệ an toàn máy tính.\n"
            "• Gõ mã PIN và gửi trực tiếp vào tin nhắn chat để mở khóa.\n"
            "• Hoặc gõ lệnh `/unlock <mã_pin>`."
        )
        await update.message.reply_text(help_locked, parse_mode=ParseMode.MARKDOWN)
        return

    help_text = (
        f"📖 **HƯỚNG DẪN ĐIỀU KHIỂN LOCAL CONTROLLER**\n\n"
        f"🔐 **Bảo mật & Khóa:**\n"
        f"• `/lock` hoặc `/logout` - Khóa ngay bảng điều khiển\n"
        f"• `/unlock <mã_pin>` - Mở khóa Controller\n\n"
        f"🎮 **Cocos Creator Preview:**\n"
        f"• Nhấn **🎮 Cocos Preview** hoặc gõ `/preview` để bật server preview game và mở tunnel Cloudflare HTTPS.\n"
        f"• Nhấn **🎮 OPEN PREVIEW** để chơi game trực tiếp trong ứng dụng Telegram!\n\n"
        f"💬 **Trò chuyện & Lập trình AI:**\n"
        f"• Nhắn trực tiếp câu hỏi hoặc yêu cầu cho bot để AI tự động code, sửa bug.\n\n"
        f"🎛️ **Các lệnh điều khiển:**\n"
        f"• `/start` - Mở bảng điều khiển chính\n"
        f"• `/agent` - Đổi giữa **🤖 Antigravity** và **⚡ OpenAI Codex**\n"
        f"• `/account` - Xem thông tin Email & Gói tài khoản AI\n"
        f"• `/model` - Đổi Model AI và Reasoning Effort\n"
        f"• `/workspace` hoặc `/ws` - Xem và đổi thư mục dự án\n"
        f"• `/cd <đường dẫn>` - Chuyển sang thư mục bất kỳ trên máy tính\n"
        f"• `/new` hoặc `/reset` - Bắt đầu phiên trò chuyện mới\n"
        f"• `/stop` - Hủy tác vụ AI đang chạy dở\n"
        f"• `/status` - Xem CPU, RAM, Ổ cứng, Uptime máy tính\n"
        f"• `/screenshot` hoặc `/screen` - Chụp màn hình PC gửi về điện thoại\n"
        f"• `/cmd <lệnh>` - Chạy lệnh PowerShell trực tiếp trên PC\n"
        f"• `/ls [thư mục]` - Xem danh sách file trong workspace\n"
        f"• `/view <file>` - Xem nội dung file ngay trên Telegram"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /new hoặc /reset - Xóa phiên làm việc hiện tại."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    active_type = agent_mgr.get_active_agent_type(user.id)
    runner = agent_mgr.get_active_runner(user.id)
    agent_mgr.reset_session(user.id, active_type)

    await update.message.reply_text(
        f"🔄 **Đã làm mới phiên làm việc của {runner.display_name}!**\nTin nhắn tiếp theo sẽ bắt đầu một cuộc hội thoại mới.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /stop - Hủy tác vụ đang chạy."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    if agent_mgr.is_running(user.id):
        stopped = agent_mgr.cancel_active_task(user.id)
        if stopped:
            await update.message.reply_text("🛑 **Đã gửi tín hiệu dừng tác vụ Agent.**", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("⚠️ Không thể dừng tác vụ hoặc tác vụ đã kết thúc.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("ℹ️ Hiện không có tác vụ nào đang chạy.", parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /status - Xem tài nguyên PC và tài khoản."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    ws = workspace_mgr.get_current_workspace(user.id)
    active_type = agent_mgr.get_active_agent_type(user.id)
    runner = agent_mgr.get_active_runner(user.id)
    session = agent_mgr.get_session(user.id, active_type)

    status_text = SystemUtils.get_system_status(
        current_workspace=ws,
        conversation_id=session.conversation_id or "",
        active_agent=runner.display_name,
        model_name=session.model,
    )

    keyboard = [
        [
            InlineKeyboardButton("🔄 Làm mới", callback_data="menu_status"),
            InlineKeyboardButton("🎮 Cocos Preview", callback_data="cocos_preview"),
        ],
        [
            InlineKeyboardButton("👤 Tài khoản AI", callback_data="menu_account"),
            InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
        ],
        [
            InlineKeyboardButton("🔒 Khóa Controller", callback_data="auth_lock"),
            InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
        ],
    ]
    await update.message.reply_text(
        status_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /screenshot - Chụp màn hình máy tính."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    msg = await update.message.reply_text("📸 Đang chụp màn hình PC...")
    success, result = SystemUtils.capture_screenshot()
    if success:
        await update.message.reply_photo(
            photo=result,
            caption="🖥️ **Ảnh chụp màn hình máy tính hiện tại**",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await msg.delete()
        except Exception:
            pass
    else:
        await msg.edit_text(f"❌ {result}")


async def cmd_workspace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /workspace - Quản lý workspace."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    current_ws = workspace_mgr.get_current_workspace(user.id)
    known_ws = workspace_mgr.get_known_workspaces()

    lines = [
        f"📂 **QUẢN LÝ THƯ MỤC LÀM VIỆC (WORKSPACE)**\n",
        f"📍 **Thư mục hiện tại:**\n`{current_ws}`\n",
        f"💡 Bạn cũng có thể gõ lệnh `/cd <đường dẫn>` để chuyển sang thư mục bất kỳ.\n",
        f"👇 **Danh sách dự án đã nhận diện:**",
    ]

    keyboard = []
    for idx, path in enumerate(known_ws):
        folder_name = os.path.basename(path.rstrip("\\/")) or path
        is_active = (path.lower() == current_ws.lower())
        btn_text = f"{'✅ ' if is_active else '📁 '}{folder_name}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ws_select_{idx}")])

    keyboard.append([
        InlineKeyboardButton("🎮 Cocos Preview", callback_data="cocos_preview"),
        InlineKeyboardButton("📂 Xem file (/ls)", callback_data="ws_list_files"),
    ])
    keyboard.append([InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /cd <path> - Đổi thư mục làm việc."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    if not context.args:
        await update.message.reply_text(
            f"⚠️ Vui lòng cung cấp đường dẫn thư mục.\nVí dụ: `/cd {Config.BASE_DIR}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target_path = " ".join(context.args)
    ok_cd, res = workspace_mgr.set_workspace(user.id, target_path)
    if ok_cd:
        await update.message.reply_text(
            f"✅ **Đã chuyển Workspace sang:**\n`{res}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(res, parse_mode=ParseMode.MARKDOWN)


async def cmd_ls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /ls [subpath] - Liệt kê file."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    subpath = " ".join(context.args) if context.args else ""
    current_ws = workspace_mgr.get_current_workspace(user.id)
    ok_ls, res = workspace_mgr.list_files(current_ws, subpath)
    await update.message.reply_text(res, parse_mode=ParseMode.MARKDOWN)


async def cmd_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /view <file> - Đọc nội dung file."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    if not context.args:
        await update.message.reply_text("⚠️ Vui lòng cung cấp tên file: `/view main.py`", parse_mode=ParseMode.MARKDOWN)
        return

    filepath = " ".join(context.args)
    current_ws = workspace_mgr.get_current_workspace(user.id)
    ok_v, res = workspace_mgr.read_file(current_ws, filepath)
    await send_smart_message(context.bot, update.effective_chat.id, res)


async def cmd_powershell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /cmd <command> - Chạy PowerShell trực tiếp."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Vui lòng cung cấp lệnh cần chạy: `/cmd dir` hoặc `/cmd git status`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    cmd = " ".join(context.args)
    current_ws = workspace_mgr.get_current_workspace(user.id)

    status_msg = await update.message.reply_text(f"⚡ Đang thực thi: `{cmd}`...", parse_mode=ParseMode.MARKDOWN)
    code, output = await SystemUtils.run_shell_command(cmd, cwd=current_ws, timeout=60)

    try:
        await status_msg.delete()
    except Exception:
        pass

    result_text = f"💻 **Kết quả thực thi (Mã thoát: {code}):**\n```\n{output or '(Không có output)'}\n```"
    await send_smart_message(context.bot, update.effective_chat.id, result_text, reply_to_message_id=update.message.message_id)


def build_model_settings_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Tạo giao diện cấu hình Model/Effort phù hợp với Agent đang kích hoạt."""
    active_type = agent_mgr.get_active_agent_type(user_id)
    runner = agent_mgr.get_active_runner(user_id)
    session = agent_mgr.get_session(user_id, active_type)

    if active_type == AgentType.ANTIGRAVITY:
        acc = account_mgr.get_antigravity_account()
        acc_badge = f"👤 Account: `{acc.email}`"
    else:
        acc = account_mgr.get_codex_account()
        acc_badge = f"⚡ Account: `{acc.email}` (Gói `{acc.plan_type}`)"

    msg = (
        f"⚙️ **CÀI ĐẶT CẤU HÌNH {runner.display_name.upper()}**\n\n"
        f"🤖 **Agent:** {runner.display_name}\n"
        f"{acc_badge}\n"
        f"🧠 **Model hiện tại:** `{session.model or 'Mặc định'}`\n"
        f"⚡ **Reasoning Effort:** `{session.effort or 'Mặc định'}`\n"
    )

    if active_type == AgentType.ANTIGRAVITY:
        msg += f"🛠️ **Execution Mode:** `{session.mode}`\n"

    msg += "\n👇 **Chọn tùy chọn bên dưới để thay đổi:**"

    keyboard = []

    # Danh sách Model
    models = runner.get_available_models()
    for i in range(0, len(models), 2):
        row = []
        for model_id, label in models[i : i + 2]:
            is_cur = session.model.lower() == model_id.lower()
            btn_text = f"{'✅ ' if is_cur else ''}{label}"
            row.append(InlineKeyboardButton(btn_text, callback_data=f"set_model_{model_id}"))
        keyboard.append(row)

    # Danh sách Effort
    efforts = runner.get_available_efforts()
    effort_row = []
    for eff_id, label in efforts:
        is_cur = session.effort.lower() == eff_id.lower()
        btn_text = f"{'✅ ' if is_cur else ''}Effort: {label}"
        effort_row.append(InlineKeyboardButton(btn_text, callback_data=f"set_effort_{eff_id}"))
    keyboard.append(effort_row)

    # Mode riêng của Antigravity
    if active_type == AgentType.ANTIGRAVITY:
        keyboard.append([
            InlineKeyboardButton(f"{'✅ ' if session.mode == 'accept-edits' else ''}Mode: Accept Edits", callback_data="set_mode_accept-edits"),
            InlineKeyboardButton(f"{'✅ ' if session.mode == 'plan' else ''}Mode: Plan", callback_data="set_mode_plan"),
        ])

    keyboard.append([
        InlineKeyboardButton("🔀 Đổi Agent", callback_data="menu_agent"),
        InlineKeyboardButton("👤 Tài khoản AI", callback_data="menu_account"),
    ])
    keyboard.append([InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")])

    return msg, InlineKeyboardMarkup(keyboard)


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /model - Cài đặt Model và tham số."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    msg, reply_markup = build_model_settings_view(user.id)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


# ==========================================
# CALLBACK QUERY HANDLER
# ==========================================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các nút bấm inline keyboard với Authorization Middleware bắt buộc."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not user or not auth_mgr.is_whitelisted(user.id):
        auth_mgr.log_security_event(SecurityEventType.UNAUTHORIZED_USER, user.id if user else 0, f"Callback rejected: {query.data}")
        await query.answer("⛔ Bạn chưa được phân quyền!", show_alert=True)
        return

    data = query.data

    # --- A. CÁC CALLBACK BẢO MẬT & XÁC THỰC (Không yêu cầu đã authenticated trước) ---
    if data == "auth_unlock":
        auth_mgr.set_awaiting_pin(user.id, True)
        await query.edit_message_text(
            "🔐 **VUI LÒNG NHẬP MÃ PIN BẢO MẬT:**\n\n"
            "👉 Hãy gõ mã PIN của bạn và gửi trực tiếp vào đây để mở khóa Controller.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif data == "auth_help":
        help_text = (
            "🛡️ **THÔNG TIN BẢO MẬT LOCAL CONTROLLER**\n\n"
            "• Controller này điều khiển trực tiếp phần cứng và tệp trên PC của bạn.\n"
            "• Trạng thái xác thực chỉ lưu trong bộ nhớ tạm thời (RAM).\n"
            "• Khi máy tính hoặc bot restart, Controller sẽ tự động **LOCKED** lại.\n"
            "• Nhập đúng mã PIN để mở khóa và điều khiển."
        )
        keyboard = [[InlineKeyboardButton("🔐 Mở khóa", callback_data="auth_unlock")]]
        await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data == "auth_lock":
        auth_mgr.lock(user.id)
        msg, reply_markup = build_locked_view()
        await query.edit_message_text(
            f"🔒 **ĐÃ KHÓA LOCAL CONTROLLER THÀNH CÔNG!**\n\n{msg}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
        )
        return

    # --- B. KIỂM TRA AUTHENTICATED CHO TẤT CẢ CÁC CHỨC NĂNG CÒN LẠI ---
    if not auth_mgr.is_authenticated(user.id):
        auth_mgr.log_security_event(SecurityEventType.UNAUTHORIZED_COMMAND, user.id, f"Blocked locked callback: {data}")
        await query.answer("🔒 Controller đang bị khóa. Vui lòng mở khóa trước!", show_alert=True)
        msg, reply_markup = build_locked_view()
        try:
            await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        except Exception:
            pass
        return

    # --- C. DISPATCH CÁC ACTION ĐÃ ĐƯỢC XÁC THỰC ---

    # --- 1. MENU CHÍNH ---
    if data == "menu_main":
        msg = get_main_dashboard_text(user.id, user.first_name)
        reply_markup = build_main_menu_keyboard(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    # --- 2. COCOS PREVIEW CONTROLLER ---
    elif data == "cocos_preview" or data == "cocos_status":
        msg, reply_markup = build_cocos_preview_view(user.id)
        try:
            await query.edit_message_text(
                msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )
        except Exception:
            pass

    elif data == "cocos_start":
        ws = workspace_mgr.get_current_workspace(user.id)
        info = cocos_detector.detect_project(ws)

        if not info.is_cocos:
            msg, reply_markup = build_cocos_preview_view(user.id)
            await query.edit_message_text(
                msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )
            return

        await query.edit_message_text(
            f"🎮 **ĐANG KHỞI ĐỘNG COCOS PREVIEW...**\n\n"
            f"📂 Dự án: `{info.project_name}`\n"
            f"🛠️ Engine: `Cocos Creator {info.engine_version}`\n\n"
            f"⏳ *Đang bật Engine & Cloudflare Tunnel... Vui lòng đợi trong giây lát.*",
            parse_mode=ParseMode.MARKDOWN,
        )

        def progress_cb(text: str):
            logger.info(f"[Cocos Progress] {text}")

        success, res = await cocos_preview_mgr.start_preview(
            workspace_path=ws,
            status_callback=progress_cb,
        )

        msg, reply_markup = build_cocos_preview_view(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    elif data == "cocos_stop":
        await query.edit_message_text("⏳ Đang dừng Cocos Preview & Cloudflare Tunnel...")
        await cocos_preview_mgr.stop_preview()
        msg, reply_markup = build_cocos_preview_view(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    elif data == "cocos_restart":
        ws = workspace_mgr.get_current_workspace(user.id)
        await query.edit_message_text("🔄 Đang khởi động lại Cocos Preview...")
        await cocos_preview_mgr.restart_preview(ws)
        msg, reply_markup = build_cocos_preview_view(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    # --- 3. AGENT & MODEL SETTINGS ---
    elif data == "menu_agent":
        active_type = agent_mgr.get_active_agent_type(user.id)
        agy_active = "✅ " if active_type == AgentType.ANTIGRAVITY else "▫️ "
        codex_active = "✅ " if active_type == AgentType.CODEX else "▫️ "

        agy_acc = account_mgr.get_antigravity_account()
        codex_acc = account_mgr.get_codex_account()

        msg = (
            f"🔀 **CHỌN AGENT ENGINE ĐIỀU KHIỂN**\n\n"
            f"• 🤖 **Google Antigravity:** Gemini 3.7 Flash/Pro, Claude Sonnet 4.6, Accept-Edits & Plan.\n"
            f"  👤 Account: `{agy_acc.email}`\n\n"
            f"• ⚡ **OpenAI Codex:** GPT-5.6 Terra, o3, o3-mini, elevated sandbox & MCP.\n"
            f"  ⚡ Account: `{codex_acc.email}` (Gói `{codex_acc.plan_type}`)\n\n"
            f"👇 Nhấn để chuyển đổi Agent:"
        )
        keyboard = [
            [
                InlineKeyboardButton(f"{agy_active}🤖 Antigravity", callback_data="set_agent_antigravity"),
                InlineKeyboardButton(f"{codex_active}⚡ OpenAI Codex", callback_data="set_agent_codex"),
            ],
            [
                InlineKeyboardButton("👤 Tài khoản AI", callback_data="menu_account"),
                InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
            ],
        ]
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data in ("set_agent_antigravity", "set_agent_codex"):
        new_agent = AgentType.ANTIGRAVITY if data == "set_agent_antigravity" else AgentType.CODEX
        agent_mgr.set_active_agent_type(user.id, new_agent)
        runner = agent_mgr.get_active_runner(user.id)
        session = agent_mgr.get_session(user.id, new_agent)

        msg = (
            f"✅ **Đã chuyển sang {runner.display_name}!**\n\n"
            f"🧠 **Model:** `{session.model}`\n"
            f"⚡ **Effort:** `{session.effort}`\n"
            f"💬 **Session ID:** `{session.conversation_id or 'Phiên mới'}`"
        )
        keyboard = [
            [
                InlineKeyboardButton("⚙️ Cấu hình Model", callback_data="menu_settings"),
                InlineKeyboardButton("👤 Tài khoản AI", callback_data="menu_account"),
            ],
            [InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")],
        ]
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "menu_account":
        summary = account_mgr.get_all_accounts_summary()
        keyboard = [
            [
                InlineKeyboardButton("🔄 Làm mới", callback_data="menu_account"),
                InlineKeyboardButton("🔀 Đổi Agent", callback_data="menu_agent"),
            ],
            [InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")],
        ]
        await query.edit_message_text(
            summary, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "menu_settings":
        msg, reply_markup = build_model_settings_view(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    elif data.startswith("set_model_"):
        new_model = data.replace("set_model_", "")
        agent_mgr.set_model(user.id, new_model)
        msg, reply_markup = build_model_settings_view(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    elif data.startswith("set_effort_"):
        new_effort = data.replace("set_effort_", "")
        agent_mgr.set_effort(user.id, new_effort)
        msg, reply_markup = build_model_settings_view(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    elif data.startswith("set_mode_"):
        new_mode = data.replace("set_mode_", "")
        agent_mgr.set_mode(user.id, new_mode)
        msg, reply_markup = build_model_settings_view(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    # --- 4. WORKSPACE & SYSTEM UTILS ---
    elif data == "menu_workspace":
        current_ws = workspace_mgr.get_current_workspace(user.id)
        known_ws = workspace_mgr.get_known_workspaces()
        keyboard = []
        for idx, path in enumerate(known_ws):
            folder_name = os.path.basename(path.rstrip("\\/")) or path
            is_active = (path.lower() == current_ws.lower())
            btn_text = f"{'✅ ' if is_active else '📁 '}{folder_name}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ws_select_{idx}")])
        keyboard.append([
            InlineKeyboardButton("🎮 Cocos Preview", callback_data="cocos_preview"),
            InlineKeyboardButton("📂 Xem file (/ls)", callback_data="ws_list_files"),
        ])
        keyboard.append([InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")])

        await query.edit_message_text(
            f"📂 **CHỌN WORKSPACE**\nHiện tại: `{current_ws}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("ws_select_"):
        idx = int(data.split("_")[-1])
        known_ws = workspace_mgr.get_known_workspaces()
        if 0 <= idx < len(known_ws):
            target_ws = known_ws[idx]
            workspace_mgr.set_workspace(user.id, target_ws)
            await query.edit_message_text(
                f"✅ **Đã đổi Workspace thành:**\n`{target_ws}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎮 Cocos Preview", callback_data="cocos_preview")],
                    [InlineKeyboardButton("⬅️ Danh sách Workspace", callback_data="menu_workspace")],
                ]),
            )

    elif data == "ws_list_files":
        current_ws = workspace_mgr.get_current_workspace(user.id)
        ok_ls, res = workspace_mgr.list_files(current_ws)
        await query.edit_message_text(
            res,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_workspace")]]),
        )

    elif data == "menu_status":
        ws = workspace_mgr.get_current_workspace(user.id)
        active_type = agent_mgr.get_active_agent_type(user.id)
        runner = agent_mgr.get_active_runner(user.id)
        session = agent_mgr.get_session(user.id, active_type)

        status_text = SystemUtils.get_system_status(
            current_workspace=ws,
            conversation_id=session.conversation_id or "",
            active_agent=runner.display_name,
            model_name=session.model,
        )
        keyboard = [
            [
                InlineKeyboardButton("🔄 Làm mới", callback_data="menu_status"),
                InlineKeyboardButton("🎮 Cocos Preview", callback_data="cocos_preview"),
            ],
            [
                InlineKeyboardButton("👤 Tài khoản AI", callback_data="menu_account"),
                InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
            ],
            [
                InlineKeyboardButton("🔒 Khóa Controller", callback_data="auth_lock"),
                InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
            ],
        ]
        try:
            await query.edit_message_text(
                status_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            pass

    elif data == "menu_screenshot":
        success, result = SystemUtils.capture_screenshot()
        if success:
            await query.message.reply_photo(
                photo=result,
                caption="🖥️ **Ảnh chụp màn hình máy tính**",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await query.message.reply_text(f"❌ {result}")

    elif data == "menu_reset":
        active_type = agent_mgr.get_active_agent_type(user.id)
        runner = agent_mgr.get_active_runner(user.id)
        agent_mgr.reset_session(user.id, active_type)
        await query.edit_message_text(
            f"🔄 **Đã xóa ngữ cảnh cũ của {runner.display_name}!**\nTin nhắn tiếp theo sẽ bắt đầu một phiên mới.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")]]),
        )

    elif data == "menu_help":
        help_text = (
            f"📖 **HƯỚNG DẪN NHANH**\n\n"
            f"• Nhấn **🎮 Cocos Preview** để mở game trên điện thoại.\n"
            f"• Nhắn trực tiếp yêu cầu lập trình cho Bot.\n"
            f"• Dùng `/agent` để chuyển đổi Antigravity / Codex.\n"
            f"• Dùng `/lock` để khóa Controller khi không dùng.\n"
            f"• Dùng `/workspace` để đổi thư mục code.\n"
            f"• Dùng `/screenshot` để xem màn hình PC."
        )
        await query.edit_message_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")]]),
        )


# ==========================================
# FILE UPLOAD HANDLER
# ==========================================

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lưu tệp hoặc ảnh người dùng gửi vào thư mục làm việc hiện tại."""
    user = update.effective_user
    ok, err = auth_mgr.authorize(user.id)
    if not ok:
        await send_locked_msg(update) if auth_mgr.is_whitelisted(user.id) else await send_unauthorized_msg(update)
        return

    doc = update.message.document
    photo = update.message.photo

    current_ws = workspace_mgr.get_current_workspace(user.id)
    target_dir = Path(current_ws)

    try:
        if doc:
            file_name = doc.file_name or f"file_{int(time.time())}"
            target_path = target_dir / file_name
            tfile = await context.bot.get_file(doc.file_id)
            await tfile.download_to_drive(custom_path=target_path)
            await update.message.reply_text(
                f"📥 **Đã lưu tệp:** `{file_name}`\n"
                f"📂 **Vào thư mục:** `{target_dir}`\n\n"
                f"💡 Bạn có thể yêu cầu Agent xử lý tệp này ngay bây giờ.",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif photo:
            photo_obj = photo[-1]
            file_name = f"photo_{int(time.time())}.jpg"
            target_path = target_dir / file_name
            tfile = await context.bot.get_file(photo_obj.file_id)
            await tfile.download_to_drive(custom_path=target_path)
            await update.message.reply_text(
                f"📥 **Đã lưu ảnh:** `{file_name}`\n"
                f"📂 **Vào thư mục:** `{target_dir}`",
                parse_mode=ParseMode.MARKDOWN,
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi khi tải tệp về máy tính: {e}")


# ==========================================
# MAIN PROMPT & PIN MESSAGE HANDLER
# ==========================================

async def handle_prompt_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhận tin nhắn văn bản, xác thực PIN nếu đang LOCKED, hoặc chuyển tới AI Agent nếu đã AUTHENTICATED."""
    user = update.effective_user
    if not user or not auth_mgr.is_whitelisted(user.id):
        await send_unauthorized_msg(update)
        return

    text_input = update.message.text.strip()
    if not text_input:
        return

    # --- 1. XỬ LÝ KHI CHƯA AUTHENTICATED (NHẬP PIN MỞ KHÓA) ---
    if not auth_mgr.is_authenticated(user.id):
        # Tự động thử PIN
        ok, res_msg = auth_mgr.verify_pin(user.id, text_input)
        if ok:
            # Xóa tin nhắn chứa PIN nếu có quyền để bảo mật chat
            try:
                await update.message.delete()
            except Exception:
                pass

            dashboard = get_main_dashboard_text(user.id, user.first_name)
            await update.message.reply_text(
                f"🟢 **XÁC THỰC THÀNH CÔNG!**\n\n{dashboard}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_main_menu_keyboard(user.id),
            )
        else:
            await update.message.reply_text(res_msg, parse_mode=ParseMode.MARKDOWN)
        return

    # --- 2. XỬ LÝ PROMPT LẬP TRÌNH KHI ĐÃ AUTHENTICATED ---
    prompt_text = text_input

    # Kiểm tra xem có tác vụ nào đang chạy cho user này không
    if agent_mgr.is_running(user.id):
        await update.message.reply_text(
            "⏳ **Agent đang xử lý một tác vụ khác.**\n"
            "Vui lòng đợi hoặc gõ `/stop` để hủy tác vụ hiện tại.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    current_ws = workspace_mgr.get_current_workspace(user.id)
    chat_id = update.effective_chat.id
    runner = agent_mgr.get_active_runner(user.id)

    # Gửi tin nhắn trạng thái ban đầu
    status_msg = await update.message.reply_text(
        f"⏳ **Đang gửi yêu cầu tới {runner.display_name}...**\n"
        f"📂 `{current_ws}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    last_status_text = ""
    last_update_time = time.time()
    final_result_event = None

    async def update_status(new_text: str):
        nonlocal last_status_text, last_update_time
        now = time.time()
        # Cập nhật tối đa 1 lần mỗi 1.5 giây để tránh rate limit
        if new_text != last_status_text and (now - last_update_time > 1.5):
            last_status_text = new_text
            last_update_time = now
            try:
                await status_msg.edit_text(new_text, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass

    async def keep_typing():
        try:
            while agent_mgr.is_running(user.id):
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4.5)
        except Exception:
            pass

    typing_task = asyncio.create_task(keep_typing())

    try:
        async for event in agent_mgr.execute_prompt(
            user_id=user.id,
            prompt=prompt_text,
            workspace_dir=current_ws,
        ):
            if event.event_type == "init":
                conv_short = event.conversation_id[:8] if event.conversation_id else "new"
                await update_status(
                    f"{runner.emoji} **{runner.display_name} đã khởi động**\n"
                    f"💬 Session: `{conv_short}...`\n"
                    f"📂 `{current_ws}`"
                )

            elif event.event_type == "tool_start":
                await update_status(
                    f"{event.content}\n"
                    f"📂 `{current_ws}`"
                )

            elif event.event_type == "result":
                final_result_event = event

            elif event.event_type == "error":
                await status_msg.edit_text(event.content)
                return

    except Exception as e:
        logger.exception("Error executing prompt")
        await status_msg.edit_text(f"❌ Đã xảy ra lỗi: {e}")
        return
    finally:
        typing_task.cancel()

    # Xóa tin nhắn trạng thái
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Gửi kết quả cuối cùng
    if final_result_event and final_result_event.content:
        duration = final_result_event.duration_seconds or 0.0
        tokens = final_result_event.tokens_used or 0
        conv_id = final_result_event.conversation_id or ""
        conv_short = conv_id[:8] if conv_id else ""

        footer = (
            f"\n\n━━━━━━━━━━━━━━━━━━\n"
            f"{runner.emoji} **{runner.display_name}** | ⏱️ `{duration:.1f}s` | 🪙 `{tokens:,} tokens`"
        )
        if conv_short:
            footer += f" | 💬 `{conv_short}...`"

        full_text = final_result_event.content + footer

        await send_smart_message(
            context.bot,
            chat_id=chat_id,
            text=full_text,
            reply_to_message_id=update.message.message_id,
        )
    else:
        await update.message.reply_text(f"✅ {runner.display_name} đã hoàn thành tác vụ mà không có văn bản trả về.")


# ==========================================
# BOT APPLICATION SETUP & RUN
# ==========================================

def main():
    """Khởi động Telegram Bot."""
    token = Config.TELEGRAM_BOT_TOKEN
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("=" * 60)
        print("❌ LỖI: Chưa cấu hình TELEGRAM_BOT_TOKEN!")
        print("Vui lòng mở file .env và dán Bot Token từ @BotFather vào.")
        print(f"Đường dẫn file .env: {Config.BASE_DIR / '.env'}")
        print("=" * 60)
        sys.exit(1)

    print("=" * 60)
    print("🚀 KHỞI ĐỘNG LOCAL CONTROLLER (AUTHENTICATION & SECURITY ENABLED)")
    print(f"📂 Workspace mặc định: {Config.DEFAULT_WORKSPACE}")
    print(f"🤖 Agent mặc định: {Config.DEFAULT_AGENT.upper()}")
    print(f"🛠️ agy path: {Config.AGY_PATH}")
    print(f"⚡ codex path: {Config.CODEX_PATH}")
    print(f"🌐 cloudflared path: {Config.CLOUDFLARED_PATH or 'Chưa tìm thấy'}")
    print(f"👥 Allowed Users: {Config.ALLOWED_USER_IDS or 'Chưa có (sẽ chặn tất cả truy cập)'}")
    print(f"🔐 Security: PIN Hash scrypt verified | Rate Limit: {Config.AUTH_MAX_ATTEMPTS} attempts / {Config.AUTH_LOCKOUT_SECONDS}s lockout")
    print("=" * 60)

    app = Application.builder().token(token).build()

    # Đăng ký Command Handlers
    app.add_handler(CommandHandler(["start"], cmd_start))
    app.add_handler(CommandHandler(["lock", "logout"], cmd_lock))
    app.add_handler(CommandHandler(["unlock", "auth"], cmd_unlock))
    app.add_handler(CommandHandler(["preview", "cocos", "game"], cmd_cocos_preview))
    app.add_handler(CommandHandler(["agent", "engine"], cmd_agent))
    app.add_handler(CommandHandler(["account", "profile"], cmd_account))
    app.add_handler(CommandHandler(["help"], cmd_help))
    app.add_handler(CommandHandler(["new", "reset"], cmd_reset))
    app.add_handler(CommandHandler(["stop", "cancel"], cmd_stop))
    app.add_handler(CommandHandler(["status"], cmd_status))
    app.add_handler(CommandHandler(["screenshot", "screen"], cmd_screenshot))
    app.add_handler(CommandHandler(["workspace", "ws"], cmd_workspace))
    app.add_handler(CommandHandler(["cd"], cmd_cd))
    app.add_handler(CommandHandler(["ls", "files"], cmd_ls))
    app.add_handler(CommandHandler(["view", "cat"], cmd_view))
    app.add_handler(CommandHandler(["cmd", "run"], cmd_powershell))
    app.add_handler(CommandHandler(["model", "settings"], cmd_model))

    # Đăng ký Callback Query Handler cho các nút bấm inline
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Đăng ký File Upload Handler
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document_upload))

    # Đăng ký Message Handler cho prompt / PIN
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt_message))

    async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Xử lý lỗi toàn cục của Telegram Bot."""
        if isinstance(context.error, Conflict):
            logger.warning("⚠️ Xung đột: Có một tiến trình Bot khác đang chạy cùng Token này!")
            print("\n" + "=" * 60)
            print("⚠️ CẢNH BÁO XUNG ĐỘT (409 Conflict):")
            print("Đang có một cửa sổ hoặc tiến trình bot.py khác chạy cùng lúc.")
            print("Hãy chạy file 'stop_bot.bat' để đóng các phiên cũ, sau đó mở lại 'start_bot.bat'.")
            print("=" * 60 + "\n")
        else:
            logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

    app.add_error_handler(global_error_handler)

    # Đăng ký hàm dọn dẹp khi tắt bot
    def cleanup():
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(cocos_preview_mgr.stop_preview())
            loop.close()
        except Exception:
            pass

    atexit.register(cleanup)

    print("🤖 Controller đã sẵn sàng và đang ở trạng thái LOCKED. Nhấn Ctrl+C để dừng.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
