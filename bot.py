import asyncio
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

from agent_base import AgentType
from agent_manager import agent_mgr
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
# HELPER FUNCTIONS
# ==========================================

def is_authorized(user_id: int) -> bool:
    """Kiểm tra quyền của người dùng."""
    return Config.is_user_allowed(user_id)


async def send_unauthorized_msg(update: Update):
    """Thông báo khi người dùng chưa được cấp quyền."""
    user = update.effective_user
    user_id = user.id if user else 0
    env_file_path = Config.BASE_DIR / ".env"
    text = (
        f"⛔ **BẠN CHƯA ĐƯỢC PHÂN QUYỀN TRUY CẬP**\n\n"
        f"👤 **User ID của bạn:** `{user_id}`\n\n"
        f"👉 **Cách cấp quyền:**\n"
        f"1. Mở file `.env` tại thư mục bot trên máy tính:\n"
        f"   `{env_file_path}`\n"
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
            # Markdown bị lỗi định dạng -> gửi dạng plain text
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_to_message_id=reply_to_message_id,
            )


def build_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Tạo bàn phím menu chính."""
    active_agent = agent_mgr.get_active_agent_type(user_id)
    agent_switch_label = (
        "⚡ Chuyển sang Codex" if active_agent == AgentType.ANTIGRAVITY else "🤖 Chuyển sang Antigravity"
    )

    keyboard = [
        [
            InlineKeyboardButton("🔀 Đổi Agent", callback_data="menu_agent"),
            InlineKeyboardButton("⚙️ Cấu hình Model", callback_data="menu_settings"),
        ],
        [
            InlineKeyboardButton("📁 Chọn Workspace", callback_data="menu_workspace"),
            InlineKeyboardButton("📊 Trạng thái PC", callback_data="menu_status"),
        ],
        [
            InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
            InlineKeyboardButton("🔄 Phiên chat mới", callback_data="menu_reset"),
        ],
        [
            InlineKeyboardButton("❓ Hướng dẫn", callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_main_dashboard_text(user_id: int, user_first_name: str = "Bạn") -> str:
    """Tạo nội dung text cho Dashboard chính."""
    ws = workspace_mgr.get_current_workspace(user_id)
    active_type = agent_mgr.get_active_agent_type(user_id)
    runner = agent_mgr.get_active_runner(user_id)
    session = agent_mgr.get_session(user_id, active_type)

    agent_badge = f"{runner.emoji} **{runner.display_name}**"
    session_id_display = session.conversation_id[:12] + "..." if session.conversation_id else "Chưa có (sẽ tạo mới)"

    msg = (
        f"🤖 **DUAL AGENT TELEGRAM CONTROLLER**\n\n"
        f"Chào mừng **{user_first_name}**! Bạn có thể lập trình, fix bug và quản trị PC từ xa.\n\n"
        f"🛠️ **Agent Đang Dùng:** {agent_badge}\n"
        f"📂 **Workspace:** `{ws}`\n"
        f"🧠 **Model:** `{session.model or 'Mặc định'}`\n"
        f"⚡ **Effort:** `{session.effort or 'Mặc định'}`\n"
        f"💬 **Session ID:** `{session_id_display}`\n\n"
        f"👇 **Chọn chức năng nhanh bên dưới:**"
    )
    return msg


# ==========================================
# COMMAND HANDLERS
# ==========================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start - Menu điều khiển chính."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    msg = get_main_dashboard_text(user.id, user.first_name)
    reply_markup = build_main_menu_keyboard(user.id)

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /agent - Chọn Agent Engine."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    active_type = agent_mgr.get_active_agent_type(user.id)
    agy_active = "✅ " if active_type == AgentType.ANTIGRAVITY else "▫️ "
    codex_active = "✅ " if active_type == AgentType.CODEX else "▫️ "

    msg = (
        f"🔀 **CHỌN AGENT ENGINE ĐIỀU KHIỂN**\n\n"
        f"• 🤖 **Google Antigravity:** Tối ưu hóa cho Gemini 3.7 Flash/Pro, Claude Sonnet 4.6, đa chế độ thực thi (Accept-Edits, Plan).\n\n"
        f"• ⚡ **OpenAI Codex:** Tối ưu hóa cho GPT-5.6 Terra, o3, o3-mini, GPT-4.1, hỗ trợ sandbox elevated và MCP Tools.\n\n"
        f"👇 Nhấn chọn Agent bạn muốn sử dụng:"
    )

    keyboard = [
        [
            InlineKeyboardButton(f"{agy_active}🤖 Antigravity", callback_data="set_agent_antigravity"),
            InlineKeyboardButton(f"{codex_active}⚡ OpenAI Codex", callback_data="set_agent_codex"),
        ],
        [InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")],
    ]

    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /help - Hướng dẫn chi tiết."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    help_text = (
        f"📖 **HƯỚNG DẪN ĐIỀU KHIỂN DUAL AGENT BOT**\n\n"
        f"💬 **Trò chuyện & Lập trình:**\n"
        f"• Nhắn trực tiếp câu hỏi hoặc yêu cầu cho bot (ví dụ: `Hãy viết script tải ảnh`, `Kiểm tra lỗi trong file main.py`, ...)\n"
        f"• Bot sẽ gọi Agent đang chọn (Antigravity hoặc Codex) để tự động đọc/ghi file và thực thi lệnh.\n\n"
        f"🎛️ **Các lệnh điều khiển:**\n"
        f"• `/start` - Mở bảng điều khiển chính\n"
        f"• `/agent` - Đổi giữa **🤖 Antigravity** và **⚡ OpenAI Codex**\n"
        f"• `/model` - Đổi Model AI và Reasoning Effort\n"
        f"• `/workspace` hoặc `/ws` - Xem và đổi thư mục dự án\n"
        f"• `/cd <đường dẫn>` - Chuyển sang thư mục bất kỳ trên máy tính\n"
        f"• `/new` hoặc `/reset` - Bắt đầu phiên trò chuyện mới\n"
        f"• `/stop` - Hủy tác vụ đang chạy dở\n"
        f"• `/status` - Xem CPU, RAM, Ổ cứng, Uptime máy tính\n"
        f"• `/screenshot` hoặc `/screen` - Chụp màn hình PC gửi về điện thoại\n"
        f"• `/cmd <lệnh>` - Chạy lệnh PowerShell trực tiếp trên PC\n"
        f"• `/ls [thư mục]` - Xem danh sách file trong workspace\n"
        f"• `/view <file>` - Xem nội dung file ngay trên Telegram\n\n"
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
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
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
    """Lệnh /status - Xem tài nguyên PC."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
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
            InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
        ],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")],
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
    keyboard.append([InlineKeyboardButton("⬅️ Quay lại", callback_data="menu_main")])

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
            f"⚠️ Vui lòng cung cấp đường dẫn thư mục.\nVí dụ: `/cd {Config.BASE_DIR}`",
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


