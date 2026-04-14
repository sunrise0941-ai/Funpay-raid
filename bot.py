import os
import json
import random
import time
import threading
import logging
import signal
import sys
from typing import Set, Optional

import requests
from bs4 import BeautifulSoup
import telebot
from telebot import apihelper

# ---------- КОНФИГУРАЦИЯ ----------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан в переменных окружения")

URL = "https://funpay.com/lots/566/"
CHECK_INTERVAL_MIN = 25
CHECK_INTERVAL_MAX = 35
MAX_PRICE = 5000
SUPER_CHEAP_THRESHOLD = 2500
MAX_LOTS_TO_SCAN = 60

# ---------- ПУТИ К ФАЙЛАМ В VOLUME ----------
DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)

SEEN_FILE = os.path.join(DATA_DIR, "seen_lots.json")
CHATS_FILE = os.path.join(DATA_DIR, "chat_ids.json")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")

# ---------- ЛОГИРОВАНИЕ ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------- БОТ ----------
bot = telebot.TeleBot(TOKEN)
apihelper.SEND_MESSAGE_RATE_LIMIT = 0.05

# ---------- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ----------
seen: Set[str] = set()
chat_ids: Set[int] = set()
stop_event = threading.Event()

# ---------- РОТАЦИЯ USER-AGENT ----------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

def get_headers() -> dict:
    return {"User-Agent": random.choice(USER_AGENTS)}

# ---------- РАБОТА С ФАЙЛАМИ ----------
def load_seen() -> Set[str]:
    try:
        with open(SEEN_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen() -> None:
    try:
        with open(SEEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(seen), f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сохранения seen: {e}")

def load_chats() -> Set[int]:
    try:
        with open(CHATS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_chats() -> None:
    try:
        with open(CHATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(chat_ids), f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сохранения chat_ids: {e}")

# ---------- ПАРСИНГ ЦЕНЫ ----------
def parse_price(price_text: str) -> Optional[int]:
    digits = ''.join(filter(str.isdigit, price_text))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None

# ---------- ФИЛЬТР ПО НАЗВАНИЮ ----------
def get_alert_type(title: str) -> Optional[str]:
    t = title.lower()
    if any(word in t for word in ["связка", "комба", "combo", "bundle"]):
        return "🚨 СВЯЗКА"
    elif any(word in t for word in ["гекатон", "гека", "hekaton"]):
        return "🔥 ГЕКАТОН"
    elif any(word in t for word in ["соланар", "solanar"]):
        return "⭐ СОЛАНАР"
    elif any(word in t for word in ["сабраэль", "сабр", "sabrael"]):
        return "🌸 САБРАЭЛЬ"
    return None

# ---------- ПРОВЕРКА ЛОТОВ ----------
def check_lots() -> None:
    try:
        headers = get_headers()
        time.sleep(random.uniform(1, 3))

        response = requests.get(URL, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        lots = soup.find_all("a", class_="tc-item")

        logger.info(f"Найдено лотов: {len(lots)} (проверяем первые {MAX_LOTS_TO_SCAN})")

        for idx, lot in enumerate(lots[:MAX_LOTS_TO_SCAN]):
            title_tag = lot.find("div", class_="tc-desc-text")
            price_tag = lot.find("div", class_="tc-price")

            if not title_tag or not price_tag:
                continue

            title = title_tag.text.strip()
            price_text = price_tag.text.strip()
            price_value = parse_price(price_text)

            if price_value is None:
                continue

            link = lot.get("href", "")
            if not link:
                continue

            if not link.startswith("http"):
                link = "https://funpay.com" + link

            alert_type = get_alert_type(title)
            if not alert_type:
                continue

            if price_value > MAX_PRICE:
                continue

            if price_value <= SUPER_CHEAP_THRESHOLD:
                alert = f"🚨 СУПЕР ДЁШЕВО! {alert_type}"
            else:
                alert = alert_type

            if link in seen:
                continue

            seen.add(link)
            save_seen()

            message = (
                f"{alert}\n\n"
                f"📌 {title}\n"
                f"💰 {price_text}\n"
                f"🔗 {link}"
            )

            for chat_id in list(chat_ids):
                try:
                    bot.send_message(chat_id, message)
                    time.sleep(0.05)
                except Exception as e:
                    logger.error(f"Ошибка отправки в чат {chat_id}: {e}")
                    if "bot was blocked" in str(e) or "chat not found" in str(e):
                        chat_ids.discard(chat_id)
                        save_chats()

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети при запросе к Funpay: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в check_lots: {e}", exc_info=True)

# ---------- ФОНОВЫЙ ЦИКЛ ----------
def worker() -> None:
    logger.info("Поток мониторинга запущен")
    while not stop_event.is_set():
        check_lots()
        delay = random.uniform(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
        if stop_event.wait(delay):
            break
    logger.info("Поток мониторинга остановлен")

# ---------- ОБРАБОТЧИКИ КОМАНД ----------
@bot.message_handler(commands=['start'])
def start(message: telebot.types.Message) -> None:
    chat_ids.add(message.chat.id)
    save_chats()
    bot.reply_to(message, "🚀 Бот запущен и отслеживает лоты Funpay.\n"
                         "Ключевые слова: Гекатон, Соланар, Сабраэль, связки.\n"
                         "Максимальная цена: 5000₽\n"
                         "/stop - отключить уведомления\n"
                         "/check - принудительная проверка")

@bot.message_handler(commands=['stop'])
def stop(message: telebot.types.Message) -> None:
    chat_ids.discard(message.chat.id)
    save_chats()
    bot.reply_to(message, "🛑 Вы отключены от уведомлений")

@bot.message_handler(commands=['check'])
def manual_check(message: telebot.types.Message) -> None:
    bot.reply_to(message, "⏳ Выполняю проверку...")
    check_lots()
    bot.send_message(message.chat.id, "✅ Проверка завершена")

# ---------- GRACEFUL SHUTDOWN ----------
def signal_handler(sig, frame) -> None:
    logger.info("Получен сигнал завершения, останавливаем бота...")
    stop_event.set()
    bot.stop_polling()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ---------- ТОЧКА ВХОДА ----------
if __name__ == "__main__":
    # Загружаем сохранённые данные
    seen = load_seen()
    chat_ids = load_chats()
    logger.info(f"Загружено {len(seen)} лотов, {len(chat_ids)} подписчиков")

    # Запускаем фоновый поток
    worker_thread = threading.Thread(target=worker, daemon=False)
    worker_thread.start()

    try:
        logger.info("Бот запущен, начинаем polling")
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        logger.critical(f"Критическая ошибка в polling: {e}")
    finally:
        stop_event.set()
        worker_thread.join(timeout=5)
        logger.info("Бот завершил работу")