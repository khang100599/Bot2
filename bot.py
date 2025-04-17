import json
import datetime
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import Update
import google.generativeai as genai
import threading
import http.server
import socketserver
import firebase_admin
from firebase_admin import credentials, db

# Lấy token và key từ biến môi trường
TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Kiểm tra token/key
if not TOKEN or not GEMINI_API_KEY:
    raise ValueError("BOT_TOKEN và GEMINI_API_KEY phải được thiết lập trong biến môi trường")

# Cấu hình Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Cấu hình Firebase
cred = credentials.Certificate("/etc/secrets/firebase-service-account.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://bot2-eb694-default-rtdb.asia-southeast1.firebasedatabase.app/'
})

# Tham chiếu đến dữ liệu trong Firebase
ref = db.reference('groups')

# Đọc dữ liệu từ Firebase
def load_data():
    try:
        data = ref.get()
        if data is None:
            return {"groups": {}}
        return {"groups": data}
    except Exception as e:
        print(f"Lỗi khi đọc dữ liệu từ Firebase: {e}")
        return {"groups": {}}

# Lưu dữ liệu vào Firebase
def save_data(data):
    try:
        ref.set(data["groups"])
    except Exception as e:
        print(f"Lỗi khi lưu dữ liệu vào Firebase: {e}")

# Hàm kiểm tra quyền truy cập
def is_subscribed(chat_id, data):
    try:
        group = data["groups"].get(str(chat_id))
        if not group:
            return False
        end_date = datetime.datetime.strptime(group["subscription_end"], "%Y-%m-%d")
        return end_date >= datetime.datetime.now()
    except Exception as e:
        print(f"Lỗi khi kiểm tra quyền truy cập: {e}")
        return False

# Hàm xử lý lệnh /start
async def start(update: Update, context):
    chat_id = update.message.chat.id
    data = load_data()
    if not is_subscribed(chat_id, data):
        await update.message.reply_text("Group này chưa đăng ký sử dụng bot. Liên hệ admin để thuê!")
        return
    await update.message.reply_text("Xin chào! Mình là bot hỗ trợ siêu dễ thương đây! Hỏi mình về cửa hàng, giá, hoặc dịch vụ nhé! 😊")

# Hàm lấy ID group
async def get_id(update: Update, context):
    chat_id = update.message.chat.id
    await update.message.reply_text(f"ID của group này là: {chat_id}")

# Hàm thêm từ khóa spam
async def add_spam_keyword(update: Update, context):
    chat_id = update.message.chat.id
    data = load_data()
    if not is_subscribed(chat_id, data):
        await update.message.reply_text("Group này chưa đăng ký!")
        return
    # Kiểm tra quyền admin
    try:
        admins = [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]
        if update.message.from_user.id not in admins:
            await update.message.reply_text("Chỉ admin group được dùng lệnh này!")
            return
    except Exception as e:
        await update.message.reply_text("Lỗi khi kiểm tra quyền admin. Thử lại sau!")
        print(f"Lỗi kiểm tra admin: {e}")
        return
    if not context.args:
        await update.message.reply_text("Vui lòng cung cấp từ khóa! Ví dụ: /addspam quảng_cáo")
        return
    keyword = context.args[0].lower()
    # Đảm bảo group có cấu trúc dữ liệu
    if str(chat_id) not in data["groups"]:
        data["groups"][str(chat_id)] = {"spam_keywords": [], "violations": {}, "ban_limit": 3, "subscription_end": "2025-12-31"}
    data["groups"][str(chat_id)]["spam_keywords"].append(keyword)
    save_data(data)
    await update.message.reply_text(f"Đã thêm từ khóa '{keyword}' vào danh sách cấm.")

