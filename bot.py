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
CHASZMIN_RSS       = "https://chaszmin.com.ua/category/granty-tut/feed/"
GURT_RSS           = "https://gurt.org.ua/rss/section/grants/"
PROSTIR_RSS        = "https://www.prostir.ua/?feed=rss2&post_type=grants"
GETGRANT_RSS       = "https://getgrant.ua/grants-and-funding/?feed=rss2"
DECENTRALIZATION_RSS = None   # 403 Cloudflare — вимкнено
ISAR_URL           = "https://ednannia.ua/181-contests"
IRF_URL            = "https://www.irf.ua/grants/contests/"
UCF_URL            = "https://ucf.in.ua/programs"
# Фаза 2: нові джерела для ВФ і УМФ
# mva.gov.ua — Міністерство у справах ветеранів, розділ ВФ
# (урядовий сайт, може не мати Cloudflare на GitHub Actions IP)
MVA_URL            = "https://mva.gov.ua/category/141-veteranskiy-fond"
# УМФ — пробуємо RSS та сторінку новин
UMF_RSS            = "https://uyf.gov.ua/rss/"
UMF_NEWS_URL       = "https://uyf.gov.ua/news"

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
    import warnings
    try:
        from bs4 import XMLParsedAsHTMLWarning
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    except ImportError:
        pass
    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"User-Agent": "Mozilla/5.0 ngo-grants-bot/1.0"})
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"[fetch_html] ERROR {url}: {e}")
        return None


UKRAINIAN_MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4,
    "травня": 5, "червня": 6, "липня": 7, "серпня": 8,
    "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
    "січень": 1, "лютий": 2, "березень": 3, "квітень": 4,
    "травень": 5, "червень": 6, "липень": 7, "серпень": 8,
    "вересень": 9, "жовтень": 10, "листопад": 11, "грудень": 12,
}


def is_deadline_passed(deadline_str: str) -> bool:
    """Повертає True, якщо дедлайн вже минув (порівнює з сьогоднішньою датою).

    Розпізнає формати:
    - "1 липня 2026 року" / "1 липня 2026"
    - "01.07.2026" / "01/07/2026" / "01-07-2026"
    - "July 1, 2026" / "1 July 2026"
    Якщо дату розпізнати не вдалось — повертає False (публікуємо на всяк випадок).
    """
    from datetime import date
    import re as _re

    today = date.today()
    text = deadline_str.strip().lower()

    # Формат: "1 липня 2026" або "1 липня 2026 року"
    match = _re.search(
        r"(\d{1,2})\s+(" + "|".join(UKRAINIAN_MONTHS.keys()) + r")\s+(\d{4})",
        text
    )
    if match:
        try:
            day = int(match.group(1))
            month = UKRAINIAN_MONTHS[match.group(2)]
            year = int(match.group(3))
            return date(year, month, day) < today
        except ValueError:
            pass

    # Формат: "01.07.2026" / "01/07/2026" / "01-07-2026"
    match = _re.search(r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})", text)
    if match:
        try:
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return date(year, month, day) < today
        except ValueError:
            pass

    # Формат: "2026-07-01" (ISO)
    match = _re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        try:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return date(year, month, day) < today
        except ValueError:
            pass

    return False  # не вдалось розпізнати — публікуємо


