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

# Отримуємо сторінку гранту
page = requests.get(link, timeout=30)
soup = BeautifulSoup(page.text, "html.parser")

text = soup.get_text(" ", strip=True)

# -------------------------
# ОЧИЩЕННЯ РЕКЛАМИ
# -------------------------

bad_phrases = [
    "Ми допомагаємо в оформленні",
    "Замовити оформлення грантової заявки",
    "ШКОЛА ГРАНТОЗНАВСТВА",
    "Подати заявку ТУТ",
]

for phrase in bad_phrases:
    if phrase in text:
        text = text.split(phrase)[0]

# -------------------------
# КОРОТКИЙ ОПИС
# -------------------------

summary = text[:450]

last_dot = summary.rfind(".")
if last_dot > 200:
    summary = summary[:last_dot + 1]

# -------------------------
# ПОШУК ДЕДЛАЙНУ
# -------------------------

deadline = "не зазначено"

deadline_patterns = [
    r"Deadline:\s*([^\n\.]+)",
    r"Дедлайн[:\s]*([^\n\.]+)",
    r"Closing Date[:\s]*([^\n\.]+)",
]

for pattern in deadline_patterns:
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        deadline = match.group(1).strip()
        break

# -------------------------
# ПОШУК СУМИ
# -------------------------

amount = "не зазначено"

amount_patterns = [
    r"\$[\d,]+",
    r"€[\d,]+",
    r"£[\d,]+",
    r"USD\s*[\d,]+",
    r"EUR\s*[\d,]+",
    r"up to\s*\$[\d,]+",
    r"up to\s*€[\d,]+",
]

for pattern in amount_patterns:
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        amount = match.group(0)
        break

# -------------------------
# ФОРМУВАННЯ ПОВІДОМЛЕННЯ
# -------------------------

message = f"""
🌍 <b>{title}</b>

{summary}

📢 <b>Відкрито прийом заявок</b>

📅 <b>Дедлайн:</b>
{deadline}

💰 <b>Фінансування:</b>
{amount}

🇺🇦 <b>Для України:</b>
Участь доступна для українських організацій та заявників відповідно до умов конкурсу.

🔗 <a href="{link}">Деталі конкурсу</a>
"""

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
)

print(response.text)

if response.status_code == 200:
    with open("last_post.txt", "w", encoding="utf-8") as f:
        f.write(link)
