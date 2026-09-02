# 🤖 Antigravity Telegram Controller

Ứng dụng Telegram Bot giúp bạn **điều khiển trực tiếp Google Antigravity Agent từ điện thoại** mọi lúc, mọi nơi thông qua Telegram!

---

## 🌟 Tính năng nổi bật

1. **Lập trình & Điều khiển Antigravity từ xa:**
   - Nhắn tin trực tiếp yêu cầu tạo code, fix bug, chạy lệnh, tìm kiếm trong project.
   - Hiển thị trực tiếp các bước Antigravity đang thực hiện (*⚡ Đang chạy lệnh...*, *📝 Đang sửa file...*).
   - Tự động duy trì phiên làm việc nhiều lượt hội thoại (Multi-turn conversation).

2. **Bảo mật tuyệt đối (Access Control):**
   - Chỉ duy nhất các Telegram User ID được cấu hình trong file `.env` mới có quyền điều khiển bot và can thiệp vào máy tính của bạn.

3. **Quản lý Workspace linh hoạt:**
   - Đổi thư mục dự án dễ dàng với `/workspace` hoặc `/cd <đường dẫn>`.
   - Tự động nhận diện các thư mục Game Dev / Project có sẵn trên máy của bạn.
   - Xem cấu trúc file (`/ls`) và đọc nhanh nội dung code (`/view <file>`) ngay trên điện thoại.

4. **Giám sát & Quản trị hệ thống PC:**
   - `/status`: Theo dõi thông số CPU, RAM, dung lượng ổ đĩa (C:, D:, E:...) và thời gian hoạt động.
   - `/screenshot`: Chụp ảnh màn hình máy tính gửi về điện thoại theo thời gian thực.
   - `/cmd <lệnh>`: Thực thi nhanh các lệnh PowerShell (ví dụ: `git status`, `git pull`, `taskkill`...).

5. **Gửi file & Tệp tin:**
   - Kéo thả hoặc gửi file/ảnh qua Telegram, bot sẽ tự động lưu thẳng vào thư mục làm việc hiện tại trên máy tính.

---

## 🚀 Hướng dẫn cài đặt & Khởi chạy (Chỉ 2 phút)

### Bước 1: Tạo Telegram Bot & Lấy Token
1. Mở Telegram, tìm kiếm bot tên là **[@BotFather](https://t.me/BotFather)**.
2. Gửi lệnh `/newbot` và làm theo hướng dẫn để đặt tên cho bot.
3. @BotFather sẽ cấp cho bạn một chuỗi **HTTP API Token** (ví dụ: `7123456789:AAFxX...`).

### Bước 2: Cấu hình file `.env`
Mở file [`.env`](file:///E:/TELEGRAM_BOT/GAME_DEV_BOT/.env) trong thư mục `E:\TELEGRAM_BOT\GAME_DEV_BOT\` và điền:
```env
TELEGRAM_BOT_TOKEN=Dán_Token_Vừa_Tạo_Vào_Đây
ALLOWED_USER_IDS=ID_Telegram_Của_Bạn
```

> 💡 **Mẹo lấy Telegram User ID:**
> - Bạn có thể chat với bot **[@userinfobot](https://t.me/userinfobot)** trên Telegram để xem ID của mình.
> - Hoặc cứ chạy bot và nhắn bất kỳ tin nhắn nào vào bot, bot sẽ tự động thông báo ID của bạn trên màn hình chat!

### Bước 3: Khởi động Bot
- **Cách 1:** Nhấp đúp chuột vào file [`start_bot.bat`](file:///E:/TELEGRAM_BOT/GAME_DEV_BOT/start_bot.bat) để chạy với cửa sổ dòng lệnh.
- **Cách 2:** Nhấp đúp vào [`start_bot_background.vbs`](file:///E:/TELEGRAM_BOT/GAME_DEV_BOT/start_bot_background.vbs) để bot chạy ẩn ngầm dưới nền máy tính.

---

## 📱 Danh sách các lệnh điều khiển trên Telegram

| Lệnh | Chức năng |
| :--- | :--- |
| **Nhắn tin trực tiếp** | Gửi yêu cầu lập trình / xử lý tác vụ cho Antigravity |
| `/start` | Mở bảng điều khiển và menu phím tắt |
| `/help` | Xem hướng dẫn chi tiết các lệnh |
| `/new` hoặc `/reset` | Xóa ngữ cảnh cũ và bắt đầu một phiên chat mới |
| `/stop` | Hủy ngay tác vụ Antigravity đang chạy dở |
| `/workspace` hoặc `/ws` | Xem và chọn nhanh thư mục dự án cần làm việc |
| `/cd <đường_dẫn>` | Chuyển thư mục làm việc sang đường dẫn bất kỳ trên PC |
| `/ls [thư mục]` | Liệt kê danh sách các file/thư mục con |
| `/view <file>` | Đọc nội dung file code ngay trên Telegram |
| `/status` | Xem thông số CPU, RAM, Ổ cứng và Uptime PC |
| `/screenshot` | Chụp màn hình máy tính gửi về Telegram |
| `/cmd <lệnh>` | Chạy lệnh PowerShell trực tiếp trên máy |
| `/model` | Đổi Model AI (Gemini 3.7 Flash, Pro...) hoặc Effort |

---

## 🛠️ Cấu trúc thư mục mã nguồn

```
E:\TELEGRAM_BOT\GAME_DEV_BOT\
├── bot.py                    # Chương trình chính xử lý Telegram Bot & tin nhắn
├── agy_runner.py             # Bộ điều khiển và stream sự kiện từ Antigravity CLI
├── config.py                 # Tải và xử lý cấu hình bảo mật .env
├── workspace_manager.py      # Quản lý các thư mục dự án và file code
├── system_utils.py           # Giám sát phần cứng PC, chụp màn hình, chạy PowerShell
├── requirements.txt          # Danh sách thư viện Python
├── .env                      # File cấu hình Token và User ID bảo mật
├── .env.example              # Mẫu cấu hình mẫu
├── start_bot.bat             # File khởi động nhanh 1-click cho Windows
└── start_bot_background.vbs  # File khởi động chạy ngầm
```
