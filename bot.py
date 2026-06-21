import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"

r = requests.get(url)

print(r.text)
