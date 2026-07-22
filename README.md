# Telegram football poll bot

Bot này tạo poll trong Telegram group vào mỗi thứ Ba lúc 18:00 theo giờ Việt Nam (GMT+7).

Poll được gửi có cấu hình cố định:

- Câu hỏi: `Đá bóng`
- Lựa chọn: `Đi`, `Không đi`
- Không ẩn danh
- Mỗi người chỉ chọn được một lựa chọn
- Không cho phép thêm lựa chọn

## 1. Chuẩn bị Telegram

1. Tạo bot bằng [@BotFather](https://t.me/BotFather) và lưu lại bot token.
2. Thêm bot vào group cần nhận poll.
3. Đảm bảo bot có quyền gửi tin nhắn trong group.
4. Trong group, gửi một lệnh nhắm tới bot, ví dụ `/id@ten_bot_cua_ban`.
5. Trên máy cá nhân, lấy các update mới nhất bằng lệnh sau. Thay `BOT_TOKEN` bằng token của bạn nhưng không commit token vào repository:

   ```bash
   read -rsp "Bot token: " TELEGRAM_BOT_TOKEN; echo
   curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"
   unset TELEGRAM_BOT_TOKEN
   ```

   Tìm `message.chat.id` trong JSON trả về. Group/supergroup thường có chat ID dạng số âm, ví dụ `-1001234567890`.

## 2. Cấu hình GitHub Secrets

Trong repository, mở **Settings → Secrets and variables → Actions → New repository secret** và tạo:

| Tên secret | Giá trị |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token lấy từ BotFather |
| `TELEGRAM_CHAT_ID` | `message.chat.id` của group |

Không đưa token vào source code, commit, issue hoặc log workflow.

## 3. Chạy và kiểm tra

### Test local

1. Copy file mẫu và điền token + group ID:

   ```bash
   cp .env.example .env
   ```

2. Sửa `.env` với giá trị thật của bạn:

   ```env
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=-1001234567890
   ```

3. Gửi poll thử:

   ```bash
   python3 src/send_poll.py
   ```

   File `.env` đã được gitignore, không bị commit lên repository.

### Unit test

Unit test chạy bằng Python standard library:

```bash
python3 -m unittest discover -s tests -v
```

### Chạy trên GitHub Actions

Để chạy thử poll thật trên GitHub, vào **Actions → Send weekly football poll → Run workflow**. Mỗi lần bấm chạy thủ công sẽ tạo một poll mới.

Workflow tự động chạy bằng cron `0 11 * * 2`, tương ứng 11:00 UTC vào thứ Ba, tức 18:00 GMT+7. GitHub Actions có thể trễ nhẹ khi hệ thống tải cao; scheduled workflow cũng chạy trên branch mặc định.

## Cấu trúc

- `src/send_poll.py`: xây payload và gọi Telegram Bot API.
- `tests/test_send_poll.py`: unit test không gọi mạng.
- `.github/workflows/send-football-poll.yml`: lịch chạy và truyền GitHub Secrets.