def run_isar(posted_links: set) -> None:
    """ІСАР Єднання: читаємо меню 'Грантові конкурси'.

    Увага: ІСАР не прибирає завершені конкурси з навігаційного меню одразу
    після закриття дедлайну. Тому після завантаження сторінки конкурсу
    перевіряємо дедлайн — якщо він у минулому, конкурс пропускаємо.
    """
    soup = fetch_html(ISAR_URL)
    if not soup:
        return

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
            print(f"[ІСАР] Skipped (фільтр): {title}")
            save_posted_link(link)
            posted_links.add(link)
            continue

        print(f"[ІСАР] Processing: {title}")
        try:
            page = fetch_html(link)
            if not page:
                continue

            page_text = page.get_text(" ", strip=True)

            # Перевіряємо дедлайн — якщо він у минулому, пропускаємо конкурс.
            # extract_deadline повертає рядок типу "1 липня 2026 року" або "01.07.2026".
            # Намагаємось розпізнати дату і порівняти з сьогодні.
            deadline_str = extract_deadline(page_text)
            if deadline_str and is_deadline_passed(deadline_str):
                print(f"[ІСАР] Skipped (дедлайн минув: {deadline_str}): {title}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            # Опис — перший змістовний абзац
            description = ""
            content = page.find("div", class_=re.compile(r"item-page|article|content"))
            if content:
                for p in content.find_all("p"):
                    text = p.get_text(" ", strip=True)
                    if len(text) > 80:
                        description = text[:600]
                        break
            if not description:
                description = title

            msg = f"📌 <b>{title}</b>\n"
            if deadline_str:
                msg += f"📅 <b>Дедлайн:</b> {deadline_str}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">ІСАР Єднання — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
            time.sleep(2)
        except Exception as e:
            print(f"[ІСАР] ERROR {link}: {e}")

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
            time.sleep(2)  # пауза між запитами до сайту
        except Exception as e:
            print(f"[ІСАР] ERROR {link}: {e}")


def run_irf(posted_links: set) -> None:
    """МФ «Відродження»: збираємо активні конкурси.

    МФВ не має RSS. Sitemap захищений або має іншу структуру.
    Стратегія: читаємо сторінку /grants/contests/ і шукаємо
    всі посилання на /contest/... Якщо сторінка повернула
    порожній HTML (JS-рендеринг) — спробуємо sitemap з xml-парсером.
    """
    import xml.etree.ElementTree as ET

    contest_urls = []

    # Спроба 1: сторінка /grants/contests/ — шукаємо посилання
    soup = fetch_html("https://www.irf.ua/grants/contests/")
    if soup:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/contest/" in href:
                if href.startswith("/"):
                    href = "https://www.irf.ua" + href
                if href.startswith("https://www.irf.ua/contest/") and href not in contest_urls:
                    contest_urls.append(href)

    # Спроба 2: sitemap з правильним XML-парсером
    if not contest_urls:
        try:
            import warnings
            from bs4 import XMLParsedAsHTMLWarning
            warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

            r = requests.get(
                "https://www.irf.ua/sitemap.xml",
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 ngo-grants-bot/1.0"}
            )
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                for loc in root.findall(".//sm:loc", ns):
                    url = loc.text.strip() if loc.text else ""
                    if url.startswith("https://www.irf.ua/contest/") and url not in contest_urls:
                        contest_urls.append(url)
        except Exception as e:
            print(f"[МФВ] Sitemap error: {e}")

    if not contest_urls:
        print("[МФВ] Не вдалось знайти конкурси (сторінка і sitemap порожні)")
        return

    print(f"[МФВ] Знайдено {len(contest_urls)} конкурсів")

    for link in contest_urls:
        if link in posted_links:
            continue

        try:
            page = fetch_html(link)
            if not page:
                continue

            h1 = page.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else link

            page_text = page.get_text(" ", strip=True)
            page_text_lower = page_text.lower()

            # Відсіюємо завершені конкурси за текстом
            if (
                "завершення конкурсу" in page_text_lower
                or "конкурс завершено" in page_text_lower
                or "завершений конкурс" in page_text_lower
            ):
                print(f"[МФВ] Skipped (завершений): {title}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            # Відсіюємо за дедлайном
            deadline_str = extract_deadline(page_text)
            if deadline_str and is_deadline_passed(deadline_str):
                print(f"[МФВ] Skipped (дедлайн минув: {deadline_str}): {title}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            # Фільтр тендерів/закупівель
            if is_excluded(title) or is_excluded(page_text[:300]):
                print(f"[МФВ] Skipped (фільтр): {title}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            print(f"[МФВ] Processing: {title}")

            description = ""
            for p in page.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 80 and "завершення конкурсу" not in text.lower():
                    description = text[:600]
                    break
            if not description:
                description = title

            msg = f"📌 <b>{title}</b>\n"
            if deadline_str:
                msg += f"📅 <b>Дедлайн:</b> {deadline_str}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">МФ «Відродження» — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
            time.sleep(2)
        except Exception as e:
            print(f"[МФВ] ERROR {link}: {e}")


# ---------------------------------------------------------------------------
# ДЕДУПЛІКАЦІЯ ЗА ЗАГОЛОВКОМ
# Якщо один грант публікується з двох джерел з однаковою назвою —
# публікуємо лише перший. Зберігаємо нормалізований хеш заголовку
# в окремому файлі posted_titles.txt.
# ---------------------------------------------------------------------------

POSTED_TITLES_FILE = "posted_titles.txt"


def load_posted_titles() -> set:
    try:
        with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as f:
            return set(f.read().splitlines())
    except FileNotFoundError:
        return set()


def title_hash(title: str) -> str:
    """Нормалізований хеш першиx 80 символів заголовку."""
    normalized = re.sub(r"\s+", " ", title.strip().lower())[:80]
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def is_title_duplicate(title: str, posted_titles: set) -> bool:
    return title_hash(title) in posted_titles


def save_title_hash(title: str, posted_titles: set) -> None:
    h = title_hash(title)
    if h not in posted_titles:
        posted_titles.add(h)
        with open(POSTED_TITLES_FILE, "a", encoding="utf-8") as f:
            f.write(h + "\n")


# ---------------------------------------------------------------------------
# УКФ — Український культурний фонд (ucf.in.ua)
# Конкурси публікуються на /programs як картки з назвою та посиланням.
# Платформа власна (не WordPress), без RSS.
# Конкурсів мало (5-10 на сезон), зате всі унікальні.
# ---------------------------------------------------------------------------

def run_ucf(posted_links: set, posted_titles: set) -> None:
    soup = fetch_html(UCF_URL)
    if not soup:
        print("[УКФ] Не вдалось завантажити сторінку програм")
        return

    # Шукаємо посилання на програми/конкурси
    contest_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/m_programs/" in href or "/programs/" in href:
            if href.startswith("/"):
                href = "https://ucf.in.ua" + href
            if href not in contest_links and "ucf.in.ua" in href:
                contest_links.append(href)

    if not contest_links:
        print("[УКФ] Жодного конкурсу не знайдено на сторінці")
        return

    print(f"[УКФ] Знайдено {len(contest_links)} програм")

    for link in contest_links[:15]:  # обмежуємо щоб не спамити при першому запуску
        if link in posted_links:
            continue
        try:
            page = fetch_html(link)
            if not page:
                continue

            h1 = page.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else ""
            if not title:
                continue

            if is_title_duplicate(title, posted_titles):
                print(f"[УКФ] Skipped (дубль заголовку): {title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            if is_excluded(title):
                print(f"[УКФ] Skipped (фільтр): {title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            page_text = page.get_text(" ", strip=True)
            deadline_str = extract_deadline(page_text)
            if deadline_str and is_deadline_passed(deadline_str):
                print(f"[УКФ] Skipped (дедлайн минув: {deadline_str}): {title[:50]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            # Опис — перший змістовний абзац, пропускаємо службові тексти
            # (форма зворотного зв'язку, навігація, короткі підписи)
            UCF_JUNK = [
                "ви можете поставити питання",
                "отримати на нього відповідь",
                "напишіть нам",
                "підписка на новини",
            ]
            description = ""
            for p in page.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) < 100:
                    continue
                if any(j in text.lower() for j in UCF_JUNK):
                    continue
                description = text[:600]
                break
            if not description:
                # Fallback — перший великий div з текстом
                for div in page.find_all(["div", "section"]):
                    text = div.get_text(" ", strip=True)
                    if len(text) > 150 and not any(j in text.lower() for j in UCF_JUNK):
                        description = text[:600]
                        break
            if not description:
                description = title
            msg = f"🎨 <b>{title}</b>\n"
            if deadline_str:
                msg += f"📅 <b>Дедлайн:</b> {deadline_str}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">УКФ — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
                save_title_hash(title, posted_titles)
            time.sleep(2)
        except Exception as e:
            print(f"[УКФ] ERROR {link}: {e}")


# ---------------------------------------------------------------------------
# УМФ — Український молодіжний фонд (uyf.gov.ua)
# Конкурси публікуються на /programs — окремі сторінки по програмах.
# Платформа власна, без RSS.
# ---------------------------------------------------------------------------

def run_umf(posted_links: set, posted_titles: set) -> None:
    """УМФ: сторінка /programs рендериться через JS — requests бачить порожній HTML.
    Стратегія: читаємо RSS новин УМФ (якщо є) або сканує /news на посилання
    типу /programs/[slug] — там публікуються оголошення конкурсів."""

    contest_links = []

    # Спроба 1: RSS новин УМФ
    feed = feedparser.parse("https://uyf.gov.ua/rss/")
    if not feed.entries:
        feed = feedparser.parse("https://uyf.gov.ua/feed/")

    if feed.entries:
        for entry in feed.entries[:20]:
            link = entry.link
            # Відбираємо лише посилання на програми/конкурси
            if "/programs/" in link and link not in contest_links:
                contest_links.append(link)
        print(f"[УМФ] Знайдено {len(contest_links)} конкурсів через RSS")

    # Спроба 2: сторінка новин — там є посилання на програми
    if not contest_links:
        news_soup = fetch_html("https://uyf.gov.ua/news")
        if news_soup:
            for a in news_soup.find_all("a", href=True):
                href = a["href"]
                if "/programs/" in href:
                    if href.startswith("/"):
                        href = "https://uyf.gov.ua" + href
                    if href not in contest_links:
                        contest_links.append(href)
            print(f"[УМФ] Знайдено {len(contest_links)} конкурсів через /news")

    if not contest_links:
        print("[УМФ] Жодного конкурсу не знайдено (JS-рендеринг, RSS недоступний)")
        return

    for link in contest_links[:10]:
        if link in posted_links:
            continue
        try:
            page = fetch_html(link)
            if not page:
                continue

            h1 = page.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else ""
            if not title:
                continue

            if is_title_duplicate(title, posted_titles):
                print(f"[УМФ] Skipped (дубль заголовку): {title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            if is_excluded(title):
                print(f"[УМФ] Skipped (фільтр): {title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            page_text = page.get_text(" ", strip=True)
            deadline_str = extract_deadline(page_text)
            if deadline_str and is_deadline_passed(deadline_str):
                print(f"[УМФ] Skipped (дедлайн минув: {deadline_str}): {title[:50]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            description = ""
            for p in page.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 80:
                    description = text[:600]
                    break
            if not description:
                description = title

            print(f"[УМФ] Processing: {title[:60]}")
            msg = f"🌱 <b>{title}</b>\n"
            if deadline_str:
                msg += f"📅 <b>Дедлайн:</b> {deadline_str}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">УМФ — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
                save_title_hash(title, posted_titles)
            time.sleep(2)
        except Exception as e:
            print(f"[УМФ] ERROR {link}: {e}")


# ---------------------------------------------------------------------------
# ВЕТЕРАНСЬКИЙ ФОНД (veteranfund.com.ua)
# WordPress-сайт. Конкурси на /competitions/ зі списком карток,
# кожен конкурс — окрема сторінка /contests/[slug]/
# ---------------------------------------------------------------------------

def run_veteranfund(posted_links: set, posted_titles: set) -> None:
    soup = fetch_html(VF_URL)
    if not soup:
        print("[ВФ] Не вдалось завантажити сторінку конкурсів")
        return

    contest_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/contests/" in href and href != VF_URL:
            if not href.startswith("http"):
                href = "https://veteranfund.com.ua" + href
            if href not in contest_links:
                contest_links.append(href)

    if not contest_links:
        print("[ВФ] Жодного конкурсу не знайдено на сторінці")
        return

    print(f"[ВФ] Знайдено {len(contest_links)} конкурсів")

    for link in contest_links:
        if link in posted_links:
            continue
        try:
            page = fetch_html(link)
            if not page:
                continue

            h1 = page.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else ""
            if not title:
                continue

            if is_title_duplicate(title, posted_titles):
                print(f"[ВФ] Skipped (дубль заголовку): {title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            if is_excluded(title):
                print(f"[ВФ] Skipped (фільтр): {title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            page_text = page.get_text(" ", strip=True)
            deadline_str = extract_deadline(page_text)
            if deadline_str and is_deadline_passed(deadline_str):
                print(f"[ВФ] Skipped (дедлайн минув: {deadline_str}): {title[:50]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            description = ""
            for p in page.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 80:
                    description = text[:600]
                    break
            if not description:
                description = title

            print(f"[ВФ] Processing: {title[:60]}")
            msg = f"🎖 <b>{title}</b>\n"
            if deadline_str:
                msg += f"📅 <b>Дедлайн:</b> {deadline_str}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">Ветеранський фонд — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
                save_title_hash(title, posted_titles)
            time.sleep(2)
        except Exception as e:
            print(f"[ВФ] ERROR {link}: {e}")


def run_mva(posted_links: set, posted_titles: set) -> None:
    """МВА — Міністерство у справах ветеранів, розділ Ветеранського фонду.
    Публікує новини про відкриття конкурсів ВФ з посиланнями на деталі."""
    soup = fetch_html(MVA_URL)
    if not soup:
        print("[МВА/ВФ] Не вдалось завантажити сторінку")
        return

    # Шукаємо посилання на окремі новини про конкурси
    news_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        # Беремо лише посилання де є слова про конкурс/грант у тексті або URL
        if any(kw in text.lower() or kw in href.lower()
               for kw in ["конкурс", "грант", "варто", "програм", "contest", "grant"]):
            if href.startswith("/"):
                href = "https://mva.gov.ua" + href
            # Пропускаємо навігаційні скорочення (/vartogo, /vartobiznes тощо)
            # Беремо лише повні URL новин (зазвичай довші)
            if "mva.gov.ua" in href and href not in [l for l, _ in news_links]:
                if len(href) > 40:  # навігаційні посилання короткі
                    news_links.append((href, text))

    if not news_links:
        print("[МВА/ВФ] Жодної новини про конкурси не знайдено")
        return

    print(f"[МВА/ВФ] Знайдено {len(news_links)} новин про конкурси")

    for link, nav_text in news_links[:10]:
        if link in posted_links:
            continue

        try:
            page = fetch_html(link)
            if not page:
                continue

            # Беремо реальний заголовок зі сторінки (h1), а не навігаційний текст
            h1 = page.find("h1")
            full_title = h1.get_text(" ", strip=True) if h1 else nav_text
            if not full_title or len(full_title) < 5:
                full_title = nav_text

            # Перевірки за реальним заголовком
            if is_title_duplicate(full_title, posted_titles):
                print(f"[МВА/ВФ] Skipped (дубль): {full_title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue
            if is_excluded(full_title):
                print(f"[МВА/ВФ] Skipped (фільтр): {full_title[:60]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            page_text = page.get_text(" ", strip=True)
            deadline_str = extract_deadline(page_text)
            if deadline_str and is_deadline_passed(deadline_str):
                print(f"[МВА/ВФ] Skipped (дедлайн минув: {deadline_str}): {full_title[:50]}")
                save_posted_link(link)
                posted_links.add(link)
                continue

            description = ""
            for p in page.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 100:
                    description = text[:600]
                    break
            if not description:
                description = full_title

            print(f"[МВА/ВФ] Processing: {full_title[:60]}")
            msg = f"🎖 <b>{full_title}</b>\n"
            if deadline_str:
                msg += f"📅 <b>Дедлайн:</b> {deadline_str}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">Ветеранський фонд — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
                save_title_hash(full_title, posted_titles)
            time.sleep(2)
        except Exception as e:
            print(f"[МВА/ВФ] ERROR {link}: {e}")


def run_umf_phase2(posted_links: set, posted_titles: set) -> None:
    """УМФ Фаза 2: пробуємо RSS і сторінку новин.
    Конкурси УМФ оголошуються через новини з посиланнями на /programs/[slug]."""

    contest_links = []

    # Спроба 1: RSS
    for rss_url in [UMF_RSS, "https://uyf.gov.ua/feed/", "https://uyf.gov.ua/news/feed/"]:
        feed = feedparser.parse(rss_url)
        if feed.entries:
            print(f"[УМФ] RSS працює: {rss_url}, {len(feed.entries)} записів")
            for entry in feed.entries[:20]:
                if "/programs/" in entry.link and entry.link not in contest_links:
                    contest_links.append(entry.link)
            break

    # Спроба 2: HTML сторінки новин
    if not contest_links:
        soup = fetch_html(UMF_NEWS_URL)
        if soup:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/programs/" in href:
                    if href.startswith("/"):
                        href = "https://uyf.gov.ua" + href
                    if href not in contest_links:
                        contest_links.append(href)

    if not contest_links:
        print("[УМФ] Конкурси не знайдено (JS або заблоковано)")
        return

    print(f"[УМФ] Знайдено {len(contest_links)} конкурсів")

    for link in contest_links[:10]:
        if link in posted_links:
            continue
        try:
            page = fetch_html(link)
            if not page:
                continue

            h1 = page.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else ""
            if not title or is_title_duplicate(title, posted_titles) or is_excluded(title):
                save_posted_link(link)
                posted_links.add(link)
                continue

            page_text = page.get_text(" ", strip=True)
            deadline_str = extract_deadline(page_text)
            if deadline_str and is_deadline_passed(deadline_str):
                save_posted_link(link)
                posted_links.add(link)
                continue

            description = ""
            for p in page.find_all("p"):
                text = p.get_text(" ", strip=True)
                if len(text) > 100:
                    description = text[:600]
                    break
            if not description:
                description = title

            print(f"[УМФ] Processing: {title[:60]}")
            msg = f"🌱 <b>{title}</b>\n"
            if deadline_str:
                msg += f"📅 <b>Дедлайн:</b> {deadline_str}\n"
            msg += f"\n{description}\n\n🔗 <a href=\"{link}\">УМФ — джерело</a>\n"

            response = send_telegram_message(msg)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
                save_title_hash(title, posted_titles)
            time.sleep(2)
        except Exception as e:
            print(f"[УМФ] ERROR {link}: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    posted_links = load_posted_links()
    posted_titles = load_posted_titles()

    # RSS-джерела
    run_chaszmin(posted_links)
    run_simple_source(GURT_RSS,     "ГУРТ — джерело",                posted_links)
    run_simple_source(PROSTIR_RSS,  "Громадський Простір — джерело", posted_links)
    run_simple_source(GETGRANT_RSS, "GetGrant — джерело",            posted_links)

    # HTML-скрейпери — загальні
    run_isar(posted_links)
    run_irf(posted_links)

    # HTML-скрейпери — державні фонди
    run_ucf(posted_links, posted_titles)
    run_mva(posted_links, posted_titles)       # Ветеранський фонд через МВА
    run_umf_phase2(posted_links, posted_titles)  # УМФ — фаза 2


if __name__ == "__main__":
    main()
