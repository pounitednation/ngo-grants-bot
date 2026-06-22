import os
import feedparser
import requests

RSS_URL = "https://chaszmin.com.ua/category/granty-tut/feed/"

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

feed = feedparser.parse(RSS_URL)

if len(feed.entries) == 0:
    print("No entries")
    exit()

entry = feed.entries[0]

title = entry.title.strip()
link = entry.link

try:
    with open("last_post.txt", "r", encoding="utf-8") as f:
        last_link = f.read().strip()
except:
    last_link = ""

if link == last_link:
    print("Already posted")
    exit()

message = f"""
🌍 <b>{title}</b>

📌 Нова грантова можливість

🔗 <a href="{link}">Детальніше</a>
"""

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
)

print(response.text)

if response.status_code == 200:
    with open("last_post.txt", "w", encoding="utf-8") as f:
        f.write(link)
