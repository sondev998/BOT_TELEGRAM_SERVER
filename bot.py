import asyncio
import html
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

from agy_runner import agy_runner
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
logger = logging.getLogger("AntigravityTelegramBot")


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def is_authorized(user_id: int) -> bool:
    """Kiểm tra quyền của người dùng."""
    return Config.is_user_allowed(user_id)


async def send_unauthorized_msg(update: Update):
    """Thông báo khi người dùng chưa được cấp quyền."""
    user = update.effective_user
    user_id = user.id if user else 0
    text = (
        f"⛔ **BẠN CHƯA ĐƯỢC PHÂN QUYỀN TRUY CẬP**\n\n"
        f"👤 **User ID của bạn:** `{user_id}`\n\n"
        f"👉 **Cách cấp quyền:**\n"
        f"1. Mở file `.env` tại thư mục bot trên máy tính:\n"
        f"   `E:\\TELEGRAM_BOT\\GAME_DEV_BOT\\.env`\n"
        f"2. Thêm ID của bạn vào dòng:\n"
        f"   `ALLOWED_USER_IDS={user_id}`\n"
        f"3. Lưu file và khởi động lại Bot."
    )
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query:
        await update.callback_query.answer("⛔ Bạn chưa được phân quyền!", show_alert=True)


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
        file_data.name = f"antigravity_output_{int(time.time())}.md"
        await bot.send_document(
            chat_id=chat_id,
            document=file_data,
            caption="📄 Toàn bộ nội dung phản hồi từ Antigravity",
        )
        return

    # Chia nhỏ tin nhắn nếu dài hơn 4000 ký tự
    max_chunk = 3800
    chunks = []
    if len(text) <= max_chunk:
        chunks.append(text)
    else:
        # Cắt theo dòng
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
            # Markdown bị lỗi định dạng -> gửi dạng plain text
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_to_message_id=reply_to_message_id,
            )


