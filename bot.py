import os
import json
import random
import time
import logging
import threading
import requests
from bs4 import BeautifulSoup
import telebot

# ---------- CONFIG ----------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан")

URL = "https://funpay.com/lots/566/"
CHECK_INTERVAL_MIN = 25
CHECK_INTERVAL_MAX = 35

MAX_PRICE = 5000
SUPER_CHEAP_THRESHOLD = 2500
MAX_LOTS_TO_SCAN = 60
SEEN_FILE = "seen.json"

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN)

seen = set()
chat_ids = set()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
]

def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}

# ---------- LOAD/SAVE ----------
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

# ---------- PARSE PRICE ----------
def parse_price(text):
    digits = "".join(filter(str.isdigit, text))
    return int(digits) if digits else None

# ---------- ALERT FILTER ----------
def get_alert_type(title):
    t = title.lower()

    if any(w in t for w in ["связка", "combo", "bundle"]):
        return "🚨 СВЯЗКА"
    if "гекатон" in t:
        return "🔥 ГЕКАТОН"
    if "соланар" in t:
        return "⭐ СОЛАНАР"
    if "сабраэль" in t:
        return "🌸 САБРАЭЛЬ"
    return None

# ---------- MAIN CHECK ----------
def check_lots():
    try:
        time.sleep(random.uniform(1, 3))

        r = requests.get(URL, headers=get_headers(), timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        lots = soup.find_all("a", class_="tc-item")

        for lot in lots[:MAX_LOTS_TO_SCAN]:

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

            alert = get_alert_type(title)
            if not alert:
                continue

            if price > MAX_PRICE:
                continue

            if link in seen:
                continue

            seen.add(link)

            if price <= SUPER_CHEAP_THRESHOLD:
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

# ---------- BACKGROUND LOOP ----------
def loop():
    while True:
        check_lots()
        time.sleep(random.uniform(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX))

# ---------- TELEGRAM ----------
@bot.message_handler(commands=["start"])
def start(m):
    chat_ids.add(m.chat.id)
    bot.reply_to(m, "Бот запущен 🚀")

@bot.message_handler(commands=["stop"])
def stop(m):
    chat_ids.discard(m.chat.id)
    bot.reply_to(m, "Остановлено 🛑")

# ---------- PING SERVER (ANTI SLEEP) ----------
def keep_alive():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return

    while True:
        try:
            requests.get(url)
        except:
            pass
        time.sleep(300)  # каждые 5 минут

# ---------- START ----------
if __name__ == "__main__":
    load_seen()

    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()

    bot.polling(none_stop=True)