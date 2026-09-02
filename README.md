# 🤖 Dual Agent Telegram Controller (Antigravity & OpenAI Codex)

Ứng dụng Telegram Bot giúp bạn **điều khiển trực tiếp Google Antigravity Agent & OpenAI Codex Agent từ điện thoại** mọi lúc, mọi nơi thông qua Telegram!

---

## 🌟 Tính năng nổi bật

1. **Hỗ trợ 2 AI Agent độc lập (Dual Engine):**
   - 🤖 **Google Antigravity:** Gemini 3.7 Flash, Gemini 3.1 Pro, Claude Sonnet 4.6, Claude Opus 4.6 với chế độ Accept-Edits và Plan.
   - ⚡ **OpenAI Codex:** GPT-5.6 Terra, OpenAI o3, o3-mini, GPT-4.1 với Sandbox elevated & MCP Tools.
   - Chuyển đổi Agent tức thì chỉ bằng 1 nút bấm trên Telegram (`/agent` hoặc qua menu).

2. **Lập trình & Điều khiển từ xa:**
   - Nhắn tin trực tiếp yêu cầu tạo code, fix bug, chạy lệnh, tìm kiếm trong project.
   - Hiển thị trực tiếp các bước Agent đang thực hiện (*⚡ Đang chạy lệnh...*, *📝 Đang sửa file...*).
   - Tự động duy trì phiên làm việc nhiều lượt hội thoại độc lập cho từng Agent.

3. **Bảo mật tuyệt đối (Access Control):**
   - Chỉ duy nhất các Telegram User ID được cấu hình trong file `.env` mới có quyền điều khiển bot và can thiệp vào máy tính của bạn.

4. **Quản lý Workspace thông minh:**
   - Tự động nhận diện các dự án có sẵn từ cả Antigravity (`settings.json`) và Codex (`config.toml`).
   - Đổi thư mục dự án dễ dàng với `/workspace` hoặc `/cd <đường dẫn>`.
   - Xem cấu trúc file (`/ls`) và đọc nhanh nội dung code (`/view <file>`) ngay trên điện thoại.

5. **Giám sát & Quản trị hệ thống PC:**
   - `/status`: Theo dõi thông số CPU, RAM, dung lượng ổ đĩa (C:, D:, E:...) và Agent đang kích hoạt.
   - `/screenshot`: Chụp ảnh màn hình máy tính gửi về điện thoại theo thời gian thực.
   - `/cmd <lệnh>`: Thực thi nhanh các lệnh PowerShell (ví dụ: `git status`, `git pull`, `taskkill`...).

6. **Gửi file & Tệp tin:**
   - Kéo thả hoặc gửi file/ảnh qua Telegram, bot sẽ tự động lưu thẳng vào thư mục làm việc hiện tại trên máy tính.

---

## 🚀 Hướng dẫn cài đặt & Khởi chạy (Chỉ 2 phút)

### Bước 1: Tạo Telegram Bot & Lấy Token
1. Mở Telegram, tìm kiếm bot tên là **[@BotFather](https://t.me/BotFather)**.
2. Gửi lệnh `/newbot` và làm theo hướng dẫn để đặt tên cho bot.
3. @BotFather sẽ cấp cho bạn một chuỗi **HTTP API Token** (ví dụ: `7123456789:AAFxX...`).

### Bước 2: Cấu hình file `.env`
Mở file [`.env`](file:///E:/TELEGRAM_BOT/CocosDevBot/.env) trong thư mục `E:\TELEGRAM_BOT\CocosDevBot\` và điền:
```env
TELEGRAM_BOT_TOKEN=Dán_Token_Vừa_Tạo_Vào_Đây
ALLOWED_USER_IDS=ID_Telegram_Của_Bạn
DEFAULT_AGENT=antigravity # hoặc codex
```

> 💡 **Mẹo lấy Telegram User ID:**
> - Bạn có thể chat với bot **[@userinfobot](https://t.me/userinfobot)** trên Telegram để xem ID của mình.
> - Hoặc cứ chạy bot và nhắn bất kỳ tin nhắn nào vào bot, bot sẽ tự động thông báo ID của bạn trên màn hình chat!

### Bước 3: Khởi động Bot
- **Cách 1:** Nhấp đúp chuột vào file [`start_bot.bat`](file:///E:/TELEGRAM_BOT/CocosDevBot/start_bot.bat) để chạy với cửa sổ dòng lệnh.
- **Cách 2:** Nhấp đúp vào [`start_bot_background.vbs`](file:///E:/TELEGRAM_BOT/CocosDevBot/start_bot_background.vbs) để bot chạy ẩn ngầm dưới nền máy tính.

---

## 📱 Danh sách các lệnh điều khiển trên Telegram

| Lệnh | Chức năng |
| :--- | :--- |
| **Nhắn tin trực tiếp** | Gửi yêu cầu lập trình / xử lý tác vụ cho Agent đang kích hoạt |
| `/start` | Mở bảng điều khiển và menu phím tắt |
| `/agent` | Chuyển đổi giữa **🤖 Google Antigravity** và **⚡ OpenAI Codex** |
| `/model` | Cấu hình Model AI (Gemini, Claude, GPT, o3...) và Reasoning Effort |
| `/help` | Xem hướng dẫn chi tiết các lệnh |
| `/new` hoặc `/reset` | Xóa ngữ cảnh cũ và bắt đầu một phiên chat mới |
| `/stop` | Hủy ngay tác vụ Agent đang chạy dở |
| `/workspace` hoặc `/ws` | Xem và chọn nhanh thư mục dự án cần làm việc |
| `/cd <đường_dẫn>` | Chuyển thư mục làm việc sang đường dẫn bất kỳ trên PC |
| `/ls [thư mục]` | Liệt kê danh sách các file/thư mục con |
| `/view <file>` | Đọc nội dung file code ngay trên Telegram |
| `/status` | Xem thông số CPU, RAM, Ổ cứng, Uptime PC và Agent hiện tại |
| `/screenshot` | Chụp màn hình máy tính gửi về Telegram |
| `/cmd <lệnh>` | Chạy lệnh PowerShell trực tiếp trên máy |

---

## 🛠️ Cấu trúc thư mục mã nguồn

```
E:\TELEGRAM_BOT\CocosDevBot\
├── bot.py                    # Chương trình chính Telegram Bot & Giao diện người dùng
├── agent_base.py             # Lớp cơ sở (Base), giao diện và sự kiện dùng chung
├── agent_manager.py          # Bộ điều phối trung tâm quản lý Antigravity & Codex
├── antigravity_runner.py     # Module điều khiển Google Antigravity CLI (agy)
├── codex_runner.py           # Module điều khiển OpenAI Codex CLI (codex)
├── workspace_manager.py      # Tự động nhận diện dự án từ settings Antigravity & Codex
├── system_utils.py           # Giám sát phần cứng PC, chụp màn hình, chạy PowerShell
├── config.py                 # Quản lý cấu hình & phát hiện đường dẫn binary agy/codex
├── requirements.txt          # Danh sách thư viện Python
├── .env                      # File cấu hình Token và User ID bảo mật
├── .env.example              # Mẫu cấu hình mẫu
├── start_bot.bat             # File khởi động nhanh 1-click cho Windows
└── start_bot_background.vbs  # File khởi động chạy ngầm
```
