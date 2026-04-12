import requests
import time
import threading
import logging
from bs4 import BeautifulSoup
import telebot

TOKEN =  "8715875001:AAF1P6kR-R-2PV7J8IZ3eDERhEnBTE62fYs"
bot = telebot.TeleBot(TOKEN)

URL = "https://funpay.com/lots/566/"

seen = set()
chat_ids = set()

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ---------------- PRICE ----------------
def parse_price(price_text):
    digits = ''.join(filter(str.isdigit, price_text))
    return int(digits) if digits else 999999

# ---------------- FILTER ----------------
def get_alert(title):
    t = title.lower()

    has_hekaton = any(h in t for h in ["гекатон", "гека", "hekaton"])
    has_solanar = any(s in t for s in ["соланар", "solanar"])
    has_combo = any(c in t for c in ["связка", "комба", "combo", "bundle"])
    has_sabr = any(s in t for s in ["сабраэль", "сабр", "sabrael"])

    if has_combo:
        return "🚨 СВЯЗКА"
    elif has_hekaton:
        return "🔥 ГЕКАТОН"
    elif has_solanar:
        return "⭐ СОЛАНАР"
    elif has_sabr:
        return "🌸 САБРАЭЛЬ"
    return None

# ---------------- SCRAPER ----------------
def check_lots():
    try:
        r = requests.get(URL, headers=HEADERS, timeout=10)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        lots = soup.find_all("a", class_="tc-item")

        for lot in lots[:60]:
            title_tag = lot.find("div", class_="tc-desc-text")
            price_tag = lot.find("div", class_="tc-price")

            if not title_tag or not price_tag:
                continue

            title = title_tag.text.strip()
            title_lower = title.lower()

            price_text = price_tag.text.strip()
            price_value = parse_price(price_text)

            link = lot.get("href", "")
            if not link:
                continue

            if not link.startswith("http"):
                link = "https://funpay.com" + link

            alert = get_alert(title_lower)

            if not alert:
                continue

            if price_value > 5000:
                continue

            if price_value <= 2500:
                alert = "🚨 СУПЕР ДЁШЕВО!"

            if link in seen:
                continue

            seen.add(link)

            message = (
                f"{alert}\n\n"
                f"📌 {title}\n"
                f"💰 {price_text}\n"
                f"🔗 {link}"
            )

            for chat_id in list(chat_ids):
                try:
                    bot.send_message(chat_id, message)
                except Exception as e:
                    logging.error(f"Send error: {e}")

    except Exception as e:
        logging.error(f"Check error: {e}")

# ---------------- LOOP WORKER ----------------
def worker():
    logging.info("Checker started")
    while True:
        check_lots()
        time.sleep(30)

# ---------------- HANDLERS ----------------
@bot.message_handler(commands=['start'])
def start(message):
    chat_ids.add(message.chat.id)
    bot.send_message(message.chat.id, "🚀 Бот запущен и отслеживает лоты")

@bot.message_handler(commands=['stop'])
def stop(message):
    chat_ids.discard(message.chat.id)
    bot.send_message(message.chat.id, "🛑 Вы отключены от уведомлений")

@bot.message_handler(commands=['check'])
def manual_check(message):
    check_lots()
    bot.send_message(message.chat.id, "✅ Проверка выполнена")

# ---------------- START ----------------
threading.Thread(target=worker, daemon=True).start()
bot.polling(none_stop=True)