import requests
import time
from bs4 import BeautifulSoup
import telebot

TOKEN = "8715875001:AAFIkVElPoF_Ge07raX_XdqNFT4916DDwYY"
bot = telebot.TeleBot(TOKEN)

URL = "https://funpay.com/lots/566/"

seen = set()

def parse_price(price_text):
    digits = ''.join(filter(str.isdigit, price_text))
    return int(digits) if digits else 999999

def get_alert(title):
    t = title.lower()

    has_hekaton = any(h in t for h in ["гекатон", "гек", "hekaton", "hek"])
    has_solanar = any(s in t for s in ["соланар", "solanar"])
    has_combo = any(c in t for c in ["связка", "комба", "combo", "bundle"])

    if has_combo:
        return "🚨 СВЯЗКА"
    elif has_hekaton:
        return "🔥 ГЕКАТОН"
    elif has_solanar:
        return "⭐ СОЛАНАР"
    else:
        return None

def check():
    r = requests.get(URL)
    soup = BeautifulSoup(r.text, "html.parser")

    lots = soup.find_all("a", class_="tc-item")

    for lot in lots[:60]:
        # название (чистое)
        title_tag = lot.find("div", class_="tc-desc-text")
        title = title_tag.text.strip() if title_tag else "Без названия"
        title_lower = title.lower()

        # ссылка
        href = lot.get("href")
        if href.startswith("http"):
            link = href
        else:
            link = "https://funpay.com" + href

        # цена
        price_tag = lot.find("div", class_="tc-price")
        if not price_tag:
            continue

        price_text = price_tag.text.strip()
        price_value = parse_price(price_text)

        # фильтр
        alert = get_alert(title_lower)

        if not alert:
            continue

        if price_value > 5000:
            continue

        if price_value <= 2500:
            alert = "🚨 СУПЕР ДЁШЕВО!"

        if link not in seen:
            seen.add(link)

            bot.send_message(
                CHAT_ID,
                f"{alert}\n\n"
                f"📌 {title}\n"
                f"💰 {price_text}\n"
                f"🔗 {link}",
                disable_web_page_preview=True
            )

CHAT_ID = None

@bot.message_handler(commands=['start'])
def start(message):
    global CHAT_ID
    CHAT_ID = message.chat.id

    bot.send_message(CHAT_ID, "Бот запущен 🚀")

    while True:
        try:
            check()
            time.sleep(30)
        except:
            time.sleep(30)

bot.polling()
