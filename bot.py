import os
import re
import feedparser
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
POSTED_LINKS_FILE = "posted_links.txt"

# Джерела
CHASZMIN_RSS = "https://chaszmin.com.ua/category/granty-tut/feed/"
GURT_RSS = "https://gurt.org.ua/rss/section/grants/"
PROSTIR_RSS = "https://www.prostir.ua/?feed=rss2&post_type=grants"

# Ключові слова, за якими відсіюємо тендери/закупівлі техніки/послуг
# на сайтах, де гранти й тендери змішані в одній стрічці (GURT, Prostir.ua).
# На Prostir.ua тендери часто маскуються під нейтральні заголовки
# ("Організація запрошує...", "Асоціація... запрошує...") — слова
# "тендер"/"закупівля" там часто немає взагалі ні в заголовку, ні в
# description, тож додано специфічну термінологію цінових тендерів:
# "Постачальник", "разовий договір", "цінова пропозиція", "Замовник",
# "конкурсні торги" тощо.
EXCLUDE_KEYWORDS = [
    "тендер", "закупівл", "запит цінових пропозицій", "зцп", "rfq", "rfp",
    "rfi", "itb", "цінової пропозиції", "тендерн", "постачання", "поставк",
    "цінову пропозицію", "цінові пропозиції", "цінових пропозицій",
    "конкурсні торги", "разовий договір", "разового договору",
    "постачальник", "оцінка цінових пропозицій",
    "місцева закупівля", "procurement", "запрошує подати пропозиц",
    "запрошує надати пропозиц", "надати цінову пропозиц",
    "запрошує кваліфікованих виконавц", "запрошує постачальник",
]


def is_excluded_title(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EXCLUDE_KEYWORDS)


def is_excluded_text(text: str) -> bool:
    """Перевіряє повний текст пункту (без обмеження довжини) — деякі
    маркери тендеру можуть стояти не на початку абзацу."""
    t = text.lower()
    return any(kw in t for kw in EXCLUDE_KEYWORDS)


# Деякі організації на Prostir.ua систематично публікують ЛИШЕ тендери
# на закупівлю товарів/послуг (а не гранти), і їхній RSS-уривок іноді
# обрізається ще до того, як з'являється слово "тендер"/"конкурсні торги".
# У такому випадку фільтр за ключовими словами в тексті спрацювати не
# встигає — тож такі організації відсіюємо за згадкою назви напряму.
EXCLUDE_ORGANIZATIONS = [
    "конвіктус україна",
]


def is_excluded_organization(text: str) -> bool:
    t = text.lower()
    return any(org in t for org in EXCLUDE_ORGANIZATIONS)


def load_posted_links() -> set:
    try:
        with open(POSTED_LINKS_FILE, "r", encoding="utf-8") as f:
            return set(f.read().splitlines())
    except FileNotFoundError:
        return set()


