import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"

response = requests.get(url)

print("STATUS =", response.status_code)
print(response.text)
