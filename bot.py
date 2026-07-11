import os
import re
import time
import hashlib
import feedparser
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
POSTED_LINKS_FILE = "posted_links.txt"

# ---------------------------------------------------------------------------
# ДЖЕРЕЛА
# ---------------------------------------------------------------------------
CHASZMIN_RSS  = "https://chaszmin.com.ua/category/granty-tut/feed/"
GURT_RSS      = "https://gurt.org.ua/rss/section/grants/"
PROSTIR_RSS   = "https://www.prostir.ua/?feed=rss2&post_type=grants"
GETGRANT_RSS  = "https://getgrant.ua/grants-and-funding/?feed=rss2"
ISAR_URL      = "https://ednannia.ua/181-contests"
IRF_URL       = "https://www.irf.ua/grants/contests/"

# ---------------------------------------------------------------------------
# ФІЛЬТРИ — тендери / закупівлі / вакансії-консультантів
# ---------------------------------------------------------------------------
EXCLUDE_KEYWORDS = [
    "тендер", "закупівл", "запит цінових пропозицій", "зцп", "rfq", "rfp",
    "rfi", "itb", "цінової пропозиції", "тендерн", "постачання", "поставк",
    "цінову пропозицію", "цінові пропозиції", "цінових пропозицій",
    "конкурсні торги", "разовий договір", "разового договору",
    "постачальник", "оцінка цінових пропозицій",
    "місцева закупівля", "procurement", "запрошує подати пропозиц",
    "запрошує надати пропозиц", "надати цінову пропозиц",
    "запрошує кваліфікованих виконавц", "запрошує постачальник",
    # вакансії консультантів/експертів
    "пошук експерта", "пошук експертки", "пошук експерт",
    "запрошує експерта", "запрошує консультант",
    "набір консультант", "набір тренер",
    "вакансія", "вакансії", "job opening", "position available",
    # GetGrant-специфічні не-грантові матеріали:
    # самореклама, аналітика, освітні статті, звіти про заходи
    "appeared first on getgrant",   # хвіст WordPress-постів блогу
    "getgrant отримав",             # новини про самих GetGrant
    "getgrant service отримав",
    "summit grant fest",            # репортаж про захід
    "мав честь бути запрошеним",   # особиста нотатка
    "анатомія робочих пакетів",    # навчальна стаття
    "грантова звітність у horizon", # навчальна стаття
    "living guidelines",            # аналітика про ЄС-документи
]

EXCLUDE_ORGANIZATIONS = [
    "конвіктус україна",
]


def is_excluded(text: str) -> bool:
    t = text.lower()
    return (
        any(kw in t for kw in EXCLUDE_KEYWORDS)
        or any(org in t for org in EXCLUDE_ORGANIZATIONS)
    )


# ---------------------------------------------------------------------------
# ТРЕКІНГ ОПУБЛІКОВАНИХ ПОСИЛАНЬ
# ---------------------------------------------------------------------------

def load_posted_links() -> set:
    try:
        with open(POSTED_LINKS_FILE, "r", encoding="utf-8") as f:
            return set(f.read().splitlines())
    except FileNotFoundError:
        return set()


def save_posted_link(link: str) -> None:
    with open(POSTED_LINKS_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")


# ---------------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------------

def send_telegram_message(message: str) -> requests.Response:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
    )
    print(response.text)
    return response


# ---------------------------------------------------------------------------
# CHASZMIN — повний формат (Дедлайн / Де / Галузі / Для кого / Деталі)
# ---------------------------------------------------------------------------

JUNK_MARKERS = [
    "ПІДРУЧНИК", "ПОСІБНИК", "ПОРАДНИК", "КАТАЛОГ ФОНДІВ",
    "ШКОЛА ГРАНТОЗНАВСТВА", "Подати заявку ТУТ", "HOW TO GET",
    "Можливо, ви захочете", "Замовити оформлення",
    "Ми допомагаємо в оформленні",
]


