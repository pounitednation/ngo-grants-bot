import os

print("TOKEN EXISTS:", bool(os.getenv("TELEGRAM_TOKEN")))
print("CHAT EXISTS:", bool(os.getenv("TELEGRAM_CHAT_ID")))
