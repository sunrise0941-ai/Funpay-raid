import os
import json
import random
import time
import logging
import requests
from bs4 import BeautifulSoup
import telebot

# ---------- CONFIG ----------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("Нет TELEGRAM_BOT_TOKEN")

URL = "https://funpay.com/lots/566/"
CHECK_INTERVAL_MIN = 25
CHECK_INTERVAL_MAX = 35

MAX_PRICE = 5000
SUPER_CHEAP = 2500
MAX_LOTS = 60

SEEN_FILE = "seen.json"

# ---------- LOG ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

seen = set()
chat_ids = set()

# ---------- LOAD ----------
def load_seen():
    global seen
    try:
        with open(SEEN_FILE, "r") as f:
            seen = set(json.load(f))
    except:
        seen = set()

def save_seen():
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

# ---------- PRICE ----------
def parse_price(text):
    digits = "".join(filter(str.isdigit, text))
    return int(digits) if digits else None

# ---------- ALERTS ----------
def get_alert(title):
    t = title.lower()

    if "связка" in t or "combo" in t:
        return "🚨 СВЯЗКА"
    if "гекатон" in t:
        return "🔥 ГЕКАТОН"
    if "соланар" in t:
        return "⭐ СОЛАНАР"
    if "сабраэль" in t:
        return "🌸 САБРАЭЛЬ"
    return None

# ---------- CHECK ----------
def check():
    try:
        time.sleep(random.uniform(1, 2))

        r = requests.get(URL, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        lots = soup.find_all("a", class_="tc-item")

        for lot in lots[:MAX_LOTS]:

            title_tag = lot.find("div", class_="tc-desc-text")
            price_tag = lot.find("div", class_="tc-price")

            if not title_tag or not price_tag:
                continue

            title = title_tag.text.strip()
            price = parse_price(price_tag.text)

            if not price:
                continue

            link = lot.get("href")
            if not link:
                continue

            if not link.startswith("http"):
                link = "https://funpay.com" + link

            alert = get_alert(title)
            if not alert:
                continue

            if price > MAX_PRICE:
                continue

            if link in seen:
                continue

            seen.add(link)

            if price <= SUPER_CHEAP:
                alert = "🚨 СУПЕР ДЁШЕВО! " + alert

            msg = f"{alert}\n\n{title}\n💰 {price}\n🔗 {link}"

            for chat_id in list(chat_ids):
                try:
                    bot.send_message(chat_id, msg)
                except:
                    chat_ids.discard(chat_id)

        save_seen()

    except Exception as e:
        logger.error(e)

# ---------- LOOP ----------
def loop():
    while True:
        check()
        time.sleep(random.uniform(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX))

# ---------- TELEGRAM ----------
@bot.message_handler(commands=["start"])
def start(m):
    chat_ids.add(m.chat.id)
    bot.reply_to(m, "Бот запущен 🚀")

@bot.message_handler(commands=["stop"])
def stop(m):
    chat_ids.discard(m.chat.id)
    bot.reply_to(m, "Остановлен 🛑")

# ---------- MAIN ----------
if __name__ == "__main__":
    load_seen()

    import threading
    threading.Thread(target=loop, daemon=True).start()

    bot.polling(none_stop=True)