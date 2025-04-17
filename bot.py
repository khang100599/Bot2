import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import firebase_admin
from firebase_admin import credentials, db
import os
import google.generativeai as genai

# Cấu hình logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Lấy token và API key từ biến môi trường
TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Cấu hình Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-pro")

# Kết nối Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    "databaseURL": "https://telegram-antispam-default-rtdb.firebaseio.com/"
})
ref = db.reference("/data")

# Từ khóa spam
SPAM_KEYWORDS = ["spam", "link", "check my profile", "free money", "crypto", "airdrop", "pump", "moon", "earn", "join now"]

# Lệnh /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Chào bạn! Tôi là bot chống spam tích hợp Gemini AI.")

# Xử lý tin nhắn
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    message = update.message
    user_id = str(message.from_user.id)
    group_id = str(message.chat.id)
    text = message.text.lower()

    # Lấy dữ liệu từ Firebase
    data = ref.child(group_id).get() or {}
    user_data = data.get(user_id, {"count": 0})
    count = user_data["count"]

    # Kiểm tra spam
    if any(keyword in text for keyword in SPAM_KEYWORDS):
        count += 1
        user_data["count"] = count
        data[user_id] = user_data
        ref.child(group_id).set(data)

        if count >= 3:
            await message.reply_text("🚫 Bạn đã bị cấm do spam quá nhiều!")
            await context.bot.ban_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
        else:
            await message.reply_text(f"⚠️ Cảnh báo spam ({count}/3)!")
        return

    # Nếu không spam, gọi Gemini AI
    try:
        await message.chat.send_action(action="typing")
        response = model.generate_content(message.text)
        reply = response.text.strip() if response.text else "🤖 AI không có phản hồi phù hợp."
        await message.reply_text(reply)
    except Exception as e:
        logging.error(f"Lỗi khi gọi Gemini: {e}")
        await message.reply_text("❌ Lỗi khi xử lý yêu cầu AI. Vui lòng thử lại sau.")

# Hàm chính chạy bot
async def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.initialize()
    await application.start()
    print("✅ Bot đang chạy...")
    await application.updater.start_polling()
    await application.updater.idle()

    await application.stop()
    await application.shutdown()

# Khởi động bot
if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except RuntimeError as e:
        if "already running" in str(e):
            print("⚠️ Event loop đã chạy sẵn.")
        else:
            raise