def save_posted_link(link: str) -> None:
    with open(POSTED_LINKS_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")


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

    # Дедлайн
    deadline = "не зазначено"
    match = re.search(r"ДЕДЛАЙН:\s*(.*?)\s*(ДЕ:|ГАЛУЗІ:)", text, re.IGNORECASE)
    if match:
        deadline = match.group(1).strip()

    # Де
    location = "не зазначено"
    match = re.search(r"ДЕ:\s*(.*?)\s*ГАЛУЗІ:", text, re.IGNORECASE)
    if match:
        location = match.group(1).strip()

    # Галузі
    sectors = "не зазначено"
    match = re.search(
        r"ГАЛУЗІ:\s*(.*?)(Ми допомагаємо|Сума|Для кого|$)", text, re.IGNORECASE
    )
    if match:
        sectors = match.group(1).strip()

    # Для кого — абзац-пояснення одразу після заголовка "Для кого",
    # до наступного заголовка ("До участі допускаються" / "Сума" / "Дедлайн")
    target = ""
    match = re.search(
        r"Для кого[:\s]*(.*?)(До участі допускаються|Сума|Дедлайн[:\s]|$)",
        text,
        re.IGNORECASE,
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

    # Деталі — перший змістовний абзац вступного тексту: після рекламного
    # блоку ("Подати заявку ТУТ" / "ЗАМОВИТИ ОФОРМЛЕННЯ...") і до "Для кого"
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

    entries = feed.entries[:10]
    for entry in reversed(entries):
        title = entry.title.strip()
        link = entry.link

        if link in posted_links:
            continue

        print(f"[chaszmin] Processing: {title}")

        try:
            message = process_chaszmin_entry(title, link)
            response = send_telegram_message(message)
            if response.status_code == 200:
                save_posted_link(link)
                posted_links.add(link)
        except Exception as e:
            print(f"[chaszmin] ERROR processing {link}: {e}")
            continue


# ---------------------------------------------------------------------------
# GURT / PROSTIR — спрощений формат (назва + короткий опис + дедлайн якщо
# знайдеться + лінк). Контент тут не структурований, тож деталі й "для кого"
# беремо лише в межах вже готового короткого опису з самого RSS.
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
    """Прибирає HTML-теги й зайві пробіли з опису фіда (description/summary)."""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Дайджести ГУРТ і Prostir.ua часто містять кілька грантів/тендерів/вакансій
# в одному RSS-пості, розділених послідовністю ">>>>" (чи її варіаціями
# на кшталт "> > > >", "››››" тощо — на випадок дрібних відмінностей вёрстки)
DIGEST_SPLIT_PATTERN = re.compile(r"\s*>{2,}\s*|\s*›{2,}\s*")


def split_digest_into_items(description: str) -> list:
    """Розбиває текст дайджесту на окремі смислові пункти.

    Якщо роздільника немає — повертає весь текст як один пункт
    (звичайна, не-дайджест новина).
    """
    parts = DIGEST_SPLIT_PATTERN.split(description)
    items = [p.strip() for p in parts if p.strip()]
    return items if items else [description.strip()]


def make_item_title(item_text: str, fallback_title: str, max_len: int = 90) -> str:
    """Заголовок для окремого пункту дайджесту — перше речення тексту."""
    first_sentence = re.split(r"(?<=[.!?])\s+", item_text.strip())[0].strip()
    if not first_sentence:
        return fallback_title
    if len(first_sentence) > max_len:
        first_sentence = first_sentence[:max_len].rstrip() + "..."
    return first_sentence


def build_simple_message(item_title: str, link: str, description: str, source_label: str) -> str:
    deadline = extract_deadline(description)

    summary = description
    if len(summary) > 600:
        summary = summary[:600] + "..."

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

    entries = feed.entries[:limit]
    for entry in reversed(entries):
        post_title = entry.title.strip()
        link = entry.link

        raw_description = getattr(entry, "description", "") or getattr(entry, "summary", "")
        description = clean_html_description(raw_description)
        if not description:
            description = post_title

        # Фільтруємо за реальним RSS-заголовком ще ДО розбиття на пункти:
        # якщо сам заголовок запису — тендер, весь пост відкидаємо одразу
        if (
            is_excluded_title(post_title)
            or is_excluded_text(post_title)
            or is_excluded_organization(post_title)
        ):
            item_key = f"{link}#post"
            if item_key not in posted_links:
                print(f"[{source_label}] Skipped by RSS title (тендер): {post_title}")
                save_posted_link(f"{link}#0")   # маркуємо першим пунктом щоб не повторювати
                posted_links.add(f"{link}#0")
            continue

        items = split_digest_into_items(description)

        for idx, item_text in enumerate(items):
            # Унікальний ключ анти-дублікату для кожного пункту дайджесту:
            # окремого URL для пункту немає, тож комбінуємо лінк посту + індекс
            item_key = f"{link}#{idx}"

            if item_key in posted_links:
                continue

            item_title = make_item_title(item_text, post_title)

            if (
                is_excluded_title(post_title)
                or is_excluded_title(item_title)
                or is_excluded_text(item_text)
                or is_excluded_organization(item_text)
            ):
                print(f"[{source_label}] Skipped (тендер/закупівля): {item_title}")
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
                print(f"[{source_label}] ERROR processing {item_key}: {e}")
                continue


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    posted_links = load_posted_links()

    run_chaszmin(posted_links)
    run_simple_source(GURT_RSS, "ГУРТ — джерело", posted_links)
    run_simple_source(PROSTIR_RSS, "Громадський Простір — джерело", posted_links)


if __name__ == "__main__":
    main()