# ==========================================
# COMMAND HANDLERS
# ==========================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start - Menu điều khiển chính."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    ws = workspace_mgr.get_current_workspace(user.id)
    session = agy_runner.get_session(user.id)

    msg = (
        f"🤖 **ANTIGRAVITY TELEGRAM CONTROLLER**\n\n"
        f"Chào mừng **{user.first_name}**! Bạn có thể gửi lệnh trực tiếp để Antigravity lập trình, sửa lỗi và quản lý dự án trên PC.\n\n"
        f"📂 **Workspace:** `{ws}`\n"
        f"🧠 **Model:** `{session.model}`\n"
        f"⚡ **Effort:** `{session.effort}` | **Mode:** `{session.mode}`\n"
        f"💬 **Session ID:** `{session.conversation_id or 'Chưa có (sẽ tạo mới)'}`\n\n"
        f"👇 **Chọn chức năng nhanh:**"
    )

    keyboard = [
        [
            InlineKeyboardButton("📁 Chọn Workspace", callback_data="menu_workspace"),
            InlineKeyboardButton("⚙️ Cấu hình Model", callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("📊 Trạng thái PC", callback_data="menu_status"),
            InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
        ],
        [
            InlineKeyboardButton("🔄 Phiên chat mới", callback_data="menu_reset"),
            InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu_help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /help - Hướng dẫn chi tiết."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    help_text = (
        f"📖 **HƯỚNG DẪN ĐIỀU KHIỂN ANTIGRAVITY QUA TELEGRAM**\n\n"
        f"💬 **Trò chuyện & Lập trình:**\n"
        f"• Nhắn trực tiếp câu hỏi hoặc yêu cầu cho bot (ví dụ: `Hãy viết script tải ảnh`, `Kiểm tra lỗi trong file main.py`, ...)\n"
        f"• Bot sẽ gọi Antigravity CLI, tự động đọc/ghi file và thực thi lệnh.\n\n"
        f"🎛️ **Các lệnh điều khiển:**\n"
        f"• `/start` - Mở bảng điều khiển chính\n"
        f"• `/new` hoặc `/reset` - Bắt đầu phiên trò chuyện mới (xóa ngữ cảnh cũ)\n"
        f"• `/stop` - Hủy tác vụ Antigravity đang chạy dở\n"
        f"• `/workspace` hoặc `/ws` - Xem và đổi thư mục làm việc\n"
        f"• `/cd <đường dẫn>` - Chuyển sang thư mục bất kỳ trên máy tính\n"
        f"• `/status` - Xem CPU, RAM, Ổ cứng, Uptime máy tính\n"
        f"• `/screenshot` hoặc `/screen` - Chụp ảnh màn hình máy tính gửi về điện thoại\n"
        f"• `/cmd <lệnh>` - Chạy lệnh PowerShell trực tiếp trên PC\n"
        f"• `/ls [thư mục]` - Xem danh sách file trong workspace\n"
        f"• `/view <file>` - Xem nội dung file ngay trên Telegram\n"
        f"• `/model` - Đổi model AI (Gemini 3.7 Flash, Pro...)\n\n"
        f"📥 **Gửi file/ảnh:**\n"
        f"• Bạn có thể gửi file/ảnh trực tiếp qua Telegram, bot sẽ lưu thẳng vào thư mục làm việc hiện tại!"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /new hoặc /reset - Xóa phiên làm việc hiện tại."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    agy_runner.reset_session(user.id)
    await update.message.reply_text(
        "🔄 **Đã làm mới phiên làm việc!**\nTin nhắn tiếp theo sẽ bắt đầu một cuộc hội thoại mới với Antigravity.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /stop - Hủy tác vụ đang chạy."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    if agy_runner.is_running(user.id):
        stopped = agy_runner.cancel_active_task(user.id)
        if stopped:
            await update.message.reply_text("🛑 **Đã gửi tín hiệu dừng tác vụ Antigravity.**", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("⚠️ Không thể dừng tác vụ hoặc tác vụ đã kết thúc.", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("ℹ️ Hiện không có tác vụ nào đang chạy.", parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /status - Xem tài nguyên PC."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    ws = workspace_mgr.get_current_workspace(user.id)
    session = agy_runner.get_session(user.id)
    status_text = SystemUtils.get_system_status(ws, session.conversation_id or "")

    keyboard = [
        [
            InlineKeyboardButton("🔄 Làm mới", callback_data="menu_status"),
            InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
        ]
    ]
    await update.message.reply_text(
        status_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /screenshot - Chụp màn hình máy tính."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
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
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
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

    keyboard.append([InlineKeyboardButton("📂 Xem danh sách file (/ls)", callback_data="ws_list_files")])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /cd <path> - Đổi thư mục làm việc."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Vui lòng cung cấp đường dẫn thư mục.\nVí dụ: `/cd E:\\TELEGRAM_BOT\\GAME_DEV_BOT`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target_path = " ".join(context.args)
    ok, res = workspace_mgr.set_workspace(user.id, target_path)
    if ok:
        await update.message.reply_text(
            f"✅ **Đã chuyển Workspace sang:**\n`{res}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(res, parse_mode=ParseMode.MARKDOWN)


async def cmd_ls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /ls [subpath] - Liệt kê file."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    subpath = " ".join(context.args) if context.args else ""
    current_ws = workspace_mgr.get_current_workspace(user.id)
    ok, res = workspace_mgr.list_files(current_ws, subpath)
    await update.message.reply_text(res, parse_mode=ParseMode.MARKDOWN)


async def cmd_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /view <file> - Đọc nội dung file."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    if not context.args:
        await update.message.reply_text("⚠️ Vui lòng cung cấp tên file: `/view main.py`", parse_mode=ParseMode.MARKDOWN)
        return

    filepath = " ".join(context.args)
    current_ws = workspace_mgr.get_current_workspace(user.id)
    ok, res = workspace_mgr.read_file(current_ws, filepath)
    await send_smart_message(context.bot, update.effective_chat.id, res)


async def cmd_powershell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /cmd <command> - Chạy PowerShell trực tiếp."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
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


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /model - Cài đặt Model và tham số."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    session = agy_runner.get_session(user.id)

    msg = (
        f"⚙️ **CÀI ĐẶT CẤU HÌNH ANTIGRAVITY**\n\n"
        f"🧠 **Model hiện tại:** `{session.model}`\n"
        f"⚡ **Reasoning Effort:** `{session.effort}`\n"
        f"🛠️ **Execution Mode:** `{session.mode}`\n\n"
        f"👇 Chọn tùy chọn bên dưới để thay đổi:"
    )

    keyboard = [
        [
            InlineKeyboardButton("⚡ Gemini 3.7 Flash", callback_data="set_model_Gemini 3.7 Flash (High)"),
            InlineKeyboardButton("🧠 Gemini 3.1 Pro", callback_data="set_model_Gemini 3.1 Pro (High)"),
        ],
        [
            InlineKeyboardButton("🎭 Claude Sonnet 4.6", callback_data="set_model_Claude Sonnet 4.6 (Thinking)"),
            InlineKeyboardButton("🦁 Claude Opus 4.6", callback_data="set_model_Claude Opus 4.6 (Thinking)"),
        ],
        [
            InlineKeyboardButton("Effort: High 🔴", callback_data="set_effort_high"),
            InlineKeyboardButton("Effort: Medium 🟡", callback_data="set_effort_medium"),
            InlineKeyboardButton("Effort: Low 🟢", callback_data="set_effort_low"),
        ],
        [
            InlineKeyboardButton("Mode: Accept Edits", callback_data="set_mode_accept-edits"),
            InlineKeyboardButton("Mode: Plan", callback_data="set_mode_plan"),
        ],
    ]

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==========================================
# CALLBACK QUERY HANDLER
# ==========================================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý các nút bấm inline keyboard."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    data = query.data

    if data == "menu_workspace":
        current_ws = workspace_mgr.get_current_workspace(user.id)
        known_ws = workspace_mgr.get_known_workspaces()
        keyboard = []
        for idx, path in enumerate(known_ws):
            folder_name = os.path.basename(path.rstrip("\\/")) or path
            is_active = (path.lower() == current_ws.lower())
            btn_text = f"{'✅ ' if is_active else '📁 '}{folder_name}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ws_select_{idx}")])
        keyboard.append([InlineKeyboardButton("📂 Danh sách file", callback_data="ws_list_files")])
        keyboard.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")])

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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_workspace")]]),
            )

    elif data == "ws_list_files":
        current_ws = workspace_mgr.get_current_workspace(user.id)
        ok, res = workspace_mgr.list_files(current_ws)
        await query.edit_message_text(
            res,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_workspace")]]),
        )

    elif data == "menu_status":
        ws = workspace_mgr.get_current_workspace(user.id)
        session = agy_runner.get_session(user.id)
        status_text = SystemUtils.get_system_status(ws, session.conversation_id or "")
        keyboard = [
            [
                InlineKeyboardButton("🔄 Làm mới", callback_data="menu_status"),
                InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
            ],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
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

    elif data == "menu_settings":
        session = agy_runner.get_session(user.id)
        msg = (
            f"⚙️ **CÀI ĐẶT CẤU HÌNH ANTIGRAVITY**\n\n"
            f"🧠 **Model:** `{session.model}`\n"
            f"⚡ **Effort:** `{session.effort}`\n"
            f"🛠️ **Mode:** `{session.mode}`"
        )
        keyboard = [
            [
                InlineKeyboardButton("⚡ Gemini 3.7 Flash", callback_data="set_model_Gemini 3.7 Flash (High)"),
                InlineKeyboardButton("🧠 Gemini 3.1 Pro", callback_data="set_model_Gemini 3.1 Pro (High)"),
            ],
            [
                InlineKeyboardButton("🎭 Claude Sonnet 4.6", callback_data="set_model_Claude Sonnet 4.6 (Thinking)"),
                InlineKeyboardButton("🦁 Claude Opus 4.6", callback_data="set_model_Claude Opus 4.6 (Thinking)"),
            ],
            [
                InlineKeyboardButton("Effort: High 🔴", callback_data="set_effort_high"),
                InlineKeyboardButton("Effort: Medium 🟡", callback_data="set_effort_medium"),
                InlineKeyboardButton("Effort: Low 🟢", callback_data="set_effort_low"),
            ],
            [
                InlineKeyboardButton("Mode: Accept Edits", callback_data="set_mode_accept-edits"),
                InlineKeyboardButton("Mode: Plan", callback_data="set_mode_plan"),
            ],
            [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
        ]
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("set_model_"):
        new_model = data.replace("set_model_", "")
        agy_runner.set_model(user.id, new_model)
        await query.edit_message_text(
            f"✅ **Đã chuyển Model thành:** `{new_model}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cấu hình", callback_data="menu_settings")]]),
        )

    elif data.startswith("set_effort_"):
        new_effort = data.replace("set_effort_", "")
        agy_runner.set_effort(user.id, new_effort)
        session = agy_runner.get_session(user.id)
        await query.edit_message_text(
            f"✅ **Đã chuyển Effort thành:** `{new_effort}`\n🧠 **Model cập nhật:** `{session.model}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cấu hình", callback_data="menu_settings")]]),
        )

    elif data.startswith("set_mode_"):
        new_mode = data.replace("set_mode_", "")
        agy_runner.set_mode(user.id, new_mode)
        await query.edit_message_text(
            f"✅ **Đã chuyển Mode thành:** `{new_mode}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Cấu hình", callback_data="menu_settings")]]),
        )

    elif data == "menu_reset":
        agy_runner.reset_session(user.id)
        await query.edit_message_text(
            "🔄 **Đã xóa ngữ cảnh cũ!**\nTin nhắn tiếp theo sẽ bắt đầu một phiên Antigravity mới.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")]]),
        )

    elif data == "menu_help":
        help_text = (
            f"📖 **HƯỚNG DẪN NHANH**\n\n"
            f"• Nhắn trực tiếp yêu cầu lập trình cho Bot.\n"
            f"• Dùng `/stop` để hủy lệnh đang chạy.\n"
            f"• Dùng `/workspace` để đổi thư mục code.\n"
            f"• Dùng `/screenshot` để xem màn hình PC."
        )
        await query.edit_message_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")]]),
        )

    elif data == "menu_main":
        ws = workspace_mgr.get_current_workspace(user.id)
        session = agy_runner.get_session(user.id)
        msg = (
            f"🤖 **ANTIGRAVITY TELEGRAM CONTROLLER**\n\n"
            f"📂 **Workspace:** `{ws}`\n"
            f"🧠 **Model:** `{session.model}`\n"
            f"⚡ **Effort:** `{session.effort}` | **Mode:** `{session.mode}`\n\n"
            f"👇 **Chọn chức năng nhanh:**"
        )
        keyboard = [
            [
                InlineKeyboardButton("📁 Chọn Workspace", callback_data="menu_workspace"),
                InlineKeyboardButton("⚙️ Cấu hình Model", callback_data="menu_settings"),
            ],
            [
                InlineKeyboardButton("📊 Trạng thái PC", callback_data="menu_status"),
                InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
            ],
            [
                InlineKeyboardButton("🔄 Phiên chat mới", callback_data="menu_reset"),
                InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu_help"),
            ],
        ]
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ==========================================
# FILE UPLOAD HANDLER
# ==========================================

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lưu tệp hoặc ảnh người dùng gửi vào thư mục làm việc hiện tại."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
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
                f"💡 Bạn có thể yêu cầu Antigravity xử lý tệp này ngay bây giờ.",
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
# MAIN PROMPT MESSAGE HANDLER
# ==========================================

