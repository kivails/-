import os
import random
import logging
import json
import asyncio
import threading
import string
import aiohttp
from datetime import datetime, timezone, timedelta
from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions, BotCommand
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import (
    TOKEN, ADMIN_IDS, DAILY_REWARD, DAILY_STREAK_BONUS, DAILY_MAX,
    QUIZ_REWARD, GUESS_REWARD, DUEL_REWARD, DICE_REWARD,
    SLOT_COST, SLOT_JACKPOT, SLOT_PAIR, START_BALANCE,
    WORK_COOLDOWN, WORK_MIN, WORK_MAX, ROB_COOLDOWN, ROB_SUCCESS_CHANCE, ROB_FINE,
    ROULETTE_MIN_BET, BLACKJACK_MIN_BET, COINFLIP_MIN_BET,
    SHOP_ITEMS, QUESTS, ACHIEVEMENTS, FISH, WORK_JOBS,
    RP_ACTIONS, BALL_ANSWERS, QUOTES, IDEAS, REFERRAL_BONUS
)
import database as db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)


@flask_app.route('/')
def index():
    return """
    <html><head><title>Bot</title></head>
    <body style="font-family:sans-serif;text-align:center;padding:50px;background:#1a1a2e;color:#eee;">
    <h1>🤖 Telegram Bot</h1>
    <p style="color:#4ade80;font-size:20px;">✅ Работает</p>
    <p>Пинг: <span id="t"></span></p>
    <script>document.getElementById('t').textContent=new Date().toLocaleString();</script>
    </body></html>
    """, 200


@flask_app.route('/health')
def health():
    return {"status": "ok"}, 200


# ---------- Состояния ----------
guess_games = {}
duel_games = {}
quiz_games = {}
blackjack_games = {}

QUIZ_QUESTIONS = [
    ("Сколько планет в Солнечной системе?", "8"),
    ("Столица Франции?", "париж"),
    ("Сколько будет 7 * 8?", "56"),
    ("Какой газ мы вдыхаем?", "кислород"),
    ("Самое большое животное на Земле?", "синий кит"),
    ("Сколько цветов в радуге?", "7"),
    ("Кто написал «Война и мир»?", "толстой"),
    ("Самая длинная река в мире?", "нил"),
    ("Сколько сторон у шестиугольника?", "6"),
    ("Год начала Второй мировой?", "1939"),
    ("Формула воды?", "h2o"),
    ("Сколько минут в часе?", "60"),
    ("Столица Японии?", "токио"),
    ("Какой самый твёрдый минерал?", "алмаз"),
    ("Сколько будет 12 * 12?", "144"),
    ("Кто написал «Евгений Онегин»?", "пушкин"),
    ("Сколько континентов?", "6"),
    ("Какой язык в Бразилии?", "португальский"),
    ("Сколько будет 100 / 4?", "25"),
    ("Крупнейшая планета?", "юпитер"),
    ("Химический символ золота?", "au"),
    ("Сколько костей у взрослого?", "206"),
    ("Самая высокая гора?", "эверест"),
    ("Кто открыл Америку?", "колумб"),
    ("Год полёта Гагарина?", "1961"),
]

JOKES = [
    "— Что сказал программист, когда закончил работу? — Ещё один commit, и я спать.",
    "Программист — это машина для превращения кофе в код.",
    "— Почему программисты путают Хэллоуин и Рождество? — Потому что Oct 31 == Dec 25.",
    "Есть 10 типов людей: те, кто понимает двоичную систему, и те, кто нет.",
    "— Как называется страх перед программированием? — Кодофобия.",
    "99 маленьких багов в коде, 99 маленьких багов... Уберёшь один — их 127.",
]

LINE = "━━━━━━━━━━━━━━━━━━━━━━━"


# ==================== ОФОРМЛЕНИЕ ====================

def frame(title: str, emoji: str = "✨") -> str:
    return (
        f"╭──────────────────────────╮\n"
        f"   {emoji}  **{title}**  {emoji}\n"
        f"╰──────────────────────────╯"
    )


def divider() -> str:
    return "━━━━━━━━━━━━━━━━━━━━━━━━━━"


def field(emoji: str, key: str, value) -> str:
    return f"{emoji} **{key}:** {value}"


def mention(user) -> str:
    return f"[{user.first_name}](tg://user?id={user.id})"


def mention_by_id(user_id: int, name: str = "Пользователь") -> str:
    return f"[{name}](tg://user?id={user_id})"


async def fetch_anime_gif(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["results"][0]["url"]
    except Exception as e:
        logger.warning(f"Gif fetch failed: {e}")
    return None


def is_bot_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def is_chat_admin(update, context) -> bool:
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def check_quest(user_id: int, quest_key: str, increment: int = 1):
    user = db.get_user(user_id)
    progress = json.loads(user[13] or '{}')
    progress[quest_key] = progress.get(quest_key, 0) + increment
    db.update_user(user_id, quest_progress=json.dumps(progress))
    description, target, reward = QUESTS[quest_key]
    if progress[quest_key] == target:
        db.add_balance(user_id, reward, f"quest_{quest_key}")
        return True, reward, description
    return False, 0, description


async def grant_achievement(update, user_id: int, ach_id: str):
    if ach_id not in ACHIEVEMENTS:
        return
    if db.add_achievement(user_id, ach_id):
        name, desc = ACHIEVEMENTS[ach_id]
        try:
            await update.message.reply_text(
                f"🏆 **НОВАЯ АЧИВКА!**\n{LINE}\n"
                f"👤 {mention_by_id(user_id)}\n{name}\n_{desc}_",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass


async def check_banned(update: Update) -> bool:
    db.get_user(update.effective_user.id,
                update.effective_user.username,
                update.effective_user.first_name)
    data = db.get_user(update.effective_user.id)
    return bool(data[15])


# ==================== START / HELP ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.get_user(user.id, user.username, user.first_name)

    # Реферальная обработка
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].replace("ref_", ""))
            if referrer_id != user.id:
                if db.add_referral(referrer_id, user.id):
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            f"🎉 Новый реферал! **+{REFERRAL_BONUS} 💎**",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        # Проверка ачивки реферера
                        ref_user = db.get_user(referrer_id)
                        if (ref_user[24] or 0) >= 5:
                            db.add_achievement(referrer_id, "referrer")
                    except Exception:
                        pass
        except (ValueError, IndexError):
            pass

    await grant_achievement(update, user.id, "first_steps")

    text = (
        f"{frame('ДОБРО ПОЖАЛОВАТЬ', '🌟')}\n\n"
        f"👋 Привет, **{user.first_name}**!\n\n"
        f"🤖 Я — **многофункциональный бот** с играми, экономикой,\n"
        f"RP, кланами, рефералами и модерацией.\n\n"
        f"{divider()}\n"
        f"📖 Все команды: /help\n"
        f"🎮 Игры: /games\n"
        f"💰 Экономика: /economy\n"
        f"🎰 Казино: /casino\n"
        f"💞 RP: /rp\n"
        f"💍 Отношения: /lovehelp\n"
        f"🎁 Рефералы: /referral\n"
        f"🎲 Развлечения: /fun\n"
        f"👑 Кланы: /clans\n"
        f"🏆 Ачивки: /achievements\n"
        f"🛡 Модерация: /modhelp\n"
        f"🔧 Утилиты: /utils\n"
        f"{divider()}\n\n"
        f"💡 _Добавь меня в группу и дай права администратора!_"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('СПРАВКА', '📖')}\n\n"
        f"🎮 Игры — /games\n"
        f"💰 Экономика — /economy\n"
        f"🎰 Казино — /casino\n"
        f"💞 RP — /rp\n"
        f"💍 Отношения — /lovehelp\n"
        f"🎁 Рефералы — /referral\n"
        f"🎲 Развлечения — /fun\n"
        f"👑 Кланы — /clans\n"
        f"🛡 Модерация — /modhelp\n"
        f"🔧 Утилиты — /utils\n"
        f"📌 Заметки — /noteshelp\n"
        f"🏆 Ачивки — /achievements\n\n"
        f"{divider()}\n"
        f"👤 /profile — профиль\n"
        f"📊 /stats — статистика\n"
        f"🏆 /top — топ\n"
        f"⭐ /rep — репутация\n"
        f"🕐 /msk — время МСК\n"
        f"💱 /currency — курсы валют\n"
        f"ℹ️ /about — о боте"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def games_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('ИГРЫ', '🎮')}\n\n"
        f"🎲 /roll — кубик (анимация)\n"
        f"🪙 /coin — монетка\n"
        f"🎯 /dice — кости против бота\n"
        f"🏀 /basketball — баскетбол\n"
        f"⚽ /football — футбол\n"
        f"🎳 /bowling — боулинг\n"
        f"🎯 /darts — дартс\n"
        f"🎰 /slot — автомат (10)\n"
        f"🔢 /guess — угадай число\n"
        f"🛑 /stopguess — стоп\n"
        f"⚔️ /duel @юзер — дуэль\n"
        f"❓ /quiz — викторина\n"
        f"🧠 /trivia — тривия\n"
        f"🎱 /8ball — шар судьбы\n"
        f"🎲 /random от до — число\n"
        f"🎲 /dnd — кубик D&D\n"
        f"🔤 /anagram — анаграмма\n"
        f"🎯 /emojiquiz — эмодзи-загадка"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def economy_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('ЭКОНОМИКА', '💰')}\n\n"
        f"💵 /balance [@юзер] — баланс\n"
        f"🎁 /daily — бонус (+50)\n"
        f"💼 /work — подработка (1ч)\n"
        f"🎣 /fish — рыбалка (15м)\n"
        f"🥷 /rob @юзер — ограбить\n"
        f"🏆 /top — топ-10\n"
        f"💸 /pay @юзер сумма — перевод\n"
        f"🛒 /shop — магазин\n"
        f"🛍 /buy ID — купить\n"
        f"🎒 /inventory — инвентарь\n"
        f"📜 /quests — квесты\n"
        f"🎁 /referral — рефералы (+0.5 💎)"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def casino_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('КАЗИНО', '🎰')}\n\n"
        f"🎰 /slot — автомат\n"
        f"🪙 /bet_flip орёл|решка сумма\n"
        f"🎡 /roulette цвет|число сумма\n"
        f"🃏 /blackjack сумма\n"
        f"🎲 /bet_dice сумма\n\n"
        f"{divider()}\n"
        f"Мин. ставки: рулетка {ROULETTE_MIN_BET}, блэкджек {BLACKJACK_MIN_BET}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def rp_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [frame('RP-ДЕЙСТВИЯ', '💞'), ""]
    for key, (emoji, text, _) in RP_ACTIONS.items():
        lines.append(f"{emoji} /{key} — {text}")
    lines.append("")
    lines.append("💡 _Работает: ответ на сообщение / @упоминание_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def love_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('ОТНОШЕНИЯ', '💍')}\n\n"
        f"💍 /marry @юзер — предложение\n"
        f"✅ /accept — принять\n"
        f"❌ /decline — отклонить\n"
        f"💔 /divorce — развестись\n"
        f"💞 /couple — показать пару\n"
        f"💕 /love @юзер — совместимость\n"
        f"🚢 /ship @a @b — шип"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def mod_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('МОДЕРАЦИЯ', '🛡')}\n\n"
        f"🔇 /mute [10m] — замутить\n"
        f"🔊 /unmute — размутить\n"
        f"👢 /kick — кикнуть\n"
        f"🚫 /ban — забанить\n"
        f"✅ /unban — разбанить\n"
        f"⚠️ /warn — предупреждение\n"
        f"🔹 /unwarn — снять\n"
        f"📋 /warns — варны\n"
        f"🧹 /purge N — удалить\n"
        f"📜 /rules — правила\n"
        f"✏️ /setrules — задать"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def utils_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('УТИЛИТЫ', '🔧')}\n\n"
        f"🌤 /weather город — погода\n"
        f"🌐 /tr текст — перевод\n"
        f"⏰ /remind 10m текст — напоминание\n"
        f"⏲ /timer 60 — таймер\n"
        f"🆔 /id — ID\n"
        f"🏓 /ping — пинг\n"
        f"🔐 /password 16 — пароль\n"
        f"📱 /qr текст — QR\n"
        f"🎨 /color — цвет\n"
        f"💱 /currency 100 USD RUB — конвертер\n"
        f"💎 /crypto BTC — крипта\n"
        f"📅 /date — день\n"
        f"🕐 /msk — Москва"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def fun_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('РАЗВЛЕЧЕНИЯ', '🎲')}\n\n"
        f"🎱 /8ball вопрос\n"
        f"💕 /love @юзер\n"
        f"🚢 /ship @a @b\n"
        f"🎭 /quote\n"
        f"🖼 /avatar @юзер\n"
        f"😄 /joke\n"
        f"🧠 /fact\n"
        f"💡 /idea\n"
        f"🎲 /choice a | b | c\n"
        f"🔮 /predict"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def notes_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('ЗАМЕТКИ', '📌')}\n\n"
        f"💾 /save имя текст\n"
        f"📖 /get имя\n"
        f"📋 /notes — список\n"
        f"🗑 /del имя"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def clans_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('КЛАНЫ', '👑')}\n\n"
        f"🏰 /create_clan Имя\n"
        f"📋 /clans\n"
        f"👥 /clan_info Имя\n"
        f"➕ /clan_join Имя\n"
        f"➖ /clan_leave\n"
        f"💰 /clan_deposit сумма\n"
        f"🏆 /clan_top\n"
        f"🗑 /clan_delete"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{frame('О БОТЕ', 'ℹ️')}\n\n"
        f"🤖 **Версия:** 6.0\n"
        f"🌐 **PTB:** python-telegram-bot 21.6\n"
        f"⚡ **Хостинг:** Render\n\n"
        f"{divider()}\n"
        f"📊 Команд: **170+**\n"
        f"🎮 Игр: **17**\n"
        f"💞 RP: **{len(RP_ACTIONS)}**\n"
        f"🏆 Ачивок: **{len(ACHIEVEMENTS)}**"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t0 = datetime.now()
    msg = await update.message.reply_text("🏓 ...")
    dt = (datetime.now() - t0).total_seconds() * 1000
    await msg.edit_text(f"🏓 Понг! `{dt:.0f}мс`", parse_mode=ParseMode.MARKDOWN)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    text = (
        f"🆔 **Ваш ID:** `{user.id}`\n"
        f"💬 **ID чата:** `{chat.id}`\n"
        f"📛 **Тип:** {chat.type}"
    )
    if update.message.reply_to_message:
        t = update.message.reply_to_message.from_user
        text += f"\n👤 **ID {t.first_name}:** `{t.id}`"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ==================== ВРЕМЯ / ВАЛЮТЫ ====================

async def moscow_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Время в Москве — через API worldtimeapi"""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://worldtimeapi.org/api/timezone/Europe/Moscow"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                dt_str = data["datetime"][:19].replace("T", " ")
                await update.message.reply_text(
                    f"{frame('МОСКВА (МСК)', '🕐')}\n\n"
                    f"📅 **{dt_str}**\n"
                    f"🌍 UTC{data['utc_offset']}\n"
                    f"_Обновлено с worldtimeapi.org_",
                    parse_mode=ParseMode.MARKDOWN
                )
    except Exception:
        msk = datetime.now(timezone(timedelta(hours=3)))
        await update.message.reply_text(
            f"{frame('МОСКВА (МСК)', '🕐')}\n\n"
            f"📅 **{msk.strftime('%d.%m.%Y %H:%M:%S')}**\n"
            f"_Fallback-режим (сервер)_",
            parse_mode=ParseMode.MARKDOWN
        )


async def currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Курсы валют: фиат + крипта"""
    if not context.args:
        await update.message.reply_text(
            f"{frame('ВАЛЮТЫ', '💱')}\n\n"
            f"`/currency USD` — курс валюты\n"
            f"`/currency 100 USD RUB` — конвертация\n"
            f"`/crypto BTC` — криптовалюта\n\n"
            f"{divider()}\n"
            f"💎 Крипта: BTC, ETH, TON, SOL, BNB, XRP",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Вариант: /currency 100 USD RUB
    if len(context.args) >= 3 and context.args[0].replace('.', '').isdigit():
        try:
            amount = float(context.args[0])
            from_cur = context.args[1].upper()
            to_cur = context.args[2].upper()
            async with aiohttp.ClientSession() as session:
                url = f"https://open.er-api.com/v6/latest/{from_cur}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
                    if data.get("result") != "success":
                        await update.message.reply_text("❌ Не нашёл валюту.")
                        return
                    rate = data["rates"].get(to_cur)
                    if not rate:
                        await update.message.reply_text("❌ Не нашёл целевую валюту.")
                        return
                    result = amount * rate
                    await update.message.reply_text(
                        f"💱 **{amount:g} {from_cur}** = **{result:.2f} {to_cur}**",
                        parse_mode=ParseMode.MARKDOWN
                    )
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
        return

    code = context.args[0].upper()
    crypto_map = {
        "BTC": "bitcoin", "TON": "the-open-network", "ETH": "ethereum",
        "SOL": "solana", "BNB": "binancecoin", "XRP": "ripple",
    }
    if code in crypto_map:
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_map[code]}&vs_currencies=usd,rub"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
                    info = data[crypto_map[code]]
                    await update.message.reply_text(
                        f"{frame(f'КУРС {code}', '💎')}\n\n"
                        f"🇺🇸 USD: **${info['usd']:,.2f}**\n"
                        f"🇷🇺 RUB: **{info['rub']:,.2f} ₽**\n"
                        f"{divider()}\n"
                        f"_Источник: CoinGecko_",
                        parse_mode=ParseMode.MARKDOWN
                    )
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
        return

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://open.er-api.com/v6/latest/{code}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                if data.get("result") != "success":
                    await update.message.reply_text("❌ Не нашёл валюту.")
                    return
                rub = data["rates"].get("RUB")
                usd = data["rates"].get("USD")
                eur = data["rates"].get("EUR")
                await update.message.reply_text(
                    f"{frame(f'КУРС {code}', '💱')}\n\n"
                    f"🇷🇺 RUB: {rub}\n"
                    f"🇺🇸 USD: {usd}\n"
                    f"🇪🇺 EUR: {eur}",
                    parse_mode=ParseMode.MARKDOWN
                )
    except Exception:
        await update.message.reply_text("Ошибка получения курса.")