# Hàm reset số lần cảnh báo
async def reset_warnings(update: Update, context):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    data = load_data()
    if not is_subscribed(chat_id, data):
        await update.message.reply_text("Group này chưa đăng ký!")
        return
    # Kiểm tra quyền admin
    try:
        admins = [admin.user.id for admin in await context.bot.get_chat_administrators(chat_id)]
        if update.message.from_user.id not in admins:
            await update.message.reply_text("Chỉ admin group được dùng lệnh này!")
            return
    except Exception as e:
        await update.message.reply_text("Lỗi khi kiểm tra quyền admin. Thử lại sau!")
        print(f"Lỗi kiểm tra admin: {e}")
        return
    # Đảm bảo group có cấu trúc dữ liệu
    if str(chat_id) not in data["groups"]:
        data["groups"][str(chat_id)] = {"spam_keywords": [], "violations": {}, "ban_limit": 3, "subscription_end": "2025-12-31"}
    # Reset số lần vi phạm của người dùng
    data["groups"][str(chat_id)]["violations"][str(user_id)] = 0
    save_data(data)
    await update.message.reply_text(f"Đã reset số lần cảnh báo của bạn (@{update.message.from_user.username}) về 0. Bạn an toàn rồi! 😊")

# Hàm xử lý tin nhắn
async def handle_message(update: Update, context):
    message = update.message
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.lower()

    # Kiểm tra quyền truy cập
    data = load_data()
    if not is_subscribed(chat_id, data):
        return  # Không phản hồi nếu group chưa đăng ký

    # Đảm bảo group có cấu trúc dữ liệu
    if str(chat_id) not in data["groups"]:
        data["groups"][str(chat_id)] = {"spam_keywords": [], "violations": {}, "ban_limit": 3, "subscription_end": "2025-12-31"}
        save_data(data)

    # Kiểm tra spam
    try:
        group_data = data["groups"][str(chat_id)]
        for keyword in group_data["spam_keywords"]:
            if keyword in text:
                await message.delete()
                group_data["violations"][str(user_id)] = group_data["violations"].get(str(user_id), 0) + 1
                warning = f"@{message.from_user.username} gửi tin nhắn chứa từ khóa cấm ('{keyword}'). Vi phạm lần {group_data['violations'][str(user_id)]}."
                await context.bot.send_message(chat_id=chat_id, text=warning)
                if group_data["violations"][str(user_id)] >= group_data["ban_limit"]:
                    await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                    await context.bot.send_message(chat_id=chat_id, text=f"@{message.from_user.username} đã bị cấm vì vi phạm {group_data['ban_limit']} lần.")
                    group_data["violations"][str(user_id)] = 0
                save_data(data)
                return
    except Exception as e:
        print(f"Lỗi khi kiểm tra spam: {e}")
        await message.reply_text("Lỗi khi kiểm tra spam. Thử lại sau!")
        return

    # Xử lý yêu cầu bằng Gemini
    try:
        prompt = f"""
        Bạn là trợ lý cửa hàng, trả lời ngắn gọn và chính xác bằng tiếng Việt.
        - Nếu hỏi về địa chỉ: trả lời "Bên em có chi nhánh từ quận 9, Bình thạnh, hóc môn, tân bình, tân phú, anh zai ở đâu để e sắp xếp"
        - Nếu hỏi về giá, menu, dịch vụ: trả lời "dạ a ở quận mấy để em tư vấn thêm cho, bên em có chi nhánh từ quận 9, Bình tân, bình thạnh, tân phú, hóc môn
        - Nếu yêu cầu ảnh ktv trả lời "Liên hệ Kiet Loz để xem ảnh?"
        - Nếu hỏi mã giảm giá: trả lời "Mã hiện tại: SALE10, giảm 10% đến 30/4/2025."
        - Các câu hỏi khác: trả lời tự nhiên, ngắn gọn.
        Câu hỏi: {text}
        """
        response = model.generate_content(prompt)
        await message.reply_text(response.text)
    except Exception as e:
        await update.message.reply_text("Xin lỗi, tôi gặp lỗi. Thử lại nhé!")
        print(f"Lỗi Gemini: {e}")

# Hàm chạy server HTTP giả để Render nhận cổng
def run_dummy_server():
    PORT = 8080  # Render thường kiểm tra cổng 8080
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Dummy server running on port {PORT} for Render health check...")
        httpd.serve_forever()

def main():
    # Tạo ứng dụng bot
    application = Application.builder().token(TOKEN).build()

    # Thêm lệnh
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("getid", get_id))
    application.add_handler(CommandHandler("addspam", add_spam_keyword))
    application.add_handler(CommandHandler("resetwarnings", reset_warnings))

    # Thêm xử lý tin nhắn
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Chạy server HTTP giả trong một thread riêng
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()

    # Bắt đầu bot
    print("Bot đang chạy...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