async def handle_prompt_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhận tin nhắn văn bản và gửi tới Antigravity CLI."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    prompt_text = update.message.text.strip()
    if not prompt_text:
        return

    # Kiểm tra xem có tác vụ nào đang chạy cho user này không
    if agy_runner.is_running(user.id):
        await update.message.reply_text(
            "⏳ **Antigravity đang xử lý một tác vụ khác.**\n"
            "Vui lòng đợi hoặc gõ `/stop` để hủy tác vụ hiện tại.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    current_ws = workspace_mgr.get_current_workspace(user.id)
    chat_id = update.effective_chat.id

    # Gửi tin nhắn trạng thái ban đầu
    status_msg = await update.message.reply_text(
        "⏳ **Đang gửi yêu cầu tới Antigravity...**\n"
        f"📂 `{current_ws}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Biến theo dõi cập nhật tin nhắn trạng thái (tránh flood limit của Telegram)
    last_status_text = ""
    last_update_time = time.time()
    final_result_event = None

    async def update_status(new_text: str):
        nonlocal last_status_text, last_update_time
        now = time.time()
        # Cập nhật tối đa 1 lần mỗi 1.5 giây
        if new_text != last_status_text and (now - last_update_time > 1.5):
            last_status_text = new_text
            last_update_time = now
            try:
                await status_msg.edit_text(new_text, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass

    # Tạo tác vụ typing định kỳ trong lúc chờ
    async def keep_typing():
        try:
            while agy_runner.is_running(user.id):
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4.5)
        except Exception:
            pass

    typing_task = asyncio.create_task(keep_typing())

    try:
        async for event in agy_runner.execute_prompt(
            user_id=user.id,
            prompt=prompt_text,
            workspace_dir=current_ws,
        ):
            if event.event_type == "init":
                await update_status(
                    f"🤖 **Antigravity đã khởi động**\n"
                    f"💬 Session: `{event.conversation_id[:8]}...`\n"
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

        footer = f"\n\n━━━━━━━━━━━━━━━━━━\n⏱️ `{duration:.1f}s` | 🪙 `{tokens:,} tokens` | 💬 `{conv_id[:8]}...`"
        full_text = final_result_event.content + footer

        await send_smart_message(
            context.bot,
            chat_id=chat_id,
            text=full_text,
            reply_to_message_id=update.message.message_id,
        )
    else:
        await update.message.reply_text("✅ Tác vụ đã hoàn thành mà không có văn bản trả về.")


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
    print("🚀 KHỞI ĐỘNG ANTIGRAVITY TELEGRAM BOT SERVER")
    print(f"📂 Workspace mặc định: {Config.DEFAULT_WORKSPACE}")
    print(f"🧠 Model: {Config.DEFAULT_MODEL}")
    print(f"🛠️ agy path: {Config.AGY_PATH}")
    print(f"👥 Allowed Users: {Config.ALLOWED_USER_IDS or 'Chưa có (sẽ thông báo khi có người nhắn)'}")
    print("=" * 60)

    # Khởi tạo Application
    app = Application.builder().token(token).build()

    # Đăng ký các Command Handlers
    app.add_handler(CommandHandler(["start"], cmd_start))
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

    # Đăng ký Message Handler cho các prompt thông thường
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

    print("🤖 Bot đã sẵn sàng nhận tin nhắn từ Telegram. Nhấn Ctrl+C để dừng.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