def is_junk(sentence: str) -> bool:
    return any(marker.lower() in sentence.lower() for marker in JUNK_MARKERS)


def process_chaszmin_entry(title: str, link: str) -> str:
    page = requests.get(link, timeout=30)
    soup = BeautifulSoup(page.text, "html.parser")
    article = soup.find("article")
    text = article.get_text(" ", strip=True) if article else soup.get_text(" ", strip=True)

    deadline = "не зазначено"
    match = re.search(r"ДЕДЛАЙН:\s*(.*?)\s*(ДЕ:|ГАЛУЗІ:)", text, re.IGNORECASE)
    if match:
        deadline = match.group(1).strip()

    location = "не зазначено"
    match = re.search(r"ДЕ:\s*(.*?)\s*ГАЛУЗІ:", text, re.IGNORECASE)
    if match:
        location = match.group(1).strip()

    sectors = "не зазначено"
    match = re.search(r"ГАЛУЗІ:\s*(.*?)(Ми допомагаємо|Сума|Для кого|$)", text, re.IGNORECASE)
    if match:
        sectors = match.group(1).strip()

    target = ""
    match = re.search(
        r"Для кого[:\s]*(.*?)(До участі допускаються|Сума|Дедлайн[:\s]|$)",
        text, re.IGNORECASE,
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

    search_zone = text
    for_kogo_match = re.search(r"Для кого", search_zone, re.IGNORECASE)
    for_kogo_pos = for_kogo_match.start() if for_kogo_match else len(search_zone)

    intro_markers = [r"Замовити оформлення грантової заявки", r"Подати заявку ТУТ"]
    last_cut = 0
    head_zone = search_zone[:for_kogo_pos]
    for marker in intro_markers:
        m = list(re.finditer(marker, head_zone, re.IGNORECASE))
        if m:
            last_cut = max(last_cut, m[-1].end())
    search_zone = search_zone[last_cut:for_kogo_pos]

    summary = ""
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
    return message


def run_chaszmin(posted_links: set) -> None:
    feed = feedparser.parse(CHASZMIN_RSS)
    if not feed.entries:
        print("[chaszmin] No entries")
        return
    for entry in reversed(feed.entries[:10]):
        title = entry.title.strip()
        link = entry.link
        if link in posted_links:
            continue
        if is_excluded(title):
            print(f"[chaszmin] Skipped: {title}")
            save_posted_link(link)
            posted_links.add(link)
            continue
        print(f"[chaszmin] Processing: {title}")
        try:
            message = process_chaszmin_entry(title, link)
            response = send_telegram_message(message)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
        except Exception as e:
            print(f"[chaszmin] ERROR {link}: {e}")


# ---------------------------------------------------------------------------
# СПІЛЬНІ УТИЛІТИ ДЛЯ RSS-ДЖЕРЕЛ (GURT / PROSTIR / GETGRANT)
# ---------------------------------------------------------------------------

DEADLINE_PATTERNS = [
    r"[Дд]едлайн[а-яіїєʼ'\s:]*[:\s]+([^.\n]{3,80})",
    r"[Кк]інцевий термін[а-яіїєʼ'\s]*[:\s]+([^.\n]{3,80})",
    r"[Тт]ермін подачі[а-яіїєʼ'\s]*[:\s]+([^.\n]{3,80})",
    r"[Тт]ермін подання[а-яіїєʼ'\s]*[:\s]+([^.\n]{3,80})",
]


def extract_deadline(text: str) -> str:
    for pattern in DEADLINE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip().rstrip(".,;")
    return ""


def clean_html_description(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


DIGEST_SPLIT_PATTERN = re.compile(r"\s*>{2,}\s*|\s*›{2,}\s*")


def split_digest_into_items(description: str) -> list:
    parts = DIGEST_SPLIT_PATTERN.split(description)
    items = [p.strip() for p in parts if p.strip()]
    return items if items else [description.strip()]


def make_item_title(item_text: str, fallback_title: str, max_len: int = 90) -> str:
    first_sentence = re.split(r"(?<=[.!?])\s+", item_text.strip())[0].strip()
    if not first_sentence:
        return fallback_title
    if len(first_sentence) > max_len:
        first_sentence = first_sentence[:max_len].rstrip() + "..."
    return first_sentence


def build_simple_message(item_title: str, link: str, description: str, source_label: str) -> str:
    deadline = extract_deadline(description)
    summary = description[:600] + "..." if len(description) > 600 else description
    message = f"📌 <b>{item_title}</b>\n"
    if deadline:
        message += f"📅 <b>Дедлайн:</b> {deadline}\n"
    message += f"\n{summary}\n\n🔗 <a href=\"{link}\">{source_label}</a>\n"
    return message


def run_simple_source(rss_url: str, source_label: str, posted_links: set, limit: int = 20) -> None:
    feed = feedparser.parse(rss_url)
    if not feed.entries:
        print(f"[{source_label}] No entries")
        return

    for entry in reversed(feed.entries[:limit]):
        post_title = entry.title.strip()
        link = entry.link
        raw_description = getattr(entry, "description", "") or getattr(entry, "summary", "")
        description = clean_html_description(raw_description)
        if not description:
            description = post_title

        # Фільтр за RSS-заголовком ще до розбиття на пункти
        if is_excluded(post_title):
            item_key = f"{link}#0"
            if item_key not in posted_links:
                print(f"[{source_label}] Skipped by title: {post_title}")
                save_posted_link(item_key)
                posted_links.add(item_key)
            continue

        items = split_digest_into_items(description)

        for idx, item_text in enumerate(items):
            item_key = f"{link}#{idx}"
            if item_key in posted_links:
                continue

            item_title = make_item_title(item_text, post_title)

            if is_excluded(post_title) or is_excluded(item_title) or is_excluded(item_text):
                print(f"[{source_label}] Skipped item: {item_title}")
                save_posted_link(item_key)
                posted_links.add(item_key)
                continue

            print(f"[{source_label}] Processing: {item_title}")
            try:
                message = build_simple_message(item_title, link, item_text, source_label)
                response = send_telegram_message(message)
                if response.status_code == 200:
                    save_posted_link(item_key)
                    posted_links.add(item_key)
            except Exception as e:
                print(f"[{source_label}] ERROR {item_key}: {e}")


# ---------------------------------------------------------------------------
# HTML-СКРЕЙПЕРИ (ІСАР Єднання / МФ «Відродження»)
# Ці сайти не мають RSS, тому читаємо список активних конкурсів напряму.
# Унікальний ключ — нормалізований URL сторінки конкурсу.
# ---------------------------------------------------------------------------

def fetch_html(url: str, timeout: int = 30) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": "Mozilla/5.0 ngo-grants-bot/1.0"})
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[fetch_html] ERROR {url}: {e}")
        return None


def run_isar(posted_links: set) -> None:
    """ІСАР Єднання: читаємо меню 'Грантові конкурси' — кожен пункт = окремий конкурс."""
    soup = fetch_html(ISAR_URL)
    if not soup:
        return

    # Навігація містить всі активні конкурси як пункти підменю
    # href-и виду: /tryvaiut-hrantovi-konkursy/...
    links_found = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "tryvaiut-hrantovi-konkursy/" in href and href != "/tryvaiut-hrantovi-konkursy":
            if href.startswith("/"):
                href = "https://ednannia.ua" + href
            links_found.add((href, a.get_text(strip=True)))

    for link, title in sorted(links_found):
        if not title or len(title) < 5:
            continue
        if link in posted_links:
            continue
        if is_excluded(title) or is_excluded(link):
            print(f"[ІСАР] Skipped: {title}")
            save_posted_link(link)
            posted_links.add(link)
            continue

        print(f"[ІСАР] Processing: {title}")
        try:
            # Заходимо на сторінку конкурсу за коротким описом
            page = fetch_html(link)
            description = ""
            if page:
                content = page.find("div", class_=re.compile(r"item-page|article|content"))
                if content:
                    paragraphs = content.find_all("p")
                    for p in paragraphs:
                        text = p.get_text(" ", strip=True)
                        if len(text) > 80:
                            description = text[:600]
                            break
            if not description:
                description = title

            deadline = extract_deadline(description)
            msg = f"📌 <b>{title}</b>\n"
            if deadline:
                msg += f"📅 <b>Дедлайн:</b> {deadline}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">ІСАР Єднання — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
            time.sleep(2)  # пауза між запитами до сайту
        except Exception as e:
            print(f"[ІСАР] ERROR {link}: {e}")


def run_irf(posted_links: set) -> None:
    """МФ «Відродження»: читаємо сторінку активних конкурсів.

    Проблеми, які вирішуємо тут:
    1. Сторінка /grants/contests/ рендерить картки через JS —
       requests бачить лише FAQ-блок без жодного посилання на конкурс.
       Тому читаємо /contest/ сторінки через sitemap або пошук на сайті.
    2. Завершені конкурси треба відсівати за наявністю слова
       "ЗАВЕРШЕННЯ КОНКУРСУ" в заголовку або тексті картки.
    3. get_text() без роздільника дає злиплий текст —
       використовуємо separator=" ".
    """
    # МФВ має XML-карту сайту з усіма конкурсами
    SITEMAP_URL = "https://www.irf.ua/sitemap.xml"
    soup = fetch_html(SITEMAP_URL)
    if not soup:
        print("[МФВ] Не вдалось завантажити sitemap")
        return

    # У sitemap шукаємо URL вигляду /contest/...
    contest_urls = []
    for loc in soup.find_all("loc"):
        url = loc.get_text(strip=True)
        if "/contest/" in url and url.startswith("https://www.irf.ua/contest/"):
            contest_urls.append(url)

    if not contest_urls:
        print("[МФВ] Жодного конкурсу в sitemap не знайдено")
        return

    for link in contest_urls:
        if link in posted_links:
            continue

        # Завантажуємо сторінку конкурсу
        try:
            page = fetch_html(link)
            if not page:
                continue

            # Заголовок конкурсу — тег h1
            h1 = page.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else link

            # Відсіюємо завершені конкурси
            # (МФВ часто показує завершені конкурси в sitemap)
            page_text_lower = page.get_text(" ", strip=True).lower()
            if (
                "завершення конкурсу" in page_text_lower
                or "конкурс завершено" in page_text_lower
                or "завершений конкурс" in page_text_lower
            ):
                print(f"[МФВ] Skipped (завершений): {title}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            if is_excluded(title):
                print(f"[МФВ] Skipped (фільтр): {title}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            print(f"[МФВ] Processing: {title}")

            # Опис — перший змістовний абзац основного контенту
            description = ""
            for p in page.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 80 and "завершення конкурсу" not in text.lower():
                    description = text[:600]
                    break
            if not description:
                description = title

            deadline = extract_deadline(page.get_text(" ", strip=True))
            msg = f"📌 <b>{title}</b>\n"
            if deadline:
                msg += f"📅 <b>Дедлайн:</b> {deadline}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">МФ «Відродження» — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
            time.sleep(2)
        except Exception as e:
            print(f"[МФВ] ERROR {link}: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    posted_links = load_posted_links()

    # RSS-джерела
    run_chaszmin(posted_links)
    run_simple_source(GURT_RSS,     "ГУРТ — джерело",              posted_links)
    run_simple_source(PROSTIR_RSS,  "Громадський Простір — джерело", posted_links)
    run_simple_source(GETGRANT_RSS, "GetGrant — джерело",           posted_links)

    # HTML-скрейпери
    run_isar(posted_links)
    run_irf(posted_links)


if __name__ == "__main__":
    main()