def build_model_settings_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Tạo giao diện cấu hình Model/Effort phù hợp với Agent đang kích hoạt."""
    active_type = agent_mgr.get_active_agent_type(user_id)
    runner = agent_mgr.get_active_runner(user_id)
    session = agent_mgr.get_session(user_id, active_type)

    msg = (
        f"⚙️ **CÀI ĐẶT CẤU HÌNH {runner.display_name.upper()}**\n\n"
        f"🤖 **Agent:** {runner.display_name}\n"
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
        InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
    ])

    return msg, InlineKeyboardMarkup(keyboard)


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /model - Cài đặt Model và tham số."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    msg, reply_markup = build_model_settings_view(user.id)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
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

    if data == "menu_main":
        msg = get_main_dashboard_text(user.id, user.first_name)
        reply_markup = build_main_menu_keyboard(user.id)
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    elif data == "menu_agent":
        active_type = agent_mgr.get_active_agent_type(user.id)
        agy_active = "✅ " if active_type == AgentType.ANTIGRAVITY else "▫️ "
        codex_active = "✅ " if active_type == AgentType.CODEX else "▫️ "

        msg = (
            f"🔀 **CHỌN AGENT ENGINE ĐIỀU KHIỂN**\n\n"
            f"• 🤖 **Google Antigravity:** Gemini 3.7 Flash/Pro, Claude Sonnet 4.6, đa chế độ thực thi.\n\n"
            f"• ⚡ **OpenAI Codex:** GPT-5.6 Terra, o3, o3-mini, GPT-4.1, elevated sandbox & MCP.\n\n"
            f"👇 Nhấn để chuyển đổi Agent:"
        )
        keyboard = [
            [
                InlineKeyboardButton(f"{agy_active}🤖 Antigravity", callback_data="set_agent_antigravity"),
                InlineKeyboardButton(f"{codex_active}⚡ OpenAI Codex", callback_data="set_agent_codex"),
            ],
            [InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")],
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
                InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main"),
            ]
        ]
        await query.edit_message_text(
            msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
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

    elif data == "menu_workspace":
        current_ws = workspace_mgr.get_current_workspace(user.id)
        known_ws = workspace_mgr.get_known_workspaces()
        keyboard = []
        for idx, path in enumerate(known_ws):
            folder_name = os.path.basename(path.rstrip("\\/")) or path
            is_active = (path.lower() == current_ws.lower())
            btn_text = f"{'✅ ' if is_active else '📁 '}{folder_name}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ws_select_{idx}")])
        keyboard.append([InlineKeyboardButton("📂 Xem file (/ls)", callback_data="ws_list_files")])
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
                InlineKeyboardButton("📸 Chụp màn hình", callback_data="menu_screenshot"),
            ],
            [InlineKeyboardButton("⬅️ Trang chủ", callback_data="menu_main")],
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
            f"• Nhắn trực tiếp yêu cầu lập trình cho Bot.\n"
            f"• Dùng `/agent` để chuyển đổi Antigravity / Codex.\n"
            f"• Dùng `/stop` để hủy lệnh đang chạy.\n"
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
# MAIN PROMPT MESSAGE HANDLER
# ==========================================

async def handle_prompt_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhận tin nhắn văn bản và chuyển tới Agent Engine đang kích hoạt."""
    user = update.effective_user
    if not is_authorized(user.id):
        await send_unauthorized_msg(update)
        return

    prompt_text = update.message.text.strip()
    if not prompt_text:
        return

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
    print("🚀 KHỞI ĐỘNG DUAL AGENT TELEGRAM BOT SERVER")
    print(f"📂 Workspace mặc định: {Config.DEFAULT_WORKSPACE}")
    print(f"🤖 Agent mặc định: {Config.DEFAULT_AGENT.upper()}")
    print(f"🛠️ agy path: {Config.AGY_PATH}")
    print(f"⚡ codex path: {Config.CODEX_PATH}")
    print(f"👥 Allowed Users: {Config.ALLOWED_USER_IDS or 'Chưa có (sẽ thông báo khi có người nhắn)'}")
    print("=" * 60)

    app = Application.builder().token(token).build()

    # Đăng ký Command Handlers
    app.add_handler(CommandHandler(["start"], cmd_start))
    app.add_handler(CommandHandler(["agent", "engine"], cmd_agent))
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

    # Đăng ký Message Handler cho prompt
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