async def crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Алиас для /currency с криптой"""
    if not context.args:
        await update.message.reply_text(
            "💎 Использование: /crypto BTC|ETH|TON|SOL|BNB|XRP",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    context.args = [context.args[0]]
    await currency(update, context)


# ==================== РЕФЕРАЛЫ ====================

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    coins = db.get_referral_coins(uid)
    count = db.get_referral_count(uid)
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    text = (
        f"{frame('РЕФЕРАЛЫ', '🎁')}\n\n"
        f"🔗 **Твоя ссылка:**\n`{link}`\n\n"
        f"{divider()}\n"
        f"{field('👥', 'Приглашено', count)}\n"
        f"{field('💎', 'Реферальных монет', f'**{coins:.1f}**')}\n"
        f"{divider()}\n"
        f"_+{REFERRAL_BONUS} 💎 за каждого нового юзера_"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ==================== ИГРЫ ====================

async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        max_num = int(context.args[0]) if context.args else 6
        if max_num < 2 or max_num > 6:
            max_num = 6
    except (ValueError, IndexError):
        max_num = 6
    if max_num == 6:
        msg = await update.message.reply_dice(emoji="🎲")
        result = msg.dice.value
    else:
        result = random.randint(1, max_num)
        await update.message.reply_dice(emoji="🎲")
    await update.message.reply_text(
        f"🎲 {mention(update.effective_user)} выбросил(а) **{result}**",
        parse_mode=ParseMode.MARKDOWN
    )
    await check_quest(update.effective_user.id, "play_5")


async def coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="🎯")
    result = "🦅 **Орёл**" if msg.dice.value in (1, 2, 3) else "🪙 **Решка**"
    await update.message.reply_text(
        f"🪙 {mention(update.effective_user)} подбрасывает...\nВыпало: {result}",
        parse_mode=ParseMode.MARKDOWN
    )


async def dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    m1 = await update.message.reply_dice(emoji="🎲")
    m2 = await update.message.reply_dice(emoji="🎲")
    player, bot = m1.dice.value, m2.dice.value
    d = db.get_user(uid)
    db.update_user(uid, stats_played=d[9] + 1)
    if player > bot:
        result = "🏆 **Вы победили!** +20"
        db.add_balance(uid, DICE_REWARD, "dice")
        db.update_user(uid, stats_won=d[10] + 1)
        await check_quest(uid, "win_3")
    elif player < bot:
        result = "🤖 **Бот победил!**"
    else:
        result = "🤝 **Ничья!**"
    await update.message.reply_text(
        f"🎯 {mention(update.effective_user)} — **{player}**\n🤖 Бот — **{bot}**\n\n{result}",
        parse_mode=ParseMode.MARKDOWN
    )
    await check_quest(uid, "play_5")


async def basketball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="🏀")
    s = msg.dice.value
    txt = "🏀 **Точный бросок!**" if s >= 4 else ("🏀 Почти!" if s >= 2 else "🏀 Мимо...")
    await update.message.reply_text(f"{mention(update.effective_user)} бросает!\n\n{txt} ({s}/5)", parse_mode=ParseMode.MARKDOWN)


async def football(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="⚽")
    s = msg.dice.value
    if s == 5: txt = "⚽ **ГООООЛ!**"
    elif s == 4: txt = "⚽ Гол!"
    elif s == 3: txt = "⚽ Вратарь поймал!"
    else: txt = "⚽ Мимо..."
    await update.message.reply_text(f"{mention(update.effective_user)} бьёт!\n\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def bowling(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="🎳")
    s = msg.dice.value
    txt = "🎳 **СТРАЙК!**" if s == 6 else f"🎳 Сбито {s} кеглей."
    await update.message.reply_text(f"{mention(update.effective_user)} бросает шар!\n\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def darts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_dice(emoji="🎯")
    s = msg.dice.value
    txt = "🎯 **В яблочко!**" if s == 6 else f"🎯 Очки: {s * 10}"
    await update.message.reply_text(f"{mention(update.effective_user)} кидает дротик!\n\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if db.get_balance(uid) < SLOT_COST:
        await update.message.reply_text("❌ Нужно 10 монет. /daily.")
        return
    msg = await update.message.reply_dice(emoji="🎰")
    v = msg.dice.value
    db.add_balance(uid, -SLOT_COST, "slot")
    if v >= 60:
        db.add_balance(uid, SLOT_JACKPOT, "slot_jackpot")
        result = f"💥 **ДЖЕКПОТ!** +{SLOT_JACKPOT}"
        await grant_achievement(update, uid, "lucky")
    elif v >= 40:
        db.add_balance(uid, SLOT_PAIR, "slot_pair")
        result = f"✨ **Удача!** +{SLOT_PAIR}"
    elif v >= 20:
        db.add_balance(uid, 5, "slot_small")
        result = "🙂 +5 монет."
    else:
        result = "😢 -10 монет."
    d = db.get_user(uid)
    db.update_user(uid, stats_played=d[9] + 1)
    if v >= 40:
        db.update_user(uid, stats_won=d[10] + 1)
        await check_quest(uid, "win_3")
    await update.message.reply_text(
        f"🎰 {mention(update.effective_user)}\n{result}\n💰 Баланс: **{db.get_balance(uid)}**",
        parse_mode=ParseMode.MARKDOWN
    )
    await check_quest(uid, "play_5")


async def dnd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sides = 20
    if context.args:
        try:
            a = context.args[0].lower()
            if a.startswith("d"):
                sides = int(a[1:])
                if sides not in (4, 6, 8, 10, 12, 20, 100):
                    sides = 20
        except (ValueError, IndexError):
            sides = 20
    r = random.randint(1, sides)
    await update.message.reply_text(f"🎲 **d{sides}** = **{r}**", parse_mode=ParseMode.MARKDOWN)


async def guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in guess_games:
        await update.message.reply_text("❌ Уже идёт. /stopguess")
        return
    guess_games[chat_id] = {'number': random.randint(1, 100), 'attempts': 0}
    await update.message.reply_text(
        f"🔢 **Угадай число (1–100)!** +{GUESS_REWARD}",
        parse_mode=ParseMode.MARKDOWN
    )


async def stop_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in guess_games:
        num = guess_games[chat_id]['number']
        del guess_games[chat_id]
        await update.message.reply_text(f"🛑 Было: **{num}**", parse_mode=ParseMode.MARKDOWN)


async def handle_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in guess_games:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        return
    n = int(text)
    game = guess_games[chat_id]
    game['attempts'] += 1
    if n < game['number']:
        await update.message.reply_text(f"📈 Больше! ({game['attempts']})")
    elif n > game['number']:
        await update.message.reply_text(f"📉 Меньше! ({game['attempts']})")
    else:
        uid = update.effective_user.id
        db.add_balance(uid, GUESS_REWARD, "guess")
        await update.message.reply_text(
            f"🎉 {mention(update.effective_user)}! **{game['number']}**\n+{GUESS_REWARD}",
            parse_mode=ParseMode.MARKDOWN
        )
        del guess_games[chat_id]


async def duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not update.message.reply_to_message and not context.args:
        await update.message.reply_text("Использование: /duel @юзер")
        return
    if update.message.reply_to_message:
        opponent = update.message.reply_to_message.from_user
    else:
        try:
            m = await context.bot.get_chat_member(chat_id, context.args[0].lstrip('@'))
            opponent = m.user
        except Exception:
            await update.message.reply_text("Не нашёл.")
            return
    challenger = update.effective_user
    if opponent.id == challenger.id:
        await update.message.reply_text("Нельзя себя!")
        return
    duel_games[chat_id] = {
        'challenger': challenger.id, 'opponent': opponent.id,
        'choice1': None, 'choice2': None,
        'names': {challenger.id: challenger.first_name, opponent.id: opponent.first_name}
    }
    kb = [[
        InlineKeyboardButton("✊", callback_data="duel_rock"),
        InlineKeyboardButton("✌️", callback_data="duel_scissors"),
        InlineKeyboardButton("✋", callback_data="duel_paper"),
    ]]
    await update.message.reply_text(
        f"⚔️ {mention(challenger)} vs {mention(opponent)}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def duel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat.id
    uid = q.from_user.id
    if chat_id not in duel_games:
        await q.edit_message_text("Дуэль завершена.")
        return
    g = duel_games[chat_id]
    if uid not in (g['challenger'], g['opponent']):
        await q.answer("Не участник!", show_alert=True)
        return
    cmap = {'duel_rock': '✊', 'duel_scissors': '✌️', 'duel_paper': '✋'}
    ch = cmap[q.data]
    if uid == g['challenger']:
        if g['choice1']:
            await q.answer("Уже!")
            return
        g['choice1'] = ch
    else:
        if g['choice2']:
            await q.answer("Уже!")
            return
        g['choice2'] = ch
    if g['choice1'] and g['choice2']:
        c1, c2 = g['choice1'], g['choice2']
        if c1 == c2:
            res = "🤝 Ничья!"
        elif (c1 == '✊' and c2 == '✌️') or (c1 == '✌️' and c2 == '✋') or (c1 == '✋' and c2 == '✊'):
            wid = g['challenger']
            db.add_balance(wid, DUEL_REWARD, "duel")
            res = f"🏆 {g['names'][wid]}! +{DUEL_REWARD}"
            await check_quest(wid, "duel_5")
        else:
            wid = g['opponent']
            db.add_balance(wid, DUEL_REWARD, "duel")
            res = f"🏆 {g['names'][wid]}! +{DUEL_REWARD}"
            await check_quest(wid, "duel_5")
        await q.edit_message_text(
            f"⚔️ Дуэль!\n\n{g['names'][g['challenger']]}: {c1}\n{g['names'][g['opponent']]}: {c2}\n\n{res}"
        )
        del duel_games[chat_id]
    else:
        await q.answer("Ждём соперника.")


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q, a = random.choice(QUIZ_QUESTIONS)
    quiz_games[chat_id] = {'answer': a.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(f"❓ **Викторина!**\n\n{q}\n\n+{QUIZ_REWARD}", parse_mode=ParseMode.MARKDOWN)


async def trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qs = [
        ("Самый быстрый зверь?", "гепард"),
        ("Сколько ног у паука?", "8"),
        ("Что такое HTML?", "hypertext markup language"),
        ("Самый большой океан?", "тихий"),
        ("Автор Гарри Поттера?", "роулинг"),
    ]
    chat_id = update.effective_chat.id
    q, a = random.choice(qs)
    quiz_games[chat_id] = {'answer': a.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(f"🧠 **Тривия!**\n\n{q}", parse_mode=ParseMode.MARKDOWN)


async def handle_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in quiz_games:
        return
    text = update.message.text.strip().lower()
    if text == quiz_games[chat_id]['answer']:
        r = quiz_games[chat_id]['reward']
        uid = update.effective_user.id
        db.add_balance(uid, r, "quiz")
        del quiz_games[chat_id]
        await update.message.reply_text(
            f"✅ Верно, {mention(update.effective_user)}! +{r}",
            parse_mode=ParseMode.MARKDOWN
        )


async def ball8(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🎱 /8ball вопрос")
        return
    q = " ".join(context.args)
    a = random.choice(BALL_ANSWERS)
    await update.message.reply_text(f"🎱 _{q}_\n{LINE}\n💬 {a}", parse_mode=ParseMode.MARKDOWN)


async def random_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) >= 2:
            a, b = int(context.args[0]), int(context.args[1])
            if a > b: a, b = b, a
        else:
            a, b = 1, 100
    except ValueError:
        a, b = 1, 100
    r = random.randint(a, b)
    await update.message.reply_text(f"🎲 От {a} до {b}: **{r}**", parse_mode=ParseMode.MARKDOWN)


async def anagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words = ["программирование", "телеграм", "экономика", "ачивка", "клан", "магазин", "рулетка"]
    word = random.choice(words)
    letters = list(word)
    random.shuffle(letters)
    chat_id = update.effective_chat.id
    quiz_games[chat_id] = {'answer': word.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(
        f"🔤 **Анаграмма!**\n\n`{''.join(letters).upper()}`\n\n+{QUIZ_REWARD}",
        parse_mode=ParseMode.MARKDOWN
    )


async def emoji_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    puzzles = [
        ("🌧️☀️", "радуга"), ("🐝🏠", "улей"), ("🌊🏄", "сёрфинг"),
        ("🦁👑", "король лев"), ("⭐🌙", "ночь"), ("🍎📱", "apple"),
        ("🐘🦒", "зоопарк"), ("🐟🎣", "рыбалка"),
    ]
    emoji, answer = random.choice(puzzles)
    chat_id = update.effective_chat.id
    quiz_games[chat_id] = {'answer': answer.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(f"🎯 **Угадай:**\n\n{emoji}\n\n+{QUIZ_REWARD}", parse_mode=ParseMode.MARKDOWN)


# ==================== КАЗИНО ====================

async def bet_flip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("/bet_flip орёл|решка сумма")
        return
    choice = context.args[0].lower()
    if choice not in ("орёл", "орел", "решка"):
        await update.message.reply_text("орёл или решка")
        return
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Сумма — число.")
        return
    uid = update.effective_user.id
    if amount < COINFLIP_MIN_BET:
        await update.message.reply_text(f"Мин: {COINFLIP_MIN_BET}")
        return
    if db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    result = random.choice(["орёл", "решка"])
    db.add_balance(uid, -amount, "bet_flip")
    if (choice in ("орёл", "орел") and result == "орёл") or (choice == "решка" and result == "решка"):
        win = amount * 2
        db.add_balance(uid, win, "bet_flip_win")
        await update.message.reply_text(f"🪙 **{result}**\n🎉 +{win}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"🪙 **{result}**\n😢 -{amount}", parse_mode=ParseMode.MARKDOWN)
    d = db.get_user(uid); db.update_user(uid, stats_played=d[9] + 1)
    await check_quest(uid, "play_5")


async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("/roulette красное|чёрное|число сумма")
        return
    choice = context.args[0].lower()
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Сумма — число.")
        return
    uid = update.effective_user.id
    if amount < ROULETTE_MIN_BET:
        await update.message.reply_text(f"Мин: {ROULETTE_MIN_BET}")
        return
    if db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    red = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    r = random.randint(0, 36)
    color = "зелёное" if r == 0 else ("красное" if r in red else "чёрное")
    db.add_balance(uid, -amount, "roulette")
    win = 0
    if choice in ("красное", "красный") and color == "красное": win = amount * 2
    elif choice in ("чёрное", "черное", "чёрный", "черный") and color == "чёрное": win = amount * 2
    elif choice.isdigit() and int(choice) == r: win = amount * 36
    if win:
        db.add_balance(uid, win, "roulette_win")
        await update.message.reply_text(f"🎡 **{r}** ({color})\n🎉 +{win}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(f"🎡 **{r}** ({color})\n😢 -{amount}", parse_mode=ParseMode.MARKDOWN)
    d = db.get_user(uid); db.update_user(uid, stats_played=d[9] + 1)
    await check_quest(uid, "play_5")


async def blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/blackjack сумма")
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Число.")
        return
    uid = update.effective_user.id
    if amount < BLACKJACK_MIN_BET:
        await update.message.reply_text(f"Мин: {BLACKJACK_MIN_BET}")
        return
    if db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало.")
        return
    cards = {"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,"J":10,"Q":10,"K":10,"A":11}
    deck = list(cards.keys()) * 4
    random.shuffle(deck)
    def dh(): return [deck.pop(), deck.pop()]
    def calc(h):
        t = sum(cards[c] for c in h); a = h.count("A")
        while t > 21 and a: t -= 10; a -= 1
        return t
    player, dealer = dh(), dh()
    db.add_balance(uid, -amount, "blackjack")
    blackjack_games[uid] = {'amount': amount, 'player': player, 'dealer': dealer, 'deck': deck}
    p, d = calc(player), calc(dealer)
    if p == 21 and d != 21:
        win = int(amount * 2.5)
        db.add_balance(uid, win, "blackjack_bj")
        await update.message.reply_text(f"🃏 **БЛЭКДЖЕК!** +{win}", parse_mode=ParseMode.MARKDOWN)
        del blackjack_games[uid]; return
    kb = [[
        InlineKeyboardButton("🎴 Ещё", callback_data=f"bj_hit:{uid}"),
        InlineKeyboardButton("🛑 Хватит", callback_data=f"bj_stand:{uid}"),
    ]]
    await update.message.reply_text(
        f"🃏 **Блэкджек** ({amount})\n{LINE}\n"
        f"🎴 Ваши: {' '.join(player)} = **{p}**\n🎴 Дилер: {dealer[0]} **?**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def blackjack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, uid_str = q.data.split(":")
    uid = int(uid_str)
    if q.from_user.id != uid:
        await q.answer("Не ваша игра!", show_alert=True)
        return
    if uid not in blackjack_games:
        await q.edit_message_text("Игра завершена.")
        return
    cards = {"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,"J":10,"Q":10,"K":10,"A":11}
    def calc(h):
        t = sum(cards[c] for c in h); a = h.count("A")
        while t > 21 and a: t -= 10; a -= 1
        return t
    g = blackjack_games[uid]; amount = g['amount']
    if action == "bj_hit":
        g['player'].append(g['deck'].pop())
        p = calc(g['player'])
        if p > 21:
            await q.edit_message_text(f"🃏 {' '.join(g['player'])} = **{p}**\n\n💥 Перебор! -{amount}", parse_mode=ParseMode.MARKDOWN)
            d = db.get_user(uid); db.update_user(uid, stats_played=d[9] + 1)
            del blackjack_games[uid]; return
        kb = [[
            InlineKeyboardButton("🎴 Ещё", callback_data=f"bj_hit:{uid}"),
            InlineKeyboardButton("🛑 Хватит", callback_data=f"bj_stand:{uid}"),
        ]]
        await q.edit_message_text(
            f"🃏 **Блэкджек** ({amount})\n{LINE}\n"
            f"🎴 Ваши: {' '.join(g['player'])} = **{p}**\n🎴 Дилер: {g['dealer'][0]} **?**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    elif action == "bj_stand":
        p = calc(g['player'])
        g['dealer'].append(g['deck'].pop())
        dv = calc(g['dealer'])
        while dv < 17:
            g['dealer'].append(g['deck'].pop())
            dv = calc(g['dealer'])
        if dv > 21 or p > dv:
            win = amount * 2; db.add_balance(uid, win, "blackjack_win"); msg = f"🏆 +{win}"
        elif p == dv:
            db.add_balance(uid, amount, "blackjack_push"); msg = "🤝 Ничья."
        else:
            msg = f"😢 -{amount}"
        await q.edit_message_text(
            f"🎴 Ваши: {' '.join(g['player'])} = {p}\n🎴 Дилер: {' '.join(g['dealer'])} = {dv}\n\n{msg}",
            parse_mode=ParseMode.MARKDOWN
        )
        d = db.get_user(uid); db.update_user(uid, stats_played=d[9] + 1)
        del blackjack_games[uid]


async def bet_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/bet_dice сумма")
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Число.")
        return
    uid = update.effective_user.id
    if amount < 10:
        await update.message.reply_text("Мин: 10")
        return
    if db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало.")
        return
    db.add_balance(uid, -amount, "bet_dice")
    p, b = random.randint(1, 6), random.randint(1, 6)
    if p > b:
        db.add_balance(uid, amount * 2, "bet_dice_win"); msg = f"🏆 +{amount*2}"
    elif p < b:
        msg = f"😢 -{amount}"
    else:
        db.add_balance(uid, amount, "bet_dice_push"); msg = "🤝 Ничья."
    await update.message.reply_text(f"🎲 Вы: {p} | 🤖 Бот: {b}\n\n{msg}", parse_mode=ParseMode.MARKDOWN)
    d = db.get_user(uid); db.update_user(uid, stats_played=d[9] + 1)
    await check_quest(uid, "play_5")


# ==================== ЭКОНОМИКА ====================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    db.get_user(user.id, user.username, user.first_name)
    bal = db.get_balance(user.id)
    ref = db.get_referral_coins(user.id)
    await update.message.reply_text(
        f"💰 Баланс {mention(user)}: **{bal}** монет\n💎 Реферальных: **{ref:.1f}**",
        parse_mode=ParseMode.MARKDOWN
    )


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    user = db.get_user(uid)
    last = user[12]
    now = datetime.now()
    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt < timedelta(hours=24):
            r = timedelta(hours=24) - (now - last_dt)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ Через {h}ч {m}м.")
            return
    streak = user[11] + 1 if last and (now - datetime.fromisoformat(last)) < timedelta(hours=48) else 1
    reward = min(DAILY_REWARD + (streak - 1) * DAILY_STREAK_BONUS, DAILY_MAX)
    db.add_balance(uid, reward, "daily")
    db.update_user(uid, last_daily=now.isoformat(), daily_streak=streak)
    if streak >= 7:
        await grant_achievement(update, uid, "daily_7")
    await update.message.reply_text(
        f"🎁 +{reward}!\n🔥 Стрик: {streak}\n💰 Баланс: {db.get_balance(uid)}"
    )
    await check_quest(uid, "daily_3")


async def work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    user = db.get_user(uid)
    last = user[17]
    now = datetime.now()
    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt < timedelta(seconds=WORK_COOLDOWN):
            r = timedelta(seconds=WORK_COOLDOWN) - (now - last_dt)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ Отдохни {h}ч {m}м.")
            return
    job = random.choice(WORK_JOBS)
    earned = random.randint(WORK_MIN, WORK_MAX)
    inv = (user[8] or "").split(",")
    if "pickaxe" in inv:
        earned = int(earned * 1.3)
    db.add_balance(uid, earned, "work")
    db.update_user(uid, last_work=now.isoformat())
    await update.message.reply_text(f"💼 Работал _{job}_\n💵 +{earned}", parse_mode=ParseMode.MARKDOWN)
    await check_quest(uid, "work_5")


async def fish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    user = db.get_user(uid)
    last = user[19]
    now = datetime.now()
    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt < timedelta(minutes=15):
            r = timedelta(minutes=15) - (now - last_dt)
            m = r.seconds // 60
            await update.message.reply_text(f"⏳ Через {m} мин.")
            return
    inv = (user[8] or "").split(",")
    bonus = 1.3 if "fishing_rod" in inv else 1.0
    roll = random.random(); cum = 0; caught = None
    for name, price, chance in FISH:
        cum += chance * bonus
        if roll <= cum:
            caught = (name, price); break
    if not caught:
        await update.message.reply_text("🎣 Ничего.")
    else:
        name, price = caught
        db.add_balance(uid, price, "fish")
        await update.message.reply_text(f"🎣 **{name}**\n💵 +{price}", parse_mode=ParseMode.MARKDOWN)
    db.update_user(uid, last_fish=now.isoformat())
    await check_quest(uid, "fish_10")


async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        await update.message.reply_text("Укажи @юзера или ответь.")
        return
    if target.id == update.effective_user.id:
        await update.message.reply_text("Себя нельзя!")
        return
    uid = update.effective_user.id
    db.get_user(uid)
    db.get_user(target.id, target.username, target.first_name)
    user = db.get_user(uid)
    last_rob = user[18]
    now = datetime.now()
    if last_rob:
        last_dt = datetime.fromisoformat(last_rob)
        if now - last_dt < timedelta(seconds=ROB_COOLDOWN):
            r = timedelta(seconds=ROB_COOLDOWN) - (now - last_dt)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ Отдохни {h}ч {m}м.")
            return
    tb = db.get_balance(target.id)
    if tb < 50:
        await update.message.reply_text("У цели < 50 монет.")
        return
    if random.random() < ROB_SUCCESS_CHANCE:
        amount = random.randint(10, min(200, tb // 2))
        db.add_balance(uid, amount, "rob_success")
        db.add_balance(target.id, -amount, "rob_victim")
        await update.message.reply_text(f"🥷 +{amount} у {mention(target)}", parse_mode=ParseMode.MARKDOWN)
    else:
        fine = min(ROB_FINE, db.get_balance(uid))
        db.add_balance(uid, -fine, "rob_fail")
        await update.message.reply_text(f"🚨 Провал! Штраф {fine}.")
    db.update_user(uid, last_rob=now.isoformat())


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.top_users(10)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [frame('ТОП-10 ИГРОКОВ', '🏆'), ""]
    for i, (uid, uname, fname, bal) in enumerate(users):
        name = f"**@{uname}**" if uname else f"_{fname or 'без имени'}_"
        lines.append(f"{medals[i]} {name} — `{bal}` 💰")
    lines.append("")
    lines.append(divider())
    lines.append("_Обновляется в реальном времени_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None; amount = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        if context.args and context.args[0].isdigit():
            amount = int(context.args[0])
    elif context.args and len(context.args) >= 2:
        name = context.args[0].lstrip('@')
        if context.args[1].isdigit():
            amount = int(context.args[1])
            if update.effective_chat.type != "private":
                try:
                    m = await context.bot.get_chat_member(update.effective_chat.id, name)
                    target = m.user
                except Exception:
                    pass
    if not target:
        await update.message.reply_text("❌ `/pay @юзер 100` или ответом на сообщение", parse_mode=ParseMode.MARKDOWN)
        return
    if not amount or amount <= 0:
        await update.message.reply_text("❌ Сумма > 0.")
        return
    uid = update.effective_user.id
    if target.id == uid:
        await update.message.reply_text("Себе нельзя.")
        return
    if db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    db.get_user(uid)
    db.get_user(target.id, target.username, target.first_name)
    db.add_balance(uid, -amount, "pay_out")
    db.add_balance(target.id, amount, "pay_in")
    await update.message.reply_text(
        f"💸 {mention(update.effective_user)} → {mention(target)}: **{amount}**",
        parse_mode=ParseMode.MARKDOWN
    )


async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [frame('МАГАЗИН', '🛒'), ""]
    for iid, (name, price, desc) in SHOP_ITEMS.items():
        lines.append(f"`{iid}` — {name}\n    💰 {price} | _{desc}_")
    lines.append("\nКупить: /buy ID")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/buy ID")
        return
    iid = context.args[0].lower()
    if iid not in SHOP_ITEMS:
        await update.message.reply_text("❌ Нет.")
        return
    name, price, desc = SHOP_ITEMS[iid]
    uid = update.effective_user.id
    if db.get_balance(uid) < price:
        await update.message.reply_text(f"❌ Нужно {price}.")
        return
    db.add_balance(uid, -price, f"buy_{iid}")
    user = db.get_user(uid)
    inv = [i for i in (user[8] or "").split(",") if i]
    inv.append(iid)
    db.update_user(uid, inventory=",".join(inv))
    await update.message.reply_text(f"✅ {name}\n💰 Осталось: {db.get_balance(uid)}")
    await check_quest(uid, "shop_3")
    if len(inv) >= 5:
        await grant_achievement(update, uid, "collector")


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    db.get_user(user.id, user.username, user.first_name)
    data = db.get_user(user.id)
    inv = [i for i in (data[8] or "").split(",") if i]
    if not inv:
        await update.message.reply_text("🎒 Пусто.")
        return
    lines = [f"🎒 **{user.first_name}:**\n"]
    for iid in inv:
        if iid in SHOP_ITEMS:
            lines.append(f"• {SHOP_ITEMS[iid][0]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def quests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    progress = json.loads(user[13] or '{}')
    lines = [f"{frame('КВЕСТЫ', '📜')}\n"]
    for qid, (desc, target, reward) in QUESTS.items():
        cur = progress.get(qid, 0)
        st = "✅" if cur >= target else "⏳"
        lines.append(f"{st} {desc}\n    {cur}/{target} | +{reward}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def achievements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    db.get_user(user.id, user.username, user.first_name)
    data = db.get_user(user.id)
    got = [g for g in (data[16] or "").split(",") if g]
    lines = [f"{frame('АЧИВКИ', '🏆')}\n", f"👤 {user.first_name} — **{len(got)}/{len(ACHIEVEMENTS)}**\n"]
    for aid, (name, desc) in ACHIEVEMENTS.items():
        mark = "✅" if aid in got else "🔒"
        lines.append(f"{mark} {name}\n    _{desc}_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def rep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        await update.message.reply_text("Укажи @юзера.")
        return
    if target.id == update.effective_user.id:
        await update.message.reply_text("Себе нельзя.")
        return
    db.get_user(target.id, target.username, target.first_name)
    data = db.get_user(target.id)
    nr = (data[21] or 0) + 1
    db.update_user(target.id, reputation=nr)
    await update.message.reply_text(
        f"⭐ {mention(update.effective_user)} → {mention(target)}\n📊 Репа: **{nr}**",
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== ПРОФИЛЬ ====================

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    db.get_user(user.id, user.username, user.first_name)
    data = db.get_user(user.id)

    partner_text = "💔 нет"
    if data[5]:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, data[5])
            partner_text = f"💞 {m.user.first_name}"
        except Exception:
            partner_text = f"💞 ID {data[5]}"

    clan_text = "🌫 нет"
    if data[20]:
        c = db.get_clan(data[20])
        if c:
            clan_text = f"🏰 {c[1]}"

    title = f" «{data[7]}»" if data[7] else ""
    bio_text = data[6] or "_не указано_"
    got = [a for a in (data[16] or "").split(",") if a]
    uname = f"@{data[1]}" if data[1] else "—"

    text = (
        f"{frame('ПРОФИЛЬ', '👤')}\n\n"
        f"🌟 **{user.first_name}**{title}\n"
        f"📛 {uname}\n"
        f"🆔 `{user.id}`\n\n"
        f"{divider()}\n"
        f"{field('💰', 'Баланс', f'**{data[3]}** монет')}\n"
        f"{field('💎', 'Реферальные', f'**{(data[22] or 0):.1f}**')}\n"
        f"{field('⭐', 'Репутация', f'**{data[21] or 0}**')}\n"
        f"{field('⚠️', 'Варны', data[4])}\n"
        f"{field('💞', 'Партнёр', partner_text)}\n"
        f"{field('👑', 'Клан', clan_text)}\n"
        f"{field('📝', 'Био', bio_text)}\n"
        f"{divider()}\n"
        f"{field('🎮', 'Игр', data[9])}\n"
        f"{field('🏆', 'Побед', data[10])}\n"
        f"{field('🔥', 'Стрик', f'{data[11] or 0} дней')}\n"
        f"{field('🎖', 'Ачивок', f'{len(got)}/{len(ACHIEVEMENTS)}')}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    db.get_user(user.id, user.username, user.first_name)
    data = db.get_user(user.id)
    played, won = data[9], data[10]
    pct = (won / played * 100) if played else 0
    text = (
        f"{frame('СТАТИСТИКА', '📊')}\n\n"
        f"👤 {user.first_name}\n{divider()}\n"
        f"🎮 Сыграно: {played}\n🏆 Побед: {won}\n"
        f"📈 Процент: {pct:.1f}%\n"
        f"💰 Монет: {data[3]}\n"
        f"💎 Реф-монет: {(data[22] or 0):.1f}\n"
        f"⭐ Репа: {data[21] or 0}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/bio текст")
        return
    text = " ".join(context.args)[:200]
    db.get_user(update.effective_user.id)
    db.update_user(update.effective_user.id, bio=text)
    await update.message.reply_text("✅ Био сохранено.")


async def title_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.get_user(uid)
    inv = (db.get_user(uid)[8] or "").split(",")
    if "vip" not in inv and "custom_title" not in inv:
        await update.message.reply_text("❌ Нужен VIP или «Своя приписка».")
        return
    if not context.args:
        await update.message.reply_text("/title текст")
        return
    text = " ".join(context.args)[:30]
    db.update_user(uid, title=text)
    await update.message.reply_text(f"✅ {text}")


# ==================== БРАК ====================

async def marry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actor = update.effective_user
    db.get_user(actor.id, actor.username, actor.first_name)
    user = db.get_user(actor.id)
    if user[5]:
        await update.message.reply_text("💔 Уже в браке. /divorce")
        return
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        await update.message.reply_text("Укажи @юзера или ответь.")
        return
    if target.id == actor.id:
        await update.message.reply_text("😅 Нельзя.")
        return
    td = db.get_user(target.id, target.username, target.first_name)
    if td[5]:
        await update.message.reply_text("Уже в браке.")
        return
    db.create_marriage_proposal(actor.id, target.id)
    kb = [[
        InlineKeyboardButton("✅ Принять", callback_data=f"marry_yes:{actor.id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"marry_no:{actor.id}"),
    ]]
    await update.message.reply_text(
        f"💍 **Предложение!**\n{LINE}\n"
        f"👤 {mention(actor)} → 💘 → {mention(target)}\n{LINE}\n"
        f"⏳ _{target.first_name}, твой ход..._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def marry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, pid_str = q.data.split(":")
    pid = int(pid_str)
    target = q.from_user
    if target.id == pid:
        await q.answer("Нельзя себе!", show_alert=True)
        return
    prop = db.get_marriage_proposal(pid, target.id)
    if not prop:
        await q.answer("Не для тебя!", show_alert=True)
        return
    pd = db.get_user(pid)
    td = db.get_user(target.id, target.username, target.first_name)
    pname = pd[2] or f"ID {pid}"
    if action == "marry_yes":
        if pd[5] or td[5]:
            await q.edit_message_text("💔 Кто-то уже в браке.")
            db.delete_marriage_proposal(pid, target.id)
            return
        db.update_user(pid, married_to=target.id)
        db.update_user(target.id, married_to=pid)
        db.delete_marriage_proposal(pid, target.id)
        await q.edit_message_text(
            f"💍💞 **Свадьба!**\n{LINE}\n"
            f"👤 {mention_by_id(pid, pname)} 💘 {mention(target)}\n{LINE}\n🎉 _Поздравляем!_",
            parse_mode=ParseMode.MARKDOWN
        )
        db.add_achievement(pid, "married")
        db.add_achievement(target.id, "married")
        await check_quest(pid, "marry")
        await check_quest(target.id, "marry")
    else:
        db.delete_marriage_proposal(pid, target.id)
        await q.edit_message_text(
            f"💔 Отказ...\n👤 {mention_by_id(pid, pname)} — не судьба.",
            parse_mode=ParseMode.MARKDOWN
        )


async def accept_marriage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.effective_user
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT proposer_id FROM marriages_proposals WHERE target_id=? ORDER BY created_at DESC LIMIT 1", (target.id,))
        row = cur.fetchone()
    if not row:
        await update.message.reply_text("💔 Нет предложений.")
        return
    pid = row[0]
    pd = db.get_user(pid)
    td = db.get_user(target.id, target.username, target.first_name)
    if pd[5] or td[5]:
        await update.message.reply_text("💔 Уже в браке.")
        db.delete_marriage_proposal(pid, target.id)
        return
    db.update_user(pid, married_to=target.id)
    db.update_user(target.id, married_to=pid)
    db.delete_marriage_proposal(pid, target.id)
    await update.message.reply_text(
        f"💍💞 **Свадьба!**\n👤 {mention_by_id(pid, pd[2] or 'Пользователь')} 💘 {mention(target)}",
        parse_mode=ParseMode.MARKDOWN
    )


async def decline_marriage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = update.effective_user
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT proposer_id FROM marriages_proposals WHERE target_id=? ORDER BY created_at DESC LIMIT 1", (target.id,))
        row = cur.fetchone()
    if not row:
        await update.message.reply_text("💔 Нет предложений.")
        return
    pid = row[0]
    pd = db.get_user(pid)
    db.delete_marriage_proposal(pid, target.id)
    await update.message.reply_text(f"💔 Отказ для {mention_by_id(pid, pd[2] or 'Пользователя')}", parse_mode=ParseMode.MARKDOWN)


async def divorce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actor = update.effective_user
    db.get_user(actor.id)
    user = db.get_user(actor.id)
    if not user[5]:
        await update.message.reply_text("Не в браке.")
        return
    pid = user[5]
    db.update_user(actor.id, married_to=None)
    db.update_user(pid, married_to=None)
    await update.message.reply_text("💔 Брак расторгнут.")


async def couple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actor = update.effective_user
    db.get_user(actor.id)
    user = db.get_user(actor.id)
    if not user[5]:
        await update.message.reply_text("Не в браке. /marry")
        return
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, user[5])
        partner = m.user
        await update.message.reply_text(f"💞 {mention(actor)} + {mention(partner)} = ❤️", parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(f"💞 ID партнёра: {user[5]}")


async def love_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        await update.message.reply_text("Укажи @юзера.")
        return
    actor = update.effective_user
    pair = tuple(sorted([actor.id, target.id]))
    random.seed(pair)
    pct = random.randint(1, 100)
    random.seed()
    if pct >= 90: bar, verdict = "💖" * 10, "Идеальная пара!"
    elif pct >= 70: bar, verdict = "💕" * 7 + "🤍" * 3, "Отличная совместимость!"
    elif pct >= 50: bar, verdict = "💛" * 5 + "🤍" * 5, "Неплохо!"
    elif pct >= 30: bar, verdict = "💔" * 3 + "🤍" * 7, "Сложно..."
    else: bar, verdict = "🖤" * 10, "Не судьба 😢"
    await update.message.reply_text(
        f"💕 **Совместимость**\n{LINE}\n"
        f"👤 {mention(actor)}\n💞 {mention(target)}\n{LINE}\n"
        f"{bar}\n📊 **{pct}%** — {verdict}",
        parse_mode=ParseMode.MARKDOWN
    )


async def ship(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = []
    if update.message.reply_to_message:
        users.append(update.message.reply_to_message.from_user)
    for arg in context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, arg.lstrip('@'))
            users.append(m.user)
        except Exception:
            pass
    if len(users) < 2:
        await update.message.reply_text("Нужно 2 юзера.")
        return
    a, b = users[0], users[1]
    pair = tuple(sorted([a.id, b.id]))
    random.seed(pair)
    pct = random.randint(1, 100)
    random.seed()
    name = a.first_name[:len(a.first_name)//2] + b.first_name[len(b.first_name)//2:]
    await update.message.reply_text(
        f"🚢 **Шип!**\n{LINE}\n💑 {mention(a)} + {mention(b)}\n{LINE}\n"
        f"💕 Имя: **{name}**\n📊 {pct}%\n{'💖' * (pct // 10)}",
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== RP ====================

async def send_rp(update: Update, context: ContextTypes.DEFAULT_TYPE, action_key: str):
    emoji, action, api_url = RP_ACTIONS[action_key]
    actor = update.effective_user
    db.get_user(actor.id, actor.username, actor.first_name)

    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        name = context.args[0].lstrip('@')
        if update.effective_chat.type != "private":
            try:
                m = await context.bot.get_chat_member(update.effective_chat.id, name)
                target = m.user
            except Exception:
                target = None
        else:
            target = name

    gif = await fetch_anime_gif(api_url)

    if target is None:
        caption = f"{emoji} {mention(actor)} _{action}_... _сам(а) с собой_ 😅"
    elif isinstance(target, str):
        caption = f"{emoji} {mention(actor)} _{action}_ **@{target}**"
    elif target.id == actor.id:
        caption = f"{emoji} {mention(actor)} _{action}_ _сам(а) себя_ 😅"
    else:
        caption = f"{emoji} {mention(actor)} _{action}_ {mention(target)}"

    try:
        if gif:
            await update.message.reply_animation(animation=gif, caption=caption, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)

    await check_quest(actor.id, "rp_10")


def make_rp_handler(action_key: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await send_rp(update, context, action_key)
    return handler


# ==================== РАЗВЛЕЧЕНИЯ ====================

async def quote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, author = random.choice(QUOTES)
    await update.message.reply_text(f"🎭 _{text}_\n\n— **{author}**", parse_mode=ParseMode.MARKDOWN)


async def avatar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    else:
        target = update.effective_user
    try:
        photos = await context.bot.get_user_profile_photos(target.id, limit=1)
        if not photos.photos:
            await update.message.reply_text("🖼 Нет аватара.")
            return
        fid = photos.photos[0][-1].file_id
        await update.message.reply_photo(photo=fid, caption=f"🖼 {mention(target)}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def random_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    color = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    await update.message.reply_text(f"🎨 **{color}**", parse_mode=ParseMode.MARKDOWN)


async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😄 {random.choice(JOKES)}")


async def fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://uselessfacts.jsph.pl/random.json?language=en", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                await update.message.reply_text(f"🧠 {data['text']}")
    except Exception:
        await update.message.reply_text("Не удалось.")


async def idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"💡 {random.choice(IDEAS)}")


async def choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/choice a | b | c")
        return
    text = " ".join(context.args)
    opts = [o.strip() for o in text.split("|") if o.strip()]
    if len(opts) < 2:
        await update.message.reply_text("2+ варианта через |")
        return
    await update.message.reply_text(f"🎲 **{random.choice(opts)}**", parse_mode=ParseMode.MARKDOWN)


async def predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    preds = [
        "Тебя ждёт удача! 🍀", "Скоро хорошая новость 📩",
        "Осторожнее с деньгами 💸", "Приятная встреча 💫",
        "Время действовать! 🚀", "Отдохни 😌",
        "Улыбнись 😊", "Возможны сюрпризы 🎁",
    ]
    await update.message.reply_text(f"🔮 {random.choice(preds)}")


# ==================== УТИЛИТЫ ====================

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/weather город")
        return
    city = " ".join(context.args)
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://wttr.in/{city}?format=j1"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                cur = data["current_condition"][0]
                await update.message.reply_text(
                    f"🌤 **{city}**\n{LINE}\n"
                    f"🌡 {cur['temp_C']}°C (ощущ. {cur['FeelsLikeC']}°C)\n"
                    f"☁️ {cur['weatherDesc'][0]['value']}\n"
                    f"💧 {cur['humidity']}%\n"
                    f"💨 {cur['windspeedKmph']} км/ч",
                    parse_mode=ParseMode.MARKDOWN
                )
    except Exception:
        await update.message.reply_text("Не удалось.")


async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message and not context.args:
        await update.message.reply_text("/tr текст")
        return
    text = update.message.reply_to_message.text if update.message.reply_to_message else " ".join(context.args)
    if not text:
        return
    try:
        async with aiohttp.ClientSession() as session:
            params = {
                "client": "gtx", "sl": "auto",
                "tl": "ru" if any(c.isascii() for c in text) else "en",
                "dt": "t", "q": text
            }
            async with session.get("https://translate.googleapis.com/translate_a/single", params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                translated = "".join(seg[0] for seg in data[0])
                await update.message.reply_text(f"🌐 {translated}")
    except Exception:
        await update.message.reply_text("Ошибка.")


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("/remind 10m текст")
        return
    t = context.args[0].lower()
    text = " ".join(context.args[1:])
    try:
        if t.endswith("m"): sec = int(t[:-1]) * 60
        elif t.endswith("h"): sec = int(t[:-1]) * 3600
        elif t.endswith("s"): sec = int(t[:-1])
        else: sec = int(t)
    except ValueError:
        await update.message.reply_text("Неверный формат.")
        return
    chat_id = update.effective_chat.id
    um = mention(update.effective_user)
    async def task():
        await asyncio.sleep(sec)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ {um}, напоминание: {text}", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
    asyncio.create_task(task())
    await update.message.reply_text(f"✅ Через {t}.")


async def timer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/timer 60")
        return
    try:
        sec = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Число.")
        return
    if sec > 3600: sec = 3600
    chat_id = update.effective_chat.id
    um = mention(update.effective_user)
    async def task():
        await asyncio.sleep(sec)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏲ {um}, таймер на {sec}с завершён!", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
    asyncio.create_task(task())
    await update.message.reply_text(f"⏲ Таймер на {sec}с.")


async def password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    length = 16
    if context.args:
        try:
            length = max(6, min(64, int(context.args[0])))
        except ValueError:
            pass
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    pwd = "".join(random.choice(chars) for _ in range(length))
    await update.message.reply_text(f"🔐 **Пароль:**\n`{pwd}`", parse_mode=ParseMode.MARKDOWN)


async def qr_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/qr текст")
        return
    text = " ".join(context.args)[:500]
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={text}"
    try:
        await update.message.reply_photo(photo=url, caption=f"📱 QR")
    except Exception:
        await update.message.reply_text(f"📱 QR: {url}")


async def date_fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now()
    facts = [
        "🌍 Отличный день!",
        "🌟 Звёзды благосклонны.",
        "☕ Не забудь кофе!",
        "📚 Хороший день для чтения.",
        "🎵 Послушай музыку.",
    ]
    await update.message.reply_text(
        f"📅 **{today.strftime('%d.%m.%Y')}**\n🗓 {today.strftime('%A')}\n{random.choice(facts)}",
        parse_mode=ParseMode.MARKDOWN
    )


async def time_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    await update.message.reply_text(f"🕐 Сервер: **{now.strftime('%H:%M:%S')}**", parse_mode=ParseMode.MARKDOWN)


# ==================== МОДЕРАЦИЯ ====================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        await update.message.reply_text("❌ Только админы.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответь на сообщение.")
        return
    target = update.message.reply_to_message.from_user
    duration = 60
    if context.args:
        a = context.args[0].lower()
        try:
            if a.endswith("m"): duration = int(a[:-1]) * 60
            elif a.endswith("h"): duration = int(a[:-1]) * 3600
            elif a.endswith("d"): duration = int(a[:-1]) * 86400
            elif a.isdigit(): duration = int(a)
        except ValueError:
            pass
    until = datetime.now() + timedelta(seconds=duration)
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await update.message.reply_text(f"🔇 {mention(target)} на {duration // 60} мин.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        )
        await update.message.reply_text(f"🔊 {mention(target)} размучен.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"👢 {mention(target)} кикнут.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🚫 {mention(target)} забанен.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    target_id = None
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].isdigit():
        target_id = int(context.args[0])
    if not target_id:
        return
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target_id)
        await update.message.reply_text(f"✅ Разбанен: {target_id}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    db.get_user(target.id, target.username, target.first_name)
    cur = db.get_user(target.id)[4]
    db.update_user(target.id, warns=cur + 1)
    new = cur + 1
    await update.message.reply_text(f"⚠️ {mention(target)} — варн ({new}/3)", parse_mode=ParseMode.MARKDOWN)
    if new >= 3:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, target.id)
            await update.message.reply_text(f"🚫 {mention(target)} забанен (3/3).", parse_mode=ParseMode.MARKDOWN)
            db.update_user(target.id, warns=0)
        except Exception:
            pass


async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    cur = db.get_user(target.id)[4]
    if cur > 0:
        db.update_user(target.id, warns=cur - 1)
    await update.message.reply_text(f"✅ Снят. Осталось: {max(0, cur - 1)}")


async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    db.get_user(user.id)
    cur = db.get_user(user.id)[4]
    await update.message.reply_text(f"⚠️ Варнов у {user.first_name}: {cur}")


async def purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("/purge N")
        return
    n = min(max(int(context.args[0]), 1), 100)
    chat_id = update.effective_chat.id
    msg_id = update.message.message_id
    deleted = 0
    for i in range(n + 1):
        try:
            await context.bot.delete_message(chat_id, msg_id - i)
            deleted += 1
        except Exception:
            pass
    await context.bot.send_message(chat_id, f"🧹 Удалено {deleted}.")


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = db.get_chat(update.effective_chat.id)
    if not chat[2]:
        await update.message.reply_text("Правил нет.")
        return
    await update.message.reply_text(f"📜 **Правила:**\n\n{chat[2]}", parse_mode=ParseMode.MARKDOWN)


async def setrules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not context.args:
        return
    db.update_chat(update.effective_chat.id, rules=" ".join(context.args)[:1000])
    await update.message.reply_text("✅ Сохранено.")


async def welcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_chat_admin(update, context):
        return
    if not context.args:
        return
    db.update_chat(update.effective_chat.id, welcome=" ".join(context.args)[:500])
    await update.message.reply_text("✅ Сохранено.")


async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for m in update.message.new_chat_members:
        chat = db.get_chat(update.effective_chat.id)
        text = chat[1] or "👋 Добро пожаловать, {name}!"
        text = text.replace("{name}", mention(m))
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(f"👋 Привет, {m.first_name}!")


# ==================== КЛАНЫ ====================

async def create_clan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/create_clan Имя")
        return
    name = context.args[0][:30]
    desc = " ".join(context.args[1:])[:200] if len(context.args) > 1 else ""
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if db.get_clan_by_name(name):
        await update.message.reply_text("❌ Имя занято.")
        return
    user = db.get_user(uid)
    if user[20]:
        await update.message.reply_text("❌ Ты уже в клане.")
        return
    cid = db.create_clan(name, uid, desc)
    if not cid:
        await update.message.reply_text("❌ Ошибка.")
        return
    db.update_user(uid, clan_id=cid)
    await update.message.reply_text(f"🏰 **{name}** создан!", parse_mode=ParseMode.MARKDOWN)


async def clans_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clans = db.get_all_clans(20)
    if not clans:
        await update.message.reply_text("Пусто.")
        return
    lines = [f"{frame('КЛАНЫ', '🏰')}\n"]
    for c in clans:
        lines.append(f"• **{c[1]}** — {c[5]} 💰 ({len(db.get_clan_members(c[0]))})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def clan_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/clan_info Имя")
        return
    c = db.get_clan_by_name(context.args[0])
    if not c:
        await update.message.reply_text("Не найден.")
        return
    members = db.get_clan_members(c[0])
    lines = [
        f"🏰 **{c[1]}**", LINE,
        f"👑 Владелец: ID {c[2]}",
        f"💰 Баланс: {c[5]}",
        f"📝 {c[3] or '—'}", LINE,
        f"👥 Участники ({len(members)}):"
    ]
    for uid, uname, fname, bal in members[:20]:
        lines.append(f"• @{uname}" if uname else f"• {fname or uid}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def clan_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    c = db.get_clan_by_name(context.args[0])
    if not c:
        await update.message.reply_text("Не найден.")
        return
    uid = update.effective_user.id
    user = db.get_user(uid)
    if user[20]:
        await update.message.reply_text("❌ Уже в клане.")
        return
    db.update_user(uid, clan_id=c[0])
    await update.message.reply_text(f"✅ Вступил в **{c[1]}**", parse_mode=ParseMode.MARKDOWN)


async def clan_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = db.get_user(uid)
    if not user[20]:
        await update.message.reply_text("Не в клане.")
        return
    c = db.get_clan(user[20])
    if c and c[2] == uid:
        await update.message.reply_text("Ты владелец. /clan_delete")
        return
    db.update_user(uid, clan_id=None)
    await update.message.reply_text("👋 Покинул.")


async def clan_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = db.get_user(uid)
    if not user[20]:
        await update.message.reply_text("Не в клане.")
        return
    if not context.args or not context.args[0].isdigit():
        return
    amount = int(context.args[0])
    if amount <= 0 or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    db.add_balance(uid, -amount, "clan_deposit")
    db.add_clan_balance(user[20], amount)
    await update.message.reply_text(f"💰 +{amount} в клан.")


async def clan_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clans = db.get_all_clans(10)
    if not clans:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"{frame('ТОП КЛАНОВ', '🏆')}\n"]
    for i, c in enumerate(clans):
        lines.append(f"{medals[i]} **{c[1]}** — {c[5]} 💰")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def clan_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = db.get_user(uid)
    if not user[20]:
        await update.message.reply_text("Не в клане.")
        return
    c = db.get_clan(user[20])
    if not c or c[2] != uid:
        await update.message.reply_text("Только владелец.")
        return
    db.delete_clan(c[0])
    await update.message.reply_text(f"🗑 Удалён.", parse_mode=ParseMode.MARKDOWN)


# ==================== ЗАМЕТКИ ====================

async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("/save имя текст")
        return
    name = context.args[0].lower()
    content = " ".join(context.args[1:])
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO notes(chat_id, name, content) VALUES(?, ?, ?)", (update.effective_chat.id, name, content))
        conn.commit()
    await update.message.reply_text(f"✅ `{name}`", parse_mode=ParseMode.MARKDOWN)


async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    name = context.args[0].lower()
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT content FROM notes WHERE chat_id=? AND name=?", (update.effective_chat.id, name))
        row = cur.fetchone()
    if row:
        await update.message.reply_text(f"📝 {row[0]}")
    else:
        await update.message.reply_text("Не найдено.")


async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM notes WHERE chat_id=?", (update.effective_chat.id,))
        rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Пусто.")
        return
    await update.message.reply_text("📝 " + ", ".join(f"`{r[0]}`" for r in rows), parse_mode=ParseMode.MARKDOWN)


async def del_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    name = context.args[0].lower()
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE chat_id=? AND name=?", (update.effective_chat.id, name))
        conn.commit()
    await update.message.reply_text("🗑 Удалено.")


# ==================== АДМИН-ПАНЕЛЬ ====================

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    logger.info(f"ADMIN CHECK: user_id={uid}, ADMIN_IDS={ADMIN_IDS}, is_admin={uid in ADMIN_IDS}")
    if not is_bot_admin(uid):
        await update.message.reply_text(
            f"❌ **Доступ запрещён.**\n\n"
            f"🆔 Ваш ID: `{uid}`\n"
            f"👑 ID админов: `{ADMIN_IDS}`\n\n"
            f"_Впишите свой ID в config.py → ADMIN_IDS_",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    text = (
        f"{frame('АДМИН-ПАНЕЛЬ', '👑')}\n\n"
        f"👤 **Юзеры:**\n"
        f"/admin_user @юзер\n"
        f"/admin_setbal @юзер сумма\n"
        f"/admin_addbal @юзер сумма\n"
        f"/admin_reset @юзер\n"
        f"/admin_ban @юзер\n"
        f"/admin_unban @юзер\n"
        f"/admin_unmarry @юзер\n"
        f"/admin_setname @юзер имя\n"
        f"/admin_giveitem @юзер ID\n\n"
        f"🌐 **Чаты:**\n"
        f"/admin_chats\n"
        f"/admin_broadcast текст\n"
        f"/admin_stats\n\n"
        f"⚙️ **Система:**\n"
        f"/admin_ping\n"
        f"/admin_version"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users"); tu = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE married_to IS NOT NULL"); m = cur.fetchone()[0] // 2
        cur.execute("SELECT COUNT(*) FROM chats"); tc = cur.fetchone()[0]
        cur.execute("SELECT SUM(balance) FROM users"); tb = cur.fetchone()[0] or 0
        cur.execute("SELECT SUM(stats_played) FROM users"); tg = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM clans"); tcl = cur.fetchone()[0]
    text = (
        f"{frame('СТАТИСТИКА', '📊')}\n\n"
        f"👥 Юзеров: **{tu}**\n"
        f"💬 Чатов: **{tc}**\n"
        f"💑 Пар: **{m}**\n"
        f"🏰 Кланов: **{tcl}**\n"
        f"💰 Всего монет: **{tb}**\n"
        f"🎮 Игр: **{tg}**"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def admin_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        await update.message.reply_text("Укажи @юзера.")
        return
    data = db.get_user(target.id, target.username, target.first_name)
    await update.message.reply_text(
        f"👤 **{target.first_name}**\n{LINE}\n"
        f"🆔 `{data[0]}`\n📛 @{data[1] or '—'}\n"
        f"💰 {data[3]}\n💎 Реф: {(data[22] or 0):.1f}\n"
        f"⚠️ Варны: {data[4]}\n💑 {data[5] or '—'}\n"
        f"🏰 Клан: {data[20] or '—'}\n"
        f"🎮 {data[9]} / 🏆 {data[10]}\n"
        f"⭐ {data[21] or 0}",
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_setbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("/admin_setbal @юзер сумма")
        return
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
        db.get_user(m.user.id)
        db.update_user(m.user.id, balance=int(context.args[1]))
        await update.message.reply_text(f"✅ {m.user.first_name} = {context.args[1]}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def admin_addbal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        return
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
        db.add_balance(m.user.id, int(context.args[1]), "admin")
        await update.message.reply_text(f"✅ +{context.args[1]}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def admin_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        return
    db.get_user(target.id)
    db.update_user(target.id, balance=START_BALANCE, warns=0, married_to=None,
                   inventory="", stats_played=0, stats_won=0, daily_streak=0,
                   quest_progress="{}", achievements="", clan_id=None, reputation=0,
                   referral_coins=0, referral_count=0)
    await update.message.reply_text(f"🔄 {target.first_name} сброшен.")


async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        return
    db.get_user(target.id)
    db.update_user(target.id, is_banned=1)
    await update.message.reply_text(f"🚫 {target.first_name} забанен.")


async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        return
    db.get_user(target.id)
    db.update_user(target.id, is_banned=0)
    await update.message.reply_text(f"✅ {target.first_name} разбанен.")


async def admin_unmarry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
            target = m.user
        except Exception:
            pass
    if not target:
        return
    data = db.get_user(target.id)
    if data[5]:
        db.update_user(target.id, married_to=None)
        db.update_user(data[5], married_to=None)
        await update.message.reply_text(f"💔 Разведён(а).")


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    if not context.args:
        return
    text = " ".join(context.args)
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM chats")
        chats = [r[0] for r in cur.fetchall()]
    sent, failed = 0, 0
    for cid in chats:
        try:
            await context.bot.send_message(chat_id=cid, text=f"📢 **Рассылка:**\n{LINE}\n{text}", parse_mode=ParseMode.MARKDOWN)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📢 OK: {sent}, ошибок: {failed}")


async def admin_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM chats")
        chats = cur.fetchall()
    if not chats:
        await update.message.reply_text("Нет чатов.")
        return
    lines = ["💬 **Чаты:**"]
    for (cid,) in chats:
        lines.append(f"• `{cid}`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def admin_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    t0 = datetime.now()
    msg = await update.message.reply_text("🏓 ...")
    dt = (datetime.now() - t0).total_seconds() * 1000
    await msg.edit_text(f"🏓 `{dt:.0f}ms`", parse_mode=ParseMode.MARKDOWN)


async def admin_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    await update.message.reply_text("🤖 **v6.0**", parse_mode=ParseMode.MARKDOWN)


async def admin_setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        return
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
        new_name = " ".join(context.args[1:])
        db.get_user(m.user.id)
        db.update_user(m.user.id, first_name=new_name)
        await update.message.reply_text(f"✅ {new_name}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def admin_giveitem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        return
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, context.args[0].lstrip('@'))
        iid = context.args[1].lower()
        if iid not in SHOP_ITEMS:
            await update.message.reply_text("Нет такого.")
            return
        db.get_user(m.user.id)
        user = db.get_user(m.user.id)
        inv = [i for i in (user[8] or "").split(",") if i]
        inv.append(iid)
        db.update_user(m.user.id, inventory=",".join(inv))
        await update.message.reply_text(f"✅ {SHOP_ITEMS[iid][0]} → {m.user.first_name}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# ==================== TEXT ROUTER ====================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_banned(update):
        return
    await handle_guess(update, context)
    await handle_quiz(update, context)


# ==================== ЗАПУСК ====================

def run_bot():
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())

    db.init_db()

    async def post_init(app):
        try:
            await app.bot.set_my_commands([
                BotCommand("start", "🚀 Старт"),
                BotCommand("help", "📖 Команды"),
                BotCommand("profile", "👤 Профиль"),
                BotCommand("balance", "💰 Баланс"),
                BotCommand("daily", "🎁 Бонус"),
                BotCommand("work", "💼 Работа"),
                BotCommand("fish", "🎣 Рыбалка"),
                BotCommand("top", "🏆 Топ"),
                BotCommand("shop", "🛒 Магазин"),
                BotCommand("games", "🎮 Игры"),
                BotCommand("casino", "🎰 Казино"),
                BotCommand("rp", "💞 RP"),
                BotCommand("referral", "🎁 Рефералы"),
                BotCommand("msk", "🕐 Время МСК"),
                BotCommand("currency", "💱 Валюты"),
                BotCommand("crypto", "💎 Крипта"),
                BotCommand("marry", "💍 Брак"),
                BotCommand("achievements", "🏆 Ачивки"),
                BotCommand("clans", "👑 Кланы"),
                BotCommand("adminhelp", "👑 Админ"),
            ])
        except Exception as e:
            logger.warning(f"set_my_commands failed: {e}")

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # БАЗОВЫЕ
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("id", id_command))

    # СПРАВКА
    application.add_handler(CommandHandler("games", games_help))
    application.add_handler(CommandHandler("economy", economy_help))
    application.add_handler(CommandHandler("casino", casino_help))
    application.add_handler(CommandHandler("rp", rp_help))
    application.add_handler(CommandHandler("lovehelp", love_help))
    application.add_handler(CommandHandler("modhelp", mod_help))
    application.add_handler(CommandHandler("utils", utils_help))
    application.add_handler(CommandHandler("noteshelp", notes_help))
    application.add_handler(CommandHandler("fun", fun_help))
    application.add_handler(CommandHandler("clans", clans_help))

    # ВРЕМЯ / ВАЛЮТЫ
    application.add_handler(CommandHandler("msk", moscow_time))
    application.add_handler(CommandHandler("moscow", moscow_time))
    application.add_handler(CommandHandler("время", moscow_time))
    application.add_handler(CommandHandler("currency", currency))
    application.add_handler(CommandHandler("crypto", crypto))

    # РЕФЕРАЛЫ
    application.add_handler(CommandHandler("referral", referral))
    application.add_handler(CommandHandler("ref", referral))

    # ИГРЫ
    application.add_handler(CommandHandler("roll", roll))
    application.add_handler(CommandHandler("coin", coin))
    application.add_handler(CommandHandler("slot", slot))
    application.add_handler(CommandHandler("dice", dice_game))
    application.add_handler(CommandHandler("basketball", basketball))
    application.add_handler(CommandHandler("basket", basketball))
    application.add_handler(CommandHandler("football", football))
    application.add_handler(CommandHandler("soccer", football))
    application.add_handler(CommandHandler("bowling", bowling))
    application.add_handler(CommandHandler("darts", darts))
    application.add_handler(CommandHandler("dnd", dnd_dice))
    application.add_handler(CommandHandler("guess", guess))
    application.add_handler(CommandHandler("stopguess", stop_guess))
    application.add_handler(CommandHandler("duel", duel))
    application.add_handler(CommandHandler("quiz", quiz))
    application.add_handler(CommandHandler("trivia", trivia))
    application.add_handler(CommandHandler("8ball", ball8))
    application.add_handler(CommandHandler("random", random_number))
    application.add_handler(CommandHandler("anagram", anagram))
    application.add_handler(CommandHandler("emojiquiz", emoji_quiz))

    # КАЗИНО
    application.add_handler(CommandHandler("bet_flip", bet_flip))
    application.add_handler(CommandHandler("roulette", roulette))
    application.add_handler(CommandHandler("blackjack", blackjack))
    application.add_handler(CommandHandler("bet_dice", bet_dice))

    # ЭКОНОМИКА
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("daily", daily))
    application.add_handler(CommandHandler("work", work))
    application.add_handler(CommandHandler("fish", fish))
    application.add_handler(CommandHandler("rob", rob))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("pay", pay))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("inventory", inventory))
    application.add_handler(CommandHandler("quests", quests))
    application.add_handler(CommandHandler("achievements", achievements_cmd))
    application.add_handler(CommandHandler("rep", rep))

    # ПРОФИЛЬ
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("bio", bio))
    application.add_handler(CommandHandler("title", title_cmd))

    # ОТНОШЕНИЯ
    application.add_handler(CommandHandler("marry", marry))
    application.add_handler(CommandHandler("accept", accept_marriage))
    application.add_handler(CommandHandler("decline", decline_marriage))
    application.add_handler(CommandHandler("divorce", divorce))
    application.add_handler(CommandHandler("couple", couple))
    application.add_handler(CommandHandler("love", love_calc))
    application.add_handler(CommandHandler("ship", ship))

    # RP
    for action_key in RP_ACTIONS.keys():
        application.add_handler(CommandHandler(action_key, make_rp_handler(action_key)))

    # РАЗВЛЕЧЕНИЯ
    application.add_handler(CommandHandler("quote", quote_cmd))
    application.add_handler(CommandHandler("avatar", avatar))
    application.add_handler(CommandHandler("color", random_color))
    application.add_handler(CommandHandler("joke", joke))
    application.add_handler(CommandHandler("fact", fact))
    application.add_handler(CommandHandler("idea", idea))
    application.add_handler(CommandHandler("choice", choice))
    application.add_handler(CommandHandler("predict", predict))

    # УТИЛИТЫ
    application.add_handler(CommandHandler("weather", weather))
    application.add_handler(CommandHandler("tr", translate))
    application.add_handler(CommandHandler("remind", remind))
    application.add_handler(CommandHandler("timer", timer_cmd))
    application.add_handler(CommandHandler("password", password))
    application.add_handler(CommandHandler("qr", qr_code))
    application.add_handler(CommandHandler("date", date_fact))
    application.add_handler(CommandHandler("time", time_cmd))

    # МОДЕРАЦИЯ
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("unmute", unmute))
    application.add_handler(CommandHandler("kick", kick))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("warn", warn))
    application.add_handler(CommandHandler("unwarn", unwarn))
    application.add_handler(CommandHandler("warns", warns))
    application.add_handler(CommandHandler("purge", purge))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("setrules", setrules))
    application.add_handler(CommandHandler("welcome", welcome_cmd))

    # КЛАНЫ
    application.add_handler(CommandHandler("create_clan", create_clan))
    application.add_handler(CommandHandler("clan_info", clan_info))
    application.add_handler(CommandHandler("clan_join", clan_join))
    application.add_handler(CommandHandler("clan_leave", clan_leave))
    application.add_handler(CommandHandler("clan_deposit", clan_deposit))
    application.add_handler(CommandHandler("clan_top", clan_top))
    application.add_handler(CommandHandler("clan_delete", clan_delete))

    # ЗАМЕТКИ
    application.add_handler(CommandHandler("save", save_note))
    application.add_handler(CommandHandler("get", get_note))
    application.add_handler(CommandHandler("notes", list_notes))
    application.add_handler(CommandHandler("del", del_note))

    # АДМИН
    application.add_handler(CommandHandler("adminhelp", admin_help))
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("admin_user", admin_user))
    application.add_handler(CommandHandler("admin_setbal", admin_setbal))
    application.add_handler(CommandHandler("admin_addbal", admin_addbal))
    application.add_handler(CommandHandler("admin_reset", admin_reset))
    application.add_handler(CommandHandler("admin_ban", admin_ban))
    application.add_handler(CommandHandler("admin_unban", admin_unban))
    application.add_handler(CommandHandler("admin_unmarry", admin_unmarry))
    application.add_handler(CommandHandler("admin_setname", admin_setname))
    application.add_handler(CommandHandler("admin_giveitem", admin_giveitem))
    application.add_handler(CommandHandler("admin_chats", admin_chats))
    application.add_handler(CommandHandler("admin_broadcast", admin_broadcast))
    application.add_handler(CommandHandler("admin_ping", admin_ping))
    application.add_handler(CommandHandler("admin_version", admin_version))

    # INLINE
    application.add_handler(CallbackQueryHandler(duel_callback, pattern=r"^duel_"))
    application.add_handler(CallbackQueryHandler(marry_callback, pattern=r"^marry_"))
    application.add_handler(CallbackQueryHandler(blackjack_callback, pattern=r"^bj_"))

    # NEW MEMBERS
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))

    # TEXT
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info("🚀 Бот запущен!")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        stop_signals=None,
        drop_pending_updates=True,
        bootstrap_retries=-1,
    )


if __name__ == "__main__":
    import threading
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Flask на порту {port}")
    flask_app.run(host="0.0.0.0", port=port)
