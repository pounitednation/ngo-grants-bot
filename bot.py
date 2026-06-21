import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

print("TOKEN LENGTH:", len(BOT_TOKEN))

url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"

response = requests.get(url)

print(response.text)
