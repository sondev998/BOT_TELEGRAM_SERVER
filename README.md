# 🤖 Dual Agent & Cocos Creator Preview Telegram Controller

Ứng dụng Telegram Bot giúp bạn **điều khiển trực tiếp Google Antigravity Agent, OpenAI Codex Agent và Cocos Creator Preview từ điện thoại** mọi lúc, mọi nơi thông qua Telegram!

---

## 🌟 Tính năng nổi bật

1. **🎮 Cocos Creator Remote Preview (Chơi game từ xa qua Telegram):**
   - Tự động nhận diện dự án **Cocos Creator 2.x và 3.x**.
   - Tự động tìm vị trí cài đặt Engine (`CocosCreator.exe`) và khởi động Preview Server (Port `7456`).
   - Tự động thiết lập **Cloudflare Tunnel (HTTPS)** an toàn không cần mở port modem.
   - Nút **`🎮 OPEN PREVIEW`** mở trực tiếp game trong **Telegram WebView / Telegram Web App** trên điện thoại.
   - Hỗ trợ đầy đủ **WebSocket / Hot Reload / DevTools**.
   - Nút **`🔄 RESTART`** và **`⏹ STOP`** dọn dẹp tiến trình an toàn khi dừng.

2. **🤖 Hỗ trợ 2 AI Agent độc lập (Dual Engine):**
   - 🤖 **Google Antigravity:** Gemini 3.7 Flash, Gemini 3.1 Pro, Claude Sonnet 4.6, Claude Opus 4.6 với chế độ Accept-Edits và Plan.
   - ⚡ **OpenAI Codex:** GPT-5.6 Terra, OpenAI o3, o3-mini, GPT-4.1 với Sandbox elevated & MCP Tools.
   - Chuyển đổi Agent tức thì chỉ bằng 1 nút bấm trên Telegram (`/agent` hoặc qua menu).

3. **👤 Quản lý tài khoản AI tự động (`/account`):**
   - Hiển thị Email, Tên chủ tài khoản, Gói dịch vụ (Free, Plus, Pro, Consumer) của cả Antigravity và Codex.

4. **📁 Quản lý Workspace thông minh:**
   - Tự động nhận diện các dự án có sẵn từ cả Antigravity (`settings.json`) và Codex (`config.toml`).
   - Đổi thư mục dự án dễ dàng với `/workspace` hoặc `/cd <đường dẫn>`.
   - Xem cấu trúc file (`/ls`) và đọc nhanh nội dung code (`/view <file>`) ngay trên điện thoại.

5. **🖥️ Giám sát & Quản trị hệ thống PC:**
   - `/status`: Theo dõi thông số CPU, RAM, dung lượng ổ đĩa (C:, D:, E:...) và Uptime.
   - `/screenshot`: Chụp ảnh màn hình máy tính gửi về điện thoại theo thời gian thực.
   - `/cmd <lệnh>`: Thực thi nhanh các lệnh PowerShell (ví dụ: `git status`, `git pull`, `taskkill`...).

---

## 🚀 Hướng dẫn cài đặt & Khởi chạy (Chỉ 2 phút)

### Bước 1: Cấu hình file `.env`
Mở file [`.env`](file:///E:/TELEGRAM_BOT/CocosDevBot/.env) trong thư mục `E:\TELEGRAM_BOT\CocosDevBot\` và điền:
```env
TELEGRAM_BOT_TOKEN=Dán_Token_Vừa_Tạo_Vào_Đây
ALLOWED_USER_IDS=ID_Telegram_Của_Bạn
DEFAULT_AGENT=antigravity # hoặc codex
```

### Bước 2: Khởi động Bot
- **Cách 1:** Nhấp đúp chuột vào file [`start_bot.bat`](file:///E:/TELEGRAM_BOT/CocosDevBot/start_bot.bat) để chạy với cửa sổ dòng lệnh.
- **Cách 2:** Nhấp đúp vào [`start_bot_background.vbs`](file:///E:/TELEGRAM_BOT/CocosDevBot/start_bot_background.vbs) để bot chạy ẩn ngầm dưới nền máy tính.

---

## 📱 Danh sách các lệnh điều khiển trên Telegram

| Lệnh | Chức năng |
| :--- | :--- |
| **Nhắn tin trực tiếp** | Gửi yêu cầu lập trình / sửa bug cho AI Agent đang kích hoạt |
| `/start` | Mở bảng điều khiển và menu phím tắt |
| `/preview` hoặc `/cocos` | Mở bảng điều khiển **Cocos Creator Preview** |
| `/agent` | Chuyển đổi giữa **🤖 Google Antigravity** và **⚡ OpenAI Codex** |
| `/account` | Xem chi tiết tài khoản AI (Email, Gói cước Free/Pro/Plus) |
| `/model` | Cấu hình Model AI (Gemini, Claude, GPT, o3...) và Reasoning Effort |
| `/workspace` hoặc `/ws` | Xem và chọn nhanh thư mục dự án Cocos cần làm việc |
| `/cd <đường_dẫn>` | Chuyển thư mục làm việc sang đường dẫn bất kỳ trên PC |
| `/ls [thư mục]` | Liệt kê danh sách các file/thư mục con |
| `/view <file>` | Đọc nội dung file code ngay trên Telegram |
| `/status` | Xem thông số CPU, RAM, Ổ cứng, Uptime PC và tài khoản |
| `/screenshot` | Chụp màn hình máy tính gửi về Telegram |
| `/cmd <lệnh>` | Chạy lệnh PowerShell trực tiếp trên máy |

---

## 🛠️ Cấu trúc thư mục mã nguồn

```
E:\TELEGRAM_BOT\CocosDevBot\
├── bot.py                    # Chương trình chính Telegram Bot & Giao diện người dùng
├── cocos_preview_manager.py  # Bộ điều khiển vòng đời Cocos Preview & Tunnel
├── cocos_detector.py         # Tự động nhận diện dự án Cocos 2.x/3.x & Engine Exe
├── cloudflare_tunnel_manager.py # Quản lý Cloudflare Tunnel (cloudflared)
├── agent_manager.py          # Bộ điều phối trung tâm quản lý Antigravity & Codex
├── account_manager.py        # Quản lý & trích xuất Email, Plan, Tier tài khoản AI
├── antigravity_runner.py     # Module điều khiển Google Antigravity CLI (agy)
├── codex_runner.py           # Module điều khiển OpenAI Codex CLI (codex)
├── workspace_manager.py      # Tự động nhận diện dự án từ settings Antigravity & Codex
├── system_utils.py           # Giám sát phần cứng PC, chụp màn hình, chạy PowerShell
├── config.py                 # Quản lý cấu hình & phát hiện đường dẫn binary
├── requirements.txt          # Danh sách thư viện Python
├── .env                      # File cấu hình Token và User ID bảo mật
├── .env.example              # Mẫu cấu hình mẫu
├── start_bot.bat             # File khởi động nhanh 1-click cho Windows
└── start_bot_background.vbs  # File khởi động chạy ngầm
```
