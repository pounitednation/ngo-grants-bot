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
    # Завантажуємо сторінку гранту
    page = requests.get(link, timeout=30)

    soup = BeautifulSoup(page.text, "html.parser")

    article = soup.find("article")

    if article:
        text = article.get_text(" ", strip=True)
    else:
        text = soup.get_text(" ", strip=True)

    # Відсікаємо меню сайту до слова ДЕДЛАЙН
    if "ДЕДЛАЙН:" in text:
        text = text[text.find("ДЕДЛАЙН:"):]

    # -------------------------
    # ОЧИЩЕННЯ РЕКЛАМИ
    # -------------------------

    bad_phrases = [
        "Ми допомагаємо в оформленні",
        "Замовити оформлення грантової заявки",
        "ШКОЛА ГРАНТОЗНАВСТВА",
        "Подати заявку ТУТ",
        "Консультація",
        "Грантова заявка",
    ]

    for phrase in bad_phrases:
        if phrase in text:
            text = text.split(phrase)[0]

    # -------------------------
    # КОРОТКИЙ ОПИС
    # -------------------------

    summary = ""

    paragraphs = re.split(r"\.\s+", text)

    for p in paragraphs:

        p = p.strip()

        if len(p) < 50:
            continue

        if "ДЕДЛАЙН" in p:
            continue

        if "ДЕ:" in p:
            continue

        if "ГАЛУЗІ:" in p:
            continue

        if "Подати заявку" in p:
            continue

        if "Ми допомагаємо" in p:
            continue

        summary = p
        break

    if not summary:
        summary = title

    if len(summary) > 450:
        summary = summary[:450] + "..."

    # -------------------------
    # ПОШУК ДЕДЛАЙНУ
    # -------------------------

    deadline = "не зазначено"

    match = re.search(
        r"ДЕДЛАЙН:\s*(.*?)\s*(ДЕ:|ГАЛУЗІ:)",
        text,
        re.IGNORECASE
    )

    if match:
        deadline = match.group(1).strip()

    # -------------------------
    # ПОШУК СУМИ
    # -------------------------

    amount = "не зазначено"

    amount_patterns = [
        r"до\s*\$[\d\s,\.]+",
        r"до\s*€[\d\s,\.]+",
        r"до\s*£[\d\s,\.]+",
        r"\$[\d\s,\.]+",
        r"€[\d\s,\.]+",
        r"£[\d\s,\.]+",
        r"USD\s*[\d\s,\.]+",
        r"EUR\s*[\d\s,\.]+",
        r"грн\.?\s*[\d\s,\.]+",
    ]

    for pattern in amount_patterns:

        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            amount = match.group(0).strip()
            break

    # -------------------------
    # ПОВІДОМЛЕННЯ
    # -------------------------

    message = f"""
```

🌍 <b>{title}</b>

{summary}

📢 <b>Відкрито прийом заявок</b>

📅 <b>Дедлайн:</b> {deadline}

💰 <b>Фінансування:</b> {amount}

🇺🇦 <b>Для України:</b>
Участь доступна для українських організацій та заявників відповідно до умов конкурсу.

🔗 <a href="{link}">Деталі конкурсу</a>
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
