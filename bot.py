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
except FileNotFoundError:
    posted_links = set()

# Перевіряємо останні 10 грантів
entries = feed.entries[:10]

for entry in reversed(entries):
    title = entry.title.strip()
    link = entry.link

    if link in posted_links:
        continue

    print(f"Processing: {title}")

    try:
        page = requests.get(link, timeout=30)
        soup = BeautifulSoup(page.text, "html.parser")
        article = soup.find("article")
        text = article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)

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

        # Маркери сторонніх рекламних блоків, які треба відкидати
        junk_markers = [
            "ПІДРУЧНИК", "ПОСІБНИК", "ПОРАДНИК", "КАТАЛОГ ФОНДІВ",
            "ШКОЛА ГРАНТОЗНАВСТВА", "Подати заявку ТУТ", "HOW TO GET",
            "Можливо, ви захочете", "Замовити оформлення",
            "Ми допомагаємо в оформленні"
        ]

        def is_junk(sentence):
            return any(marker.lower() in sentence.lower() for marker in junk_markers)

        # Для кого — беремо абзац-пояснення одразу після заголовка "Для кого",
        # до наступного заголовка ("До участі допускаються" / "Сума" / "Дедлайн")
        target = ""
        match = re.search(
            r"Для кого[:\s]*(.*?)(До участі допускаються|Сума|Дедлайн[:\s]|$)",
            text,
            re.IGNORECASE
        )
        if match:
            raw_target = match.group(1).strip()
            sentences = re.split(r"(?<=[.!?])\s+", raw_target)
            clean_sentences = []
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if is_junk(s):
                    break
                clean_sentences.append(s)
            target = " ".join(clean_sentences).strip()
            if len(target) > 400:
                target = target[:400] + "..."

        # Деталі / короткий опис — перший змістовний абзац вступного тексту.
        # Він йде після рекламного блоку ("Подати заявку ТУТ" / "ЗАМОВИТИ ОФОРМЛЕННЯ...")
        # і до заголовка "Для кого".
        summary = ""
        search_zone = text

        # Відрізаємо все ДО рекламного маркера на початку сторінки
        # (ДЕДЛАЙН/ДЕ/ГАЛУЗІ + "Ми допомагаємо" + кнопка замовлення) —
        # опис гранту починається після нього.
        # Шукаємо лише в межах тексту ДО заголовка "Для кого" (там можуть бути
        # повторні згадки "Подати заявку ТУТ" вже після Суми/Дедлайну).
        for_kogo_match = re.search(r"Для кого", search_zone, re.IGNORECASE)
        for_kogo_pos = for_kogo_match.start() if for_kogo_match else len(search_zone)

        intro_markers = [
            r"Замовити оформлення грантової заявки",
            r"Подати заявку ТУТ",
        ]
        last_cut = 0
        head_zone = search_zone[:for_kogo_pos]
        for marker in intro_markers:
            m = list(re.finditer(marker, head_zone, re.IGNORECASE))
            if m:
                last_cut = max(last_cut, m[-1].end())

        search_zone = search_zone[last_cut:for_kogo_pos]

        paragraphs = re.split(r"(?<=[.!?])\s+", search_zone)
        for p in paragraphs:
            p = p.strip()
            if len(p) < 80:
                continue
            if is_junk(p):
                continue
            summary = p
            break

        if not summary:
            summary = title
        if len(summary) > 800:
            summary = summary[:800] + "..."

        message = f"""
🌍 <b>{title}</b>
📅 <b>Дедлайн:</b> {deadline}
🌍 <b>Де:</b> {location}
🎯 <b>Галузі:</b> {sectors}
"""
        if target:
            message += f"""
👥 <b>Для кого:</b>
{target}
"""
        message += f"""
💡 <b>Деталі:</b>
{summary}
🔗 <a href="{link}">Деталі гранту</a>
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
            with open("posted_links.txt", "a", encoding="utf-8") as f:
                f.write(link + "\n")

    except Exception as e:
        print(f"ERROR processing {link}: {e}")
        continue
