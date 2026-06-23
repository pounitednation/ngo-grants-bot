```python
import os
import re
import feedparser
import requests
from bs4 import BeautifulSoup

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

# Завантаження сторінки гранту
description = ""
deadline = ""
donor = ""

try:
    page = requests.get(link, timeout=20)
    soup = BeautifulSoup(page.text, "lxml")

    paragraphs = soup.find_all("p")

    for p in paragraphs:
        text = p.get_text(" ", strip=True)

        if len(text) > 80:
            description = text[:400]
            break

    page_text = soup.get_text(" ", strip=True)

    deadline_patterns = [
        r"Deadline:\s*([^.]+)",
        r"Дедлайн:\s*([^.]+)",
        r"Deadline Date:\s*([^.]+)"
    ]

    for pattern in deadline_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            deadline = match.group(1).strip()
            break

    if "European Commission" in page_text:
        donor = "European Commission"
    elif "UNDP" in page_text:
        donor = "UNDP"
    elif "UNHCR" in page_text:
        donor = "UNHCR"

except Exception as e:
    print(e)

message = f"🌍 <b>{title}</b>\n\n"

if description:
    message += f"{description}\n\n"

message += "📢 <b>Відкрито прийом заявок</b>\n\n"

if deadline:
    message += f"🗓 <b>Дедлайн:</b>\n{deadline}\n\n"

if donor:
    message += f"🏢 <b>Донор:</b>\n{donor}\n\n"

message += """🇺🇦 <b>Для України:</b>
Участь доступна для українських організацій та заявників.

🔗 <a href="{0}">Деталі конкурсу</a>
""".format(link)

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
```
