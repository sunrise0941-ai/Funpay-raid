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
CHECK_INTERVAL_MIN = 25   # минимальная задержка между проверками (сек)
CHECK_INTERVAL_MAX = 35   # максимальная задержка
MAX_PRICE = 5000          # максимальная цена лота для уведомления
SUPER_CHEAP_THRESHOLD = 2500  # порог для пометки "супер дёшево"
MAX_LOTS_TO_SCAN = 60     # сколько лотов проверять на странице
SEEN_FILE = "seen_lots.json"
LOG_FILE = "bot.log"

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
# Ограничение на отправку сообщений (не более 20 в сек)
apihelper.SEND_MESSAGE_RATE_LIMIT = 0.05

# ---------- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ----------
seen: Set[str] = set()          # уже отправленные ссылки
chat_ids: Set[int] = set()      # подписанные чаты
stop_event = threading.Event()  # для graceful shutdown

# ---------- РОТАЦИЯ USER-AGENT ----------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

def get_headers() -> dict:
    return {"User-Agent": random.choice(USER_AGENTS)}

# ---------- РАБОТА С ФАЙЛОМ SEEN ----------
def load_seen() -> Set[str]:
    try:
        with open(SEEN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen() -> None:
    try:
        with open(SEEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(seen), f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сохранения seen: {e}")

# ---------- ПАРСИНГ ЦЕНЫ ----------
def parse_price(price_text: str) -> Optional[int]:
    """Извлекает число из строки цены. Возвращает None при ошибке."""
    digits = ''.join(filter(str.isdigit, price_text))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None

# ---------- ФИЛЬТР ПО НАЗВАНИЮ ----------
def get_alert_type(title: str) -> Optional[str]:
    """Определяет тип алерта по ключевым словам."""
    t = title.lower()

    # Приоритет: связка > конкретные герои
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
    """Основная логика: загрузка страницы, парсинг, отправка уведомлений."""
    try:
        headers = get_headers()
        # Добавляем случайную задержку перед запросом (анти-бан)
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

            # Проверка фильтров
            alert_type = get_alert_type(title)
            if not alert_type:
                continue

            if price_value > MAX_PRICE:
                continue

            # Формируем окончательный заголовок
            if price_value <= SUPER_CHEAP_THRESHOLD:
                alert = f"🚨 СУПЕР ДЁШЕВО! {alert_type}"
            else:
                alert = alert_type

            # Проверка, не отправляли ли уже
            if link in seen:
                continue

            seen.add(link)
            save_seen()  # сохраняем после каждого нового лота

            message = (
                f"{alert}\n\n"
                f"📌 {title}\n"
                f"💰 {price_text}\n"
                f"🔗 {link}"
            )

            # Рассылка всем подписанным чатам
            for chat_id in list(chat_ids):
                try:
                    bot.send_message(chat_id, message)
                    # Небольшая пауза, чтобы не упереться в лимиты Telegram
                    time.sleep(0.05)
                except Exception as e:
                    logger.error(f"Ошибка отправки в чат {chat_id}: {e}")
                    # Если чат заблокировал бота, удаляем из списка
                    if "bot was blocked" in str(e) or "chat not found" in str(e):
                        chat_ids.discard(chat_id)

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка сети при запросе к Funpay: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в check_lots: {e}", exc_info=True)

# ---------- ФОНОВЫЙ ЦИКЛ ----------
def worker() -> None:
    """Бесконечный цикл проверки с контролируемой остановкой."""
    logger.info("Поток мониторинга запущен")
    while not stop_event.is_set():
        check_lots()
        # Случайная задержка между итерациями
        delay = random.uniform(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
        # Используем Event.wait для возможности быстрой остановки
        if stop_event.wait(delay):
            break
    logger.info("Поток мониторинга остановлен")

# ---------- ОБРАБОТЧИКИ КОМАНД ----------
@bot.message_handler(commands=['start'])
def start(message: telebot.types.Message) -> None:
    chat_ids.add(message.chat.id)
    bot.reply_to(message, "🚀 Бот запущен и отслеживает лоты Funpay.\n"
                         "Ключевые слова: Гекатон, Соланар, Сабраэль, связки.\n"
                         "Максимальная цена: 5000₽\n"
                         "/stop - отключить уведомления\n"
                         "/check - принудительная проверка")

@bot.message_handler(commands=['stop'])
def stop(message: telebot.types.Message) -> None:
    chat_ids.discard(message.chat.id)
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
    # Загружаем сохранённые ссылки
    seen = load_seen()
    logger.info(f"Загружено {len(seen)} просмотренных лотов")

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