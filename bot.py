import os

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("TOKEN LENGTH:", len(BOT_TOKEN))
print("CHAT ID:", CHAT_ID)

url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"

print(url[:50] + "...")
