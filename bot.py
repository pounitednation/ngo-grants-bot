import os
import feedparser
import requests

RSS_URL = "https://chaszmin.com.ua/category/granty-tut/feed/"

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

feed = feedparser.parse(RSS_URL)

if len(feed.entries) == 0:
    print("No entries found")
    exit()

entry = feed.entries[0]

title = entry.title
link = entry.link

message = f"""📢 Новий грант

{title}

🔗 {link}
"""

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message
    }
)

print(response.text)
