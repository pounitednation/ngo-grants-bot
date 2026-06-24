import os
import re
import feedparser
import requests
from bs4 import BeautifulSoup

RSS_URL = "https://chaszmin.com.ua/category/granty-tut/feed/"

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

feed = feedparser.parse(RSS_URL)

if not feed.entries:
print("No entries")
exit()

# Завантажуємо список вже опублікованих грантів

try:
with open("posted_links.txt", "r", encoding="utf-8") as f:
posted_links = set(f.read().splitlines())
except:
posted_links = set()

# Перевіряємо останні 10 грантів

entries = feed.entries[:10]

for entry in reversed(entries):

```
title = entry.title.strip()
link = entry.link

if link in posted_links:
    continue

print(f"Processing: {title}")

try:

    page = requests.get(link, timeout=30)

    soup = BeautifulSoup(page.text, "html.parser")

    article = soup.find("article")

    if article:
        text = article.get_text(" ", strip=True)
    else:
        text = soup.get_text(" ", strip=True)

    # Дедлайн

    deadline = "не зазначено"

    match = re.search(
        r"ДЕДЛАЙН:\s*(.*?)\s*(ДЕ:|ГАЛУЗІ:)",
        text,
        re.IGNORECASE
    )

    if match:
        deadline = match.group(1).strip()

    # Де

    location = "не зазначено"

    match = re.search(
        r"ДЕ:\s*(.*?)\s*ГАЛУЗІ:",
        text,
        re.IGNORECASE
    )

    if match:
        location = match.group(1).strip()

    # Галузі

    sectors = "не зазначено"

    match = re.search(
        r"ГАЛУЗІ:\s*(.*?)(Ми допомагаємо|Сума|Для кого|$)",
        text,
        re.IGNORECASE
    )

    if match:
        sectors = match.group(1).strip()

    # Для кого

    target = ""

    match = re.search(
        r"Для кого[:\s]*(.*?)(Сума|$)",
        text,
        re.IGNORECASE
    )

    if match:
        target = match.group(1).strip()

    # Короткий опис

    summary = ""

    if "Сума" in text:

        after_sum = text.split("Сума", 1)[1]

        paragraphs = re.split(r"\.\s+", after_sum)

        for p in paragraphs:

            p = p.strip()

            if len(p) < 80:
                continue

            if "Ми допомагаємо" in p:
                continue

            if "Замовити" in p:
                continue

            if "Подати заявку" in p:
                continue

            if "ШКОЛА ГРАНТОЗНАВСТВА" in p:
                continue

            summary = p
            break

    if not summary:
        summary = title

    if len(summary) > 800:
        summary = summary[:800] + "..."

    message = f"""
```

🌍 <b>{title}</b>

📅 <b>Дедлайн:</b> {deadline}

🌍 <b>Де:</b> {location}

🎯 <b>Галузі:</b> {sectors}
"""

```
    if target:
        message += f"""
```

👥 <b>Для кого:</b>
{target}
"""

```
    message += f"""
```

💡 <b>Коротко:</b>

{summary}

🔗 <a href="{link}">Деталі гранту</a>
"""

```
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

        with open("posted_links.txt", "a", encoding="utf-8") as f:
            f.write(link + "\n")

except Exception as e:
    print(f"ERROR: {e}")
    continue
