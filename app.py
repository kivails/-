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
    TOKEN, ADMIN_IDS, ADMIN_USERNAMES, DAILY_REWARD, DAILY_STREAK_BONUS, DAILY_MAX,
    QUIZ_REWARD, GUESS_REWARD, DUEL_REWARD, DICE_REWARD,
    SLOT_COST, SLOT_JACKPOT, SLOT_PAIR, START_BALANCE,
    WORK_COOLDOWN, WORK_MIN, WORK_MAX, ROB_COOLDOWN, ROB_SUCCESS_CHANCE, ROB_FINE,
    ROULETTE_MIN_BET, BLACKJACK_MIN_BET, COINFLIP_MIN_BET,
    SHOP_ITEMS, QUESTS, ACHIEVEMENTS, FISH, WORK_JOBS,
    RP_ACTIONS, BALL_ANSWERS, QUOTES, IDEAS, REFERRAL_BONUS,
    CUSTOM_RP_COST, ANNOUNCEMENT_COST
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
    return ("<html><body style='background:#1a1a2e;color:#eee;text-align:center;padding:50px;"
            "font-family:sans-serif'><h1>🤖 Бот работает</h1>"
            "<p style='color:#4ade80;font-size:20px'>✅ Online</p></body></html>"), 200


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
    ("Самый твёрдый минерал?", "алмаз"),
    ("Сколько будет 12 * 12?", "144"),
    ("Кто написал «Евгений Онегин»?", "пушкин"),
    ("Сколько континентов?", "6"),
    ("Язык в Бразилии?", "португальский"),
    ("Сколько будет 100 / 4?", "25"),
    ("Крупнейшая планета?", "юпитер"),
]

JOKES = [
    "— Что сказал программист, когда закончил работу? — Ещё один commit, и я спать.",
    "Программист — это машина для превращения кофе в код.",
    "— Почему программисты путают Хэллоуин и Рождество? — Потому что Oct 31 == Dec 25.",
    "Есть 10 типов людей: те, кто понимает двоичную систему, и те, кто нет.",
    "99 маленьких багов в коде... Уберёшь один — их 127.",
]

LINE = "━━━━━━━━━━━━━━━━━━━━━━━"


# ==================== ОФОРМЛЕНИЕ ====================

def frame(title: str, emoji: str = "✨") -> str:
    return f"╭──────────────────────────╮\n   {emoji}  {title}  {emoji}\n╰──────────────────────────╯"


def divider() -> str:
    return "━━━━━━━━━━━━━━━━━━━━━━━━━━"


def mention(user) -> str:
    return f"[{user.first_name}](tg://user?id={user.id})"


def mention_by_id(user_id: int, name: str = "Пользователь") -> str:
    return f"[{name}](tg://user?id={user_id})"


def plain_mention(user) -> str:
    """Просто имя со ссылкой, без подчёркиваний и звёзд — для безопасной отправки"""
    return f"[{user.first_name}](tg://user?id={user.id})"


def user_display(user_id: int, username: str = None, first_name: str = None) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return f"[{first_name}](tg://user?id={user_id})"
    return f"[ID {user_id}](tg://user?id={user_id})"


async def fetch_anime_gif(url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["results"][0]["url"]
    except Exception as e:
        logger.warning(f"gif fetch: {e}")
    return None


def is_bot_admin(user_id: int, username: str = None) -> bool:
    if user_id in ADMIN_IDS:
        return True
    if username and username.lower() in [u.lower() for u in ADMIN_USERNAMES]:
        return True
    return False


async def is_chat_admin(update, context) -> bool:
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def resolve_target(update, context):
    """Возвращает (user_object_or_None, display_string_or_None).
    Работает: reply → @username (в группе) → @username как строка (в ЛС)."""
    # 1. Reply
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        return u, plain_mention(u)

    # 2. Аргумент @username / username
    args = context.args or []
    if not args:
        return None, None

    raw = args[0]
    if not raw.startswith("@"):
        return None, None
    username = raw.lstrip("@")

    # В группе — пробуем получить user
    if update.effective_chat.type != "private":
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, username)
            return member.user, plain_mention(member.user)
        except Exception:
            pass

    # Не удалось — возвращаем строку
    return None, f"@{username}"


def check_quest(user_id: int, quest_key: str, increment: int = 1):
    user = db.get_user(user_id)
    progress = json.loads(user["quest_progress"] or '{}')
    progress[quest_key] = progress.get(quest_key, 0) + increment
    db.update_user(user_id, quest_progress=json.dumps(progress))
    _, target, reward = QUESTS[quest_key]
    if progress[quest_key] == target:
        db.add_balance(user_id, reward)
        return True, reward
    return False, 0


async def grant_achievement(update, user_id: int, ach_id: str):
    if ach_id not in ACHIEVEMENTS:
        return
    if db.add_achievement(user_id, ach_id):
        name, desc = ACHIEVEMENTS[ach_id]
        try:
            await update.message.reply_text(
                f"🏆 Новая ачивка!\n{name}\n_{desc}_",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            try:
                await update.message.reply_text(f"🏆 Новая ачивка: {name}")
            except Exception:
                pass


async def check_banned(update: Update) -> bool:
    u = update.effective_user
    db.get_user(u.id, u.username, u.first_name)
    data = db.get_user(u.id)
    if data["is_banned"]:
        return True
    return False


# ==================== START / HELP ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    db.get_user(u.id, u.username, u.first_name)

    # Реферальная обработка
    if context.args and context.args[0].startswith("ref_"):
        try:
            ref_id = int(context.args[0].replace("ref_", ""))
            if ref_id != u.id and db.add_referral(ref_id, u.id):
                try:
                    await context.bot.send_message(
                        ref_id,
                        f"🎉 Новый реферал! +{REFERRAL_BONUS} 💎"
                    )
                except Exception:
                    pass
        except (ValueError, IndexError):
            pass

    await grant_achievement(update, u.id, "first_steps")

    text = (
        f"🌟 Привет, {u.first_name}! 🌟\n"
        f"{divider()}\n"
        "Я — многофункциональный бот с играми, экономикой,\n"
        "RP-командами, браком, кланами и модерацией.\n\n"
        "📖 Все команды: /help\n"
        "🎮 Игры: /games\n"
        "💰 Экономика: /economy\n"
        "🎰 Казино: /casino\n"
        "💞 RP: /rp\n"
        "💍 Отношения: /lovehelp\n"
        "🎁 Кристаллы (рефералы): /referral\n"
        "👑 Кланы: /clans\n"
        f"{divider()}\n"
        "💡 _Добавь меня в группу!_"
    )
    try:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 СПРАВКА\n"
        f"{divider()}\n"
        "🎮 /games — игры\n"
        "💰 /economy — экономика\n"
        "🎰 /casino — казино\n"
        "💞 /rp — RP-действия\n"
        "💍 /lovehelp — отношения\n"
        "🎁 /referral — кристаллы\n"
        "👑 /clans — кланы\n"
        "🛡 /modhelp — модерация\n"
        "🔧 /utils — утилиты\n"
        "📌 /noteshelp — заметки\n"
        "🏆 /achievements — ачивки\n"
        f"{divider()}\n"
        "👤 /profile — профиль\n"
        "📊 /stats — статистика\n"
        "🏆 /top — топ\n"
        "🕐 /msk — время МСК\n"
        "💱 /currency — валюты"
    )
    await update.message.reply_text(text)


async def games_help(update, context):
    text = ("🎮 ИГРЫ\n"
            f"{divider()}\n"
            "🎲 /roll — кубик\n"
            "🪙 /coin — монетка\n"
            "🎯 /dice — кости\n"
            "🏀 /basketball — баскетбол\n"
            "⚽ /football — футбол\n"
            "🎳 /bowling — боулинг\n"
            "🎯 /darts — дартс\n"
            "🎰 /slot — автомат\n"
            "🔢 /guess — число\n"
            "🛑 /stopguess — стоп\n"
            "⚔️ /duel @юзер — дуэль\n"
            "❓ /quiz — викторина\n"
            "🎱 /8ball — шар\n"
            "🎲 /random от до")
    await update.message.reply_text(text)


async def economy_help(update, context):
    text = ("💰 ЭКОНОМИКА\n"
            f"{divider()}\n"
            "💵 /balance [@юзер]\n"
            "🎁 /daily — бонус\n"
            "💼 /work — работа\n"
            "🎣 /fish — рыбалка\n"
            "🥷 /rob @юзер\n"
            "🏆 /top — топ-10\n"
            "💸 /pay @юзер сумма\n"
            "🛒 /shop — магазин\n"
            "🛍 /buy ID\n"
            "🎒 /inventory\n"
            "📜 /quests\n"
            "🎁 /referral — кристаллы")
    await update.message.reply_text(text)


async def casino_help(update, context):
    text = ("🎰 КАЗИНО\n"
            f"{divider()}\n"
            "🎰 /slot\n"
            "🪙 /bet_flip орёл|решка сумма\n"
            "🎡 /roulette цвет|число сумма\n"
            "🃏 /blackjack сумма\n"
            "🎲 /bet_dice сумма")
    await update.message.reply_text(text)


async def rp_help(update, context):
    lines = [f"💞 RP-ДЕЙСТВИЯ\n{divider()}"]
    for key, data in RP_ACTIONS.items():
        emoji, action, _, ru = data
        lines.append(f"{emoji} /{key} или /{ru} — {action}")
    lines.append("")
    lines.append("💡 Работает: ответ на сообщение / @username")
    await update.message.reply_text("\n".join(lines))


async def love_help(update, context):
    text = ("💍 ОТНОШЕНИЯ\n"
            f"{divider()}\n"
            "💍 /marry @юзер\n"
            "✅ /accept\n"
            "❌ /decline\n"
            "💔 /divorce\n"
            "💞 /couple — показать пару\n"
            "💕 /love @юзер — совместимость\n"
            "🚢 /ship — рандом шип\n"
            "🎁 /marriage_gift — прокачать уровень брака")
    await update.message.reply_text(text)


async def mod_help(update, context):
    text = ("🛡 МОДЕРАЦИЯ\n"
            f"{divider()}\n"
            "🔇 /mute [10m]\n"
            "🔊 /unmute\n"
            "👢 /kick\n"
            "🚫 /ban\n"
            "✅ /unban\n"
            "⚠️ /warn\n"
            "🔹 /unwarn\n"
            "📋 /warns\n"
            "🧹 /purge N\n"
            "📜 /rules\n"
            "✏️ /setrules текст")
    await update.message.reply_text(text)


async def utils_help(update, context):
    text = ("🔧 УТИЛИТЫ\n"
            f"{divider()}\n"
            "🌤 /weather город\n"
            "🌐 /tr текст\n"
            "⏰ /remind 10m текст\n"
            "⏲ /timer 60\n"
            "🆔 /id\n"
            "🏓 /ping\n"
            "🔐 /password 16\n"
            "📱 /qr текст\n"
            "🎨 /color\n"
            "💱 /currency 100 USD RUB\n"
            "💎 /crypto BTC\n"
            "🕐 /msk — время МСК")
    await update.message.reply_text(text)


async def fun_help(update, context):
    text = ("🎲 РАЗВЛЕЧЕНИЯ\n"
            f"{divider()}\n"
            "🎱 /8ball вопрос\n"
            "💕 /love @юзер\n"
            "🚢 /ship\n"
            "🎭 /quote\n"
            "🖼 /avatar @юзер\n"
            "😄 /joke\n"
            "🧠 /fact\n"
            "💡 /idea\n"
            "🎲 /choice a | b | c\n"
            "🔮 /predict")
    await update.message.reply_text(text)


async def notes_help(update, context):
    await update.message.reply_text("📌 ЗАМЕТКИ\n/save имя текст\n/get имя\n/notes\n/del имя")


async def clans_help(update, context):
    text = ("👑 КЛАНЫ\n"
            f"{divider()}\n"
            "🏰 /create_clan Имя\n"
            "📋 /clans — список\n"
            "👥 /clan_info Имя\n"
            "➕ /clan_join Имя\n"
            "➖ /clan_leave\n"
            "💰 /clan_deposit сумма\n"
            "🏆 /clan_top\n"
            "🗑 /clan_delete")
    await update.message.reply_text(text)


async def about(update, context):
    text = (f"ℹ️ О БОТЕ\n{divider()}\n"
            "🤖 Версия: 7.0\n"
            f"💞 RP: {len(RP_ACTIONS)}\n"
            f"🏆 Ачивок: {len(ACHIEVEMENTS)}")
    await update.message.reply_text(text)


async def ping(update, context):
    t0 = datetime.now()
    msg = await update.message.reply_text("🏓 ...")
    dt = (datetime.now() - t0).total_seconds() * 1000
    await msg.edit_text(f"🏓 Понг! {dt:.0f}мс")


async def id_command(update, context):
    u = update.effective_user
    c = update.effective_chat
    text = f"🆔 Ваш ID: {u.id}\n💬 ID чата: {c.id}\n📛 Тип: {c.type}"
    if update.message.reply_to_message:
        t = update.message.reply_to_message.from_user
        text += f"\n👤 ID {t.first_name}: {t.id}"
    await update.message.reply_text(text)


# ==================== RP (главное!) ====================

async def send_rp(update, context, action_key: str):
    """Отправляет RP-действие. Работает: reply / @username / без цели."""
    emoji, action, api_url, _ = RP_ACTIONS[action_key]
    actor = update.effective_user
    db.get_user(actor.id, actor.username, actor.first_name)

    # Определяем цель
    target_user, target_display = await resolve_target(update, context)

    # Загружаем гифку
    gif = await fetch_anime_gif(api_url)

    # Формируем caption
    if target_display is None:
        caption = f"{emoji} {plain_mention(actor)} {action}"
    elif target_user and target_user.id == actor.id:
        caption = f"{emoji} {plain_mention(actor)} {action} себя 😅"
    else:
        caption = f"{emoji} {plain_mention(actor)} {action} {target_display}"

    # Прокачка брака, если это партнёр
    if target_user:
        actor_data = db.get_user(actor.id)
        if actor_data["married_to"] == target_user.id:
            db.add_marriage_xp(actor.id, 5)
            db.add_marriage_xp(target_user.id, 5)

    try:
        if gif:
            await update.message.reply_animation(
                animation=gif,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"RP send error: {e}")
        try:
            await update.message.reply_text(caption)
        except Exception:
            await update.message.reply_text(f"{emoji} {actor.first_name} {action}")

    await check_quest(actor.id, "rp_10")


def make_rp_handler(action_key: str):
    async def handler(update, context):
        await send_rp(update, context, action_key)
    return handler


async def custom_rp_dispatch(update, context, command):
    """Своя RP-команда из БД"""
    rp = db.get_custom_rp(command)
    if not rp:
        return
    _, owner_id, cmd, emoji, action = rp
    actor = update.effective_user
    target_user, target_display = await resolve_target(update, context)
    if target_display is None:
        caption = f"{emoji} {plain_mention(actor)} {action}"
    else:
        caption = f"{emoji} {plain_mention(actor)} {action} {target_display}"
    try:
        await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(caption)


# ==================== ВРЕМЯ / ВАЛЮТЫ ====================

async def moscow_time(update, context):
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://worldtimeapi.org/api/timezone/Europe/Moscow"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                data = await resp.json()
                dt_str = data["datetime"][:19].replace("T", " ")
                await update.message.reply_text(
                    f"🕐 МОСКВА (МСК)\n{divider()}\n📅 {dt_str}\n🌍 UTC{data['utc_offset']}"
                )
    except Exception:
        msk = datetime.now(timezone(timedelta(hours=3)))
        await update.message.reply_text(f"🕐 МСК: {msk.strftime('%d.%m.%Y %H:%M:%S')}")


async def currency(update, context):
    """Конвертер валют: фиат + крипта"""
    if not context.args:
        await update.message.reply_text(
            "💱 ВАЛЮТЫ\n"
            f"{divider()}\n"
            "`/currency 100 USD RUB`\n"
            "`/currency 5000 RUB USD`\n"
            "`/currency USD` — курс\n"
            "`/crypto BTC` — крипта\n\n"
            "Доступно: RUB, USD, EUR, UAH, BYN, KZT, AED, GBP\n"
            "Крипта: BTC, ETH, TON, SOL, BNB, XRP"
        )
        return

    args = context.args
    # /currency 100 USD RUB
    if len(args) >= 3 and args[0].replace('.', '').isdigit():
        try:
            amount = float(args[0])
            from_cur = args[1].upper()
            to_cur = args[2].upper()
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
                    await update.message.reply_text(f"💱 {amount:g} {from_cur} = {result:.2f} {to_cur}")
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
        return

    # /currency XXX — курс
    code = args[0].upper()
    crypto_map = {"BTC": "bitcoin", "TON": "the-open-network", "ETH": "ethereum",
                  "SOL": "solana", "BNB": "binancecoin", "XRP": "ripple"}
    if code in crypto_map:
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_map[code]}&vs_currencies=usd,rub"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
                    info = data[crypto_map[code]]
                    await update.message.reply_text(
                        f"💎 {code}\n{divider()}\n"
                        f"🇺🇸 ${info['usd']:,.2f}\n"
                        f"🇷🇺 {info['rub']:,.2f} ₽"
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
                uah = data["rates"].get("UAH")
                byn = data["rates"].get("BYN")
                aed = data["rates"].get("AED")
                await update.message.reply_text(
                    f"💱 КУРС {code}\n{divider()}\n"
                    f"🇷🇺 RUB: {rub}\n🇺🇸 USD: {usd}\n🇪🇺 EUR: {eur}\n"
                    f"🇺🇦 UAH: {uah}\n🇧🇾 BYN: {byn}\n🇦🇪 AED: {aed}"
                )
    except Exception:
        await update.message.reply_text("Ошибка получения курса.")


async def crypto(update, context):
    if not context.args:
        await update.message.reply_text("💎 /crypto BTC|ETH|TON|SOL|BNB|XRP")
        return
    context.args = [context.args[0]]
    await currency(update, context)


# ==================== РЕФЕРАЛЫ ====================

async def referral(update, context):
    u = update.effective_user
    db.get_user(u.id, u.username, u.first_name)
    crystals = db.get_crystals(u.id)
    count = db.get_referral_count(u.id)
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{u.id}"
    await update.message.reply_text(
        f"🎁 КРИСТАЛЛЫ\n{divider()}\n"
        f"🔗 Твоя ссылка:\n`{link}`\n\n"
        f"👥 Приглашено: {count}\n"
        f"💎 Кристаллов: {crystals:.1f}\n"
        f"{divider()}\n"
        f"_+{REFERRAL_BONUS} 💎 за каждого нового_"
    )


# ==================== ТОПЫ ====================

async def top(update, context):
    users = db.top_users(10)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"🏆 ТОП-10 ПО МОНЕТАМ\n{divider()}"]
    for i, (uid, uname, fname, bal) in enumerate(users):
        name = f"@{uname}" if uname else (fname or f"ID {uid}")
        lines.append(f"{medals[i]} {name} — {bal} 💰")
    await update.message.reply_text("\n".join(lines))


async def top_ref(update, context):
    users = db.top_crystals(3)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"💎 ТОП-3 ПО КРИСТАЛЛАМ\n{divider()}"]
    for i, (uid, uname, fname, c) in enumerate(users):
        name = f"@{uname}" if uname else (fname or f"ID {uid}")
        lines.append(f"{medals[i]} {name} — {(c or 0):.1f} 💎")
    await update.message.reply_text("\n".join(lines))


async def top_casino(update, context):
    users = db.top_wins(3)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🎰 ТОП-3 ПО ПОБЕДАМ\n{divider()}"]
    for i, (uid, uname, fname, w) in enumerate(users):
        name = f"@{uname}" if uname else (fname or f"ID {uid}")
        lines.append(f"{medals[i]} {name} — {w or 0} 🏆")
    await update.message.reply_text("\n".join(lines))


async def top_messages_all(update, context):
    users = db.top_messages(None, 10)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"💬 ТОП-10 ПО СООБЩЕНИЯМ (всё время)\n{divider()}"]
    for i, (uid, uname, fname, m) in enumerate(users):
        name = f"@{uname}" if uname else (fname or f"ID {uid}")
        lines.append(f"{medals[i]} {name} — {m or 0} 💬")
    await update.message.reply_text("\n".join(lines))


async def top_messages_day(update, context):
    users = db.top_messages(update.effective_chat.id, 10, days=1)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"💬 ТОП-10 ЗА СУТКИ\n{divider()}"]
    for i, (uid, uname, fname, m) in enumerate(users):
        name = f"@{uname}" if uname else (fname or f"ID {uid}")
        lines.append(f"{medals[i]} {name} — {m or 0} 💬")
    await update.message.reply_text("\n".join(lines))


async def top_messages_week(update, context):
    users = db.top_messages(update.effective_chat.id, 10, days=7)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"💬 ТОП-10 ЗА НЕДЕЛЮ\n{divider()}"]
    for i, (uid, uname, fname, m) in enumerate(users):
        name = f"@{uname}" if uname else (fname or f"ID {uid}")
        lines.append(f"{medals[i]} {name} — {m or 0} 💬")
    await update.message.reply_text("\n".join(lines))


async def chat_stats(update, context):
    """Статистика чата"""
    chat_id = update.effective_chat.id
    users = db.top_messages(chat_id, 100)
    total_msgs = sum(m or 0 for _, _, _, m in users)
    text = (
        f"📊 СТАТИСТИКА ЧАТА\n{divider()}\n"
        f"💬 Всего сообщений: {total_msgs}\n"
        f"👥 Активных участников: {len(users)}\n"
        f"🆔 ID чата: {chat_id}"
    )
    await update.message.reply_text(text)


async def all_chats_stats(update, context):
    """Все чаты, где есть бот — только для админов бота"""
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Только для админов.")
        return
    chats = db.get_all_chats()
    text = f"🌐 ЧАТЫ С БОТОМ ({len(chats)})\n{divider()}\n"
    for cid in chats[:50]:
        text += f"• {cid}\n"
    await update.message.reply_text(text)


# ==================== ИГРЫ ====================

async def roll(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
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
    await update.message.reply_text(f"🎲 {plain_mention(update.effective_user)} выбросил {result}", parse_mode=ParseMode.MARKDOWN)


async def coin(update, context):
    msg = await update.message.reply_dice(emoji="🎯")
    result = "🦅 Орёл" if msg.dice.value in (1, 2, 3) else "🪙 Решка"
    await update.message.reply_text(f"🪙 {plain_mention(update.effective_user)}: {result}", parse_mode=ParseMode.MARKDOWN)


async def dice_game(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    m1 = await update.message.reply_dice(emoji="🎲")
    m2 = await update.message.reply_dice(emoji="🎲")
    p, b = m1.dice.value, m2.dice.value
    db.update_user(uid, stats_played=(db.get_user(uid)["stats_played"] or 0) + 1)
    if p > b:
        db.add_balance(uid, DICE_REWARD)
        db.update_user(uid, stats_won=(db.get_user(uid)["stats_won"] or 0) + 1)
        res = f"🏆 Победа! +{DICE_REWARD}"
    elif p < b:
        res = "🤖 Бот победил"
    else:
        res = "🤝 Ничья"
    await update.message.reply_text(f"🎯 {plain_mention(update.effective_user)}: {p}\n🤖 Бот: {b}\n{res}", parse_mode=ParseMode.MARKDOWN)


async def basketball(update, context):
    msg = await update.message.reply_dice(emoji="🏀")
    s = msg.dice.value
    txt = "🏀 Точный бросок!" if s >= 4 else ("🏀 Почти!" if s >= 2 else "🏀 Мимо...")
    await update.message.reply_text(f"{plain_mention(update.effective_user)} бросает!\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def football(update, context):
    msg = await update.message.reply_dice(emoji="⚽")
    s = msg.dice.value
    txt = "⚽ ГООООЛ!" if s == 5 else ("⚽ Гол!" if s == 4 else ("⚽ Вратарь!" if s == 3 else "⚽ Мимо..."))
    await update.message.reply_text(f"{plain_mention(update.effective_user)} бьёт!\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def bowling(update, context):
    msg = await update.message.reply_dice(emoji="🎳")
    s = msg.dice.value
    txt = "🎳 СТРАЙК!" if s == 6 else f"🎳 Сбито {s} кеглей"
    await update.message.reply_text(f"{plain_mention(update.effective_user)} бросает!\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def darts(update, context):
    msg = await update.message.reply_dice(emoji="🎯")
    s = msg.dice.value
    txt = "🎯 В яблочко!" if s == 6 else f"🎯 Очки: {s * 10}"
    await update.message.reply_text(f"{plain_mention(update.effective_user)} кидает!\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def slot(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if db.get_balance(uid) < SLOT_COST:
        await update.message.reply_text("❌ Нужно 10 монет.")
        return
    msg = await update.message.reply_dice(emoji="🎰")
    v = msg.dice.value
    db.add_balance(uid, -SLOT_COST)
    if v >= 60:
        db.add_balance(uid, SLOT_JACKPOT)
        res = f"💥 ДЖЕКПОТ! +{SLOT_JACKPOT}"
        await grant_achievement(update, uid, "lucky")
    elif v >= 40:
        db.add_balance(uid, SLOT_PAIR)
        res = f"✨ Удача! +{SLOT_PAIR}"
    elif v >= 20:
        db.add_balance(uid, 5)
        res = "🙂 +5"
    else:
        res = "😢 -10"
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
    if v >= 40:
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    await update.message.reply_text(f"🎰 {plain_mention(update.effective_user)}\n{res}\n💰 {db.get_balance(uid)}", parse_mode=ParseMode.MARKDOWN)
    await check_quest(uid, "casino_10")


async def guess(update, context):
    chat_id = update.effective_chat.id
    if chat_id in guess_games:
        await update.message.reply_text("❌ Уже идёт. /stopguess")
        return
    guess_games[chat_id] = {'number': random.randint(1, 100), 'attempts': 0}
    await update.message.reply_text(f"🔢 Угадай число 1–100! +{GUESS_REWARD}")


async def stop_guess(update, context):
    chat_id = update.effective_chat.id
    if chat_id in guess_games:
        n = guess_games[chat_id]['number']
        del guess_games[chat_id]
        await update.message.reply_text(f"🛑 Было: {n}")


async def handle_guess(update, context):
    chat_id = update.effective_chat.id
    if chat_id not in guess_games:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        return
    n = int(text)
    g = guess_games[chat_id]
    g['attempts'] += 1
    if n < g['number']:
        await update.message.reply_text(f"📈 Больше! ({g['attempts']})")
    elif n > g['number']:
        await update.message.reply_text(f"📉 Меньше! ({g['attempts']})")
    else:
        uid = update.effective_user.id
        db.add_balance(uid, GUESS_REWARD)
        await update.message.reply_text(f"🎉 {plain_mention(update.effective_user)}! {g['number']}\n+{GUESS_REWARD}", parse_mode=ParseMode.MARKDOWN)
        del guess_games[chat_id]


async def duel(update, context):
    chat_id = update.effective_chat.id
    target_user, target_display = await resolve_target(update, context)
    if not target_user and not target_display:
        await update.message.reply_text("Использование: /duel @юзер (или ответом)")
        return
    if target_user and target_user.id == update.effective_user.id:
        await update.message.reply_text("Нельзя себя!")
        return
    challenger = update.effective_user
    if target_user:
        opp_id = target_user.id
        opp_name = target_user.first_name
    else:
        await update.message.reply_text("В личке дуэль только с известным юзером.")
        return
    duel_games[chat_id] = {
        'challenger': challenger.id, 'opponent': opp_id,
        'choice1': None, 'choice2': None,
        'names': {challenger.id: challenger.first_name, opp_id: opp_name}
    }
    kb = [[
        InlineKeyboardButton("✊", callback_data="duel_rock"),
        InlineKeyboardButton("✌️", callback_data="duel_scissors"),
        InlineKeyboardButton("✋", callback_data="duel_paper"),
    ]]
    await update.message.reply_text(
        f"⚔️ {plain_mention(challenger)} vs {target_display}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def duel_callback(update, context):
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
            db.add_balance(wid, DUEL_REWARD)
            res = f"🏆 {g['names'][wid]}! +{DUEL_REWARD}"
            await check_quest(wid, "duel_5")
        else:
            wid = g['opponent']
            db.add_balance(wid, DUEL_REWARD)
            res = f"🏆 {g['names'][wid]}! +{DUEL_REWARD}"
            await check_quest(wid, "duel_5")
        await q.edit_message_text(f"⚔️ Дуэль!\n{g['names'][g['challenger']]}: {c1}\n{g['names'][g['opponent']]}: {c2}\n{res}")
        del duel_games[chat_id]
    else:
        await q.answer("Ждём соперника.")


async def quiz(update, context):
    chat_id = update.effective_chat.id
    q, a = random.choice(QUIZ_QUESTIONS)
    quiz_games[chat_id] = {'answer': a.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(f"❓ Викторина!\n\n{q}\n\n+{QUIZ_REWARD}")


async def trivia(update, context):
    qs = [("Самый быстрый зверь?", "гепард"), ("Сколько ног у паука?", "8"),
          ("Самый большой океан?", "тихий"), ("Автор Гарри Поттера?", "роулинг")]
    chat_id = update.effective_chat.id
    q, a = random.choice(qs)
    quiz_games[chat_id] = {'answer': a.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(f"🧠 Тривия!\n\n{q}")


async def handle_quiz(update, context):
    chat_id = update.effective_chat.id
    if chat_id not in quiz_games:
        return
    text = update.message.text.strip().lower()
    if text == quiz_games[chat_id]['answer']:
        r = quiz_games[chat_id]['reward']
        uid = update.effective_user.id
        db.add_balance(uid, r)
        del quiz_games[chat_id]
        await update.message.reply_text(f"✅ Верно, {plain_mention(update.effective_user)}! +{r}", parse_mode=ParseMode.MARKDOWN)


async def ball8(update, context):
    if not context.args:
        await update.message.reply_text("🎱 /8ball вопрос")
        return
    q = " ".join(context.args)
    await update.message.reply_text(f"🎱 {q}\n{divider()}\n{random.choice(BALL_ANSWERS)}")


async def random_number(update, context):
    try:
        if len(context.args) >= 2:
            a, b = int(context.args[0]), int(context.args[1])
            if a > b: a, b = b, a
        else:
            a, b = 1, 100
    except ValueError:
        a, b = 1, 100
    await update.message.reply_text(f"🎲 От {a} до {b}: {random.randint(a, b)}")


async def bet_flip(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("/bet_flip орёл|решка сумма")
        return
    ch = context.args[0].lower()
    if ch not in ("орёл", "орел", "решка"):
        await update.message.reply_text("орёл или решка")
        return
    try:
        amount = int(context.args[1])
    except ValueError:
        return
    uid = update.effective_user.id
    if amount < COINFLIP_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет или мин. ставка не соблюдена.")
        return
    res = random.choice(["орёл", "решка"])
    db.add_balance(uid, -amount)
    if (ch in ("орёл", "орел") and res == "орёл") or (ch == "решка" and res == "решка"):
        db.add_balance(uid, amount * 2)
        await update.message.reply_text(f"🪙 {res}\n🎉 +{amount*2}")
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    else:
        await update.message.reply_text(f"🪙 {res}\n😢 -{amount}")
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
    await check_quest(uid, "casino_10")


async def roulette(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("/roulette красное|чёрное|число сумма")
        return
    ch = context.args[0].lower()
    try:
        amount = int(context.args[1])
    except ValueError:
        return
    uid = update.effective_user.id
    if amount < ROULETTE_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    red = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    r = random.randint(0, 36)
    color = "зелёное" if r == 0 else ("красное" if r in red else "чёрное")
    db.add_balance(uid, -amount)
    win = 0
    if ch in ("красное", "красный") and color == "красное": win = amount * 2
    elif ch in ("чёрное", "черное", "чёрный", "черный") and color == "чёрное": win = amount * 2
    elif ch.isdigit() and int(ch) == r: win = amount * 36
    if win:
        db.add_balance(uid, win)
        await update.message.reply_text(f"🎡 {r} ({color})\n🎉 +{win}")
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    else:
        await update.message.reply_text(f"🎡 {r} ({color})\n😢 -{amount}")
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
    await check_quest(uid, "casino_10")


async def blackjack(update, context):
    if not context.args:
        await update.message.reply_text("/blackjack сумма")
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        return
    uid = update.effective_user.id
    if amount < BLACKJACK_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
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
    db.add_balance(uid, -amount)
    blackjack_games[uid] = {'amount': amount, 'player': player, 'dealer': dealer, 'deck': deck}
    p, d = calc(player), calc(dealer)
    if p == 21 and d != 21:
        win = int(amount * 2.5)
        db.add_balance(uid, win)
        await update.message.reply_text(f"🃏 БЛЭКДЖЕК! +{win}")
        del blackjack_games[uid]
        return
    kb = [[InlineKeyboardButton("🎴 Ещё", callback_data=f"bj_hit:{uid}"),
           InlineKeyboardButton("🛑 Хватит", callback_data=f"bj_stand:{uid}")]]
    await update.message.reply_text(
        f"🃏 Блэкджек ({amount})\n{divider()}\n🎴 Ваши: {' '.join(player)} = {p}\n🎴 Дилер: {dealer[0]} ?",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def blackjack_callback(update, context):
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
    g = blackjack_games[uid]
    amount = g['amount']
    if action == "bj_hit":
        g['player'].append(g['deck'].pop())
        p = calc(g['player'])
        if p > 21:
            await q.edit_message_text(f"🃏 {' '.join(g['player'])} = {p}\n💥 Перебор! -{amount}")
            d = db.get_user(uid)
            db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
            del blackjack_games[uid]
            return
        kb = [[InlineKeyboardButton("🎴 Ещё", callback_data=f"bj_hit:{uid}"),
               InlineKeyboardButton("🛑 Хватит", callback_data=f"bj_stand:{uid}")]]
        await q.edit_message_text(
            f"🃏 Блэкджек ({amount})\n{divider()}\n🎴 Ваши: {' '.join(g['player'])} = {p}\n🎴 Дилер: {g['dealer'][0]} ?",
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
            win = amount * 2; db.add_balance(uid, win); msg = f"🏆 +{win}"
            d = db.get_user(uid); db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
        elif p == dv:
            db.add_balance(uid, amount); msg = "🤝 Ничья."
        else:
            msg = f"😢 -{amount}"
        await q.edit_message_text(f"🎴 Ваши: {' '.join(g['player'])} = {p}\n🎴 Дилер: {' '.join(g['dealer'])} = {dv}\n{msg}")
        d = db.get_user(uid)
        db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
        del blackjack_games[uid]


async def bet_dice(update, context):
    if not context.args:
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        return
    uid = update.effective_user.id
    if amount < 10 or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    db.add_balance(uid, -amount)
    p, b = random.randint(1, 6), random.randint(1, 6)
    if p > b:
        db.add_balance(uid, amount * 2)
        msg = f"🏆 +{amount*2}"
    elif p < b:
        msg = f"😢 -{amount}"
    else:
        db.add_balance(uid, amount)
        msg = "🤝 Ничья."
    await update.message.reply_text(f"🎲 Вы: {p} | Бот: {b}\n{msg}")
    await check_quest(uid, "casino_10")


# ==================== ЭКОНОМИКА ====================

async def balance(update, context):
    target = update.effective_user
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    db.get_user(target.id, target.username, target.first_name)
    b = db.get_balance(target.id)
    c = db.get_crystals(target.id)
    await update.message.reply_text(
        f"💰 {plain_mention(target)}\nБаланс: {b}\n💎 Кристаллы: {c:.1f}",
        parse_mode=ParseMode.MARKDOWN
    )


async def daily(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    user = db.get_user(uid)
    last = user["last_daily"]
    now = datetime.now()
    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt < timedelta(hours=24):
            r = timedelta(hours=24) - (now - last_dt)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ Через {h}ч {m}м.")
            return
    streak = (user["daily_streak"] or 0) + 1 if last and (now - datetime.fromisoformat(last)) < timedelta(hours=48) else 1
    reward = min(DAILY_REWARD + (streak - 1) * DAILY_STREAK_BONUS, DAILY_MAX)
    db.add_balance(uid, reward)
    db.update_user(uid, last_daily=now.isoformat(), daily_streak=streak)
    if streak >= 7:
        await grant_achievement(update, uid, "daily_7")
    if streak >= 30:
        await grant_achievement(update, uid, "daily_30")
    await update.message.reply_text(f"🎁 +{reward}\n🔥 Стрик: {streak}\n💰 {db.get_balance(uid)}")
    await check_quest(uid, "daily_3")


async def work(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    user = db.get_user(uid)
    last = user["last_work"]
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
    inv = (user["inventory"] or "").split(",")
    if "pickaxe" in inv:
        earned = int(earned * 1.3)
    db.add_balance(uid, earned)
    db.update_user(uid, last_work=now.isoformat())
    await update.message.reply_text(f"💼 Работал {job}\n💵 +{earned}")
    await check_quest(uid, "work_5")


async def fish(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    user = db.get_user(uid)
    last = user["last_fish"]
    now = datetime.now()
    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt < timedelta(minutes=15):
            m = (timedelta(minutes=15) - (now - last_dt)).seconds // 60
            await update.message.reply_text(f"⏳ Через {m} мин.")
            return
    inv = (user["inventory"] or "").split(",")
    bonus = 1.3 if "fishing_rod" in inv else 1.0
    roll = random.random(); cum = 0; caught = None
    for name, price, chance in FISH:
        cum += chance * bonus
        if roll <= cum:
            caught = (name, price); break
    if caught:
        name, price = caught
        db.add_balance(uid, price)
        await update.message.reply_text(f"🎣 {name}\n💵 +{price}")
    else:
        await update.message.reply_text("🎣 Ничего...")
    db.update_user(uid, last_fish=now.isoformat())
    await check_quest(uid, "fish_10")


async def rob(update, context):
    target_user, target_display = await resolve_target(update, context)
    if not target_user:
        await update.message.reply_text("Укажи @юзер или ответь.")
        return
    if target_user.id == update.effective_user.id:
        await update.message.reply_text("Себя нельзя!")
        return
    uid = update.effective_user.id
    db.get_user(uid)
    db.get_user(target_user.id, target_user.username, target_user.first_name)
    user = db.get_user(uid)
    last_rob = user["last_rob"]
    now = datetime.now()
    if last_rob:
        last_dt = datetime.fromisoformat(last_rob)
        if now - last_dt < timedelta(seconds=ROB_COOLDOWN):
            r = timedelta(seconds=ROB_COOLDOWN) - (now - last_dt)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ {h}ч {m}м.")
            return
    tb = db.get_balance(target_user.id)
    if tb < 50:
        await update.message.reply_text("Мало монет.")
        return
    if random.random() < ROB_SUCCESS_CHANCE:
        amount = random.randint(10, min(200, tb // 2))
        db.add_balance(uid, amount)
        db.add_balance(target_user.id, -amount)
        await update.message.reply_text(f"🥷 +{amount} у {target_display}", parse_mode=ParseMode.MARKDOWN)
    else:
        fine = min(ROB_FINE, db.get_balance(uid))
        db.add_balance(uid, -fine)
        await update.message.reply_text(f"🚨 Штраф {fine}.")
    db.update_user(uid, last_rob=now.isoformat())


async def pay(update, context):
    target = None
    amount = None
    # Reply
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        if context.args and context.args[0].isdigit():
            amount = int(context.args[0])
    # @username + сумма
    elif context.args and len(context.args) >= 2:
        name = context.args[0].lstrip("@")
        if context.args[1].isdigit():
            amount = int(context.args[1])
            if update.effective_chat.type != "private":
                try:
                    m = await context.bot.get_chat_member(update.effective_chat.id, name)
                    target = m.user
                except Exception:
                    pass
    if not target:
        await update.message.reply_text("❌ /pay @юзер 100 или ответом на сообщение")
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
    db.add_balance(uid, -amount)
    db.add_balance(target.id, amount)
    await update.message.reply_text(
        f"💸 {plain_mention(update.effective_user)} → {plain_mention(target)}: {amount}",
        parse_mode=ParseMode.MARKDOWN
    )


async def shop(update, context):
    lines = [f"🛒 МАГАЗИН\n{divider()}"]
    for iid, (name, price, desc) in SHOP_ITEMS.items():
        lines.append(f"{name}\n   {price} 💰 | _{desc}_\n   ID: {iid}")
    lines.append(f"\nКупить: /buy ID")
    try:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("\n".join(lines))


async def buy(update, context):
    if not context.args:
        await update.message.reply_text("/buy ID")
        return
    iid = context.args[0].lower()
    if iid not in SHOP_ITEMS:
        await update.message.reply_text("❌ Нет товара.")
        return
    name, price, desc = SHOP_ITEMS[iid]
    uid = update.effective_user.id
    if db.get_balance(uid) < price:
        await update.message.reply_text(f"❌ Нужно {price}")
        return
    db.add_balance(uid, -price)
    user = db.get_user(uid)
    inv = [i for i in (user["inventory"] or "").split(",") if i]
    inv.append(iid)
    db.update_user(uid, inventory=",".join(inv))
    await update.message.reply_text(f"✅ {name}\n💰 Осталось: {db.get_balance(uid)}")
    await check_quest(uid, "shop_3")


async def inventory(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    db.get_user(u.id, u.username, u.first_name)
    data = db.get_user(u.id)
    inv = [i for i in (data["inventory"] or "").split(",") if i]
    if not inv:
        await update.message.reply_text("🎒 Пусто.")
        return
    lines = [f"🎒 Инвентарь {u.first_name}:"]
    for iid in inv:
        if iid in SHOP_ITEMS:
            lines.append(f"• {SHOP_ITEMS[iid][0]}")
    await update.message.reply_text("\n".join(lines))


async def quests(update, context):
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    progress = json.loads(user["quest_progress"] or '{}')
    lines = [f"📜 КВЕСТЫ\n{divider()}"]
    for qid, (desc, target, reward) in QUESTS.items():
        cur = progress.get(qid, 0)
        st = "✅" if cur >= target else "⏳"
        lines.append(f"{st} {desc}\n   {cur}/{target} | +{reward}")
    await update.message.reply_text("\n".join(lines))


async def achievements_cmd(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    db.get_user(u.id, u.username, u.first_name)
    data = db.get_user(u.id)
    got = [g for g in (data["achievements"] or "").split(",") if g]
    lines = [f"🏆 АЧИВКИ {u.first_name} ({len(got)}/{len(ACHIEVEMENTS)})\n{divider()}"]
    for aid, (name, desc) in ACHIEVEMENTS.items():
        mark = "✅" if aid in got else "🔒"
        lines.append(f"{mark} {name}\n   _{desc}_")
    try:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("\n".join(lines))


async def rep(update, context):
    target_user, target_display = await resolve_target(update, context)
    if not target_user:
        await update.message.reply_text("Укажи @юзер.")
        return
    if target_user.id == update.effective_user.id:
        await update.message.reply_text("Себе нельзя.")
        return
    db.get_user(target_user.id, target_user.username, target_user.first_name)
    data = db.get_user(target_user.id)
    nr = (data["reputation"] or 0) + 1
    db.update_user(target_user.id, reputation=nr)
    await update.message.reply_text(f"⭐ {plain_mention(update.effective_user)} → {target_display}\nРепа: {nr}", parse_mode=ParseMode.MARKDOWN)


# ==================== ПРОФИЛЬ ====================

async def profile(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    db.get_user(u.id, u.username, u.first_name)
    data = db.get_user(u.id)

    partner = "нет"
    if data["married_to"]:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, data["married_to"])
            partner = m.user.first_name
        except Exception:
            partner = f"ID {data['married_to']}"

    clan = "нет"
    if data["clan_id"]:
        c = db.get_clan(data["clan_id"])
        if c:
            clan = c[1]

    title = f" [{data['title']}]" if data["title"] else ""
    bio_text = data["bio"] or "—"
    reg = data["registered"][:10] if data["registered"] else "—"
    got = [a for a in (data["achievements"] or "").split(",") if a]
    uname = f"@{data['username']}" if data["username"] else "—"

    text = (
        f"👤 {u.first_name}{title}\n"
        f"{divider()}\n"
        f"📛 {uname}\n"
        f"🆔 {u.id}\n"
        f"📅 Зашёл: {reg}\n"
        f"💬 Сообщений: {data['messages'] or 0}\n"
        f"{divider()}\n"
        f"💰 Монет: {data['balance']}\n"
        f"💎 Кристаллов: {(data['crystals'] or 0):.1f}\n"
        f"⭐ Репутация: {data['reputation'] or 0}\n"
        f"⚠️ Варнов: {data['warns']}\n"
        f"💞 Партнёр: {partner}\n"
        f"💍 Уровень брака: {data['marriage_level'] or 1}\n"
        f"👑 Клан: {clan}\n"
        f"📝 Био: {bio_text}\n"
        f"{divider()}\n"
        f"🎮 Игр: {data['stats_played']} | 🏆 Побед: {data['stats_won']}\n"
        f"🔥 Daily: {data['daily_streak'] or 0}\n"
        f"🎖 Ачивок: {len(got)}/{len(ACHIEVEMENTS)}"
    )
    await update.message.reply_text(text)


async def stats_cmd(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    db.get_user(u.id, u.username, u.first_name)
    data = db.get_user(u.id)
    played, won = data["stats_played"], data["stats_won"]
    pct = (won / played * 100) if played else 0
    await update.message.reply_text(
        f"📊 Статистика {u.first_name}\n{divider()}\n"
        f"🎮 Сыграно: {played}\n🏆 Побед: {won}\n📈 {pct:.1f}%\n"
        f"💰 Монет: {data['balance']}\n💎 Кристаллов: {(data['crystals'] or 0):.1f}\n"
        f"💬 Сообщений: {data['messages'] or 0}"
    )


async def bio(update, context):
    if not context.args:
        await update.message.reply_text("/bio текст")
        return
    db.get_user(update.effective_user.id)
    db.update_user(update.effective_user.id, bio=" ".join(context.args)[:200])
    await update.message.reply_text("✅ Био сохранено.")


async def title_cmd(update, context):
    uid = update.effective_user.id
    db.get_user(uid)
    inv = (db.get_user(uid)["inventory"] or "").split(",")
    if "vip" not in inv and "custom_title" not in inv:
        await update.message.reply_text("❌ Нужен VIP или «Своя приписка».")
        return
    if not context.args:
        await update.message.reply_text("/title текст")
        return
    db.update_user(uid, title=" ".join(context.args)[:30])
    await update.message.reply_text("✅ Приписка обновлена.")


# ==================== СВОИ RP ====================

async def add_rp(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    inv = (db.get_user(uid)["inventory"] or "").split(",")
    if "vip" not in inv:
        await update.message.reply_text(f"❌ Только для VIP. Купи /buy vip")
        return
    if len(context.args) < 3:
        await update.message.reply_text(
            "Использование:\n"
            "/add_rp команда эмодзи текст\n"
            "Пример: /add_rp щекотать 🤣 щекочет"
        )
        return
    command = context.args[0].lower().replace("/", "")
    emoji = context.args[1]
    action = " ".join(context.args[2:])[:60]
    if db.get_balance(uid) < CUSTOM_RP_COST:
        await update.message.reply_text(f"❌ Нужно {CUSTOM_RP_COST} монет.")
        return
    if db.add_custom_rp(uid, command, emoji, action):
        db.add_balance(uid, -CUSTOM_RP_COST)
        await update.message.reply_text(f"✅ Создана команда /{command}!\n-{CUSTOM_RP_COST} 💰")
    else:
        await update.message.reply_text("❌ Команда уже занята.")


async def my_rp(update, context):
    uid = update.effective_user.id
    rps = db.get_my_custom_rp(uid)
    if not rps:
        await update.message.reply_text("У тебя нет своих RP-команд. /add_rp")
        return
    lines = [f"💞 Твои RP-команды:"]
    for cmd, emoji, action in rps:
        lines.append(f"{emoji} /{cmd} — {action}")
    await update.message.reply_text("\n".join(lines))


# ==================== БРАК ====================

async def marry(update, context):
    actor = update.effective_user
    db.get_user(actor.id, actor.username, actor.first_name)
    user = db.get_user(actor.id)
    if user["married_to"]:
        await update.message.reply_text("💔 Уже в браке. /divorce")
        return
    target_user, target_display = await resolve_target(update, context)
    if not target_user:
        await update.message.reply_text("Укажи @юзер или ответь.")
        return
    if target_user.id == actor.id:
        await update.message.reply_text("😅 Нельзя.")
        return
    td = db.get_user(target_user.id, target_user.username, target_user.first_name)
    if td["married_to"]:
        await update.message.reply_text("Уже в браке.")
        return
    db.create_marriage_proposal(actor.id, target_user.id)
    kb = [[
        InlineKeyboardButton("✅ Принять", callback_data=f"marry_yes:{actor.id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"marry_no:{actor.id}"),
    ]]
    await update.message.reply_text(
        f"💍 Предложение!\n{divider()}\n{plain_mention(actor)} → {target_display}\n_{target_user.first_name}, твой ход..._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def marry_callback(update, context):
    q = update.callback_query
    await q.answer()
    action, pid_str = q.data.split(":")
    pid = int(pid_str)
    target = q.from_user
    if target.id == pid:
        await q.answer("Нельзя на себе!", show_alert=True)
        return
    prop = db.get_marriage_proposal(pid, target.id)
    if not prop:
        await q.answer("Не для тебя!", show_alert=True)
        return
    pd = db.get_user(pid)
    td = db.get_user(target.id, target.username, target.first_name)
    if action == "marry_yes":
        if pd["married_to"] or td["married_to"]:
            await q.edit_message_text("💔 Кто-то уже в браке.")
            db.delete_marriage_proposal(pid, target.id)
            return
        db.update_user(pid, married_to=target.id)
        db.update_user(target.id, married_to=pid)
        db.delete_marriage_proposal(pid, target.id)
        await q.edit_message_text(
            f"💍💞 Свадьба!\n{divider()}\n{plain_mention(target)}\n🎉 Поздравляем!",
            parse_mode=ParseMode.MARKDOWN
        )
        db.add_achievement(pid, "married")
        db.add_achievement(target.id, "married")
    else:
        db.delete_marriage_proposal(pid, target.id)
        await q.edit_message_text("💔 Отказ...")


async def divorce(update, context):
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    if not user["married_to"]:
        await update.message.reply_text("Не в браке.")
        return
    pid = user["married_to"]
    db.update_user(uid, married_to=None, marriage_level=1, marriage_xp=0)
    db.update_user(pid, married_to=None, marriage_level=1, marriage_xp=0)
    await update.message.reply_text("💔 Брак расторгнут.")


async def couple(update, context):
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    if not user["married_to"]:
        await update.message.reply_text("Не в браке. /marry")
        return
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, user["married_to"])
        partner = m.user
        await update.message.reply_text(
            f"💞 {plain_mention(update.effective_user)} + {plain_mention(partner)}\n"
            f"💍 Уровень брака: {user['marriage_level'] or 1}\n"
            f"💫 Опыт: {user['marriage_xp'] or 0}/{100 * (user['marriage_level'] or 1)}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        await update.message.reply_text(f"💞 ID партнёра: {user['married_to']}")


async def marriage_gift(update, context):
    """Подарок партнёру — прокачивает уровень брака"""
    uid = update.effective_user.id
    user = db.get_user(uid)
    if not user["married_to"]:
        await update.message.reply_text("Не в браке.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Использование: /marriage_gift сумма\n"
            f"Пример: /marriage_gift 100\n"
            f"За каждые 50 монет +1 уровень опыта"
        )
        return
    amount = int(context.args[0])
    if amount <= 0 or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Недостаточно монет.")
        return
    xp = amount // 50
    db.add_balance(uid, -amount)
    new_lvl = db.add_marriage_xp(uid, xp)
    db.add_marriage_xp(user["married_to"], xp)
    await update.message.reply_text(
        f"🎁 Подарок на {amount}!\n💍 Уровень брака: {new_lvl}\n+{xp} XP"
    )
    if new_lvl >= 5:
        await grant_achievement(update, uid, "love_lvl5")
    await check_quest(uid, "love_5")


async def love_calc(update, context):
    target_user, target_display = await resolve_target(update, context)
    if not target_user:
        await update.message.reply_text("Укажи @юзер.")
        return
    actor = update.effective_user
    pair = tuple(sorted([actor.id, target_user.id]))
    random.seed(pair)
    pct = random.randint(1, 100)
    random.seed()
    if pct >= 90: verdict = "💖 Идеальная пара!"
    elif pct >= 70: verdict = "💕 Отличная совместимость!"
    elif pct >= 50: verdict = "💛 Неплохо!"
    elif pct >= 30: verdict = "💔 Сложно..."
    else: verdict = "🖤 Не судьба"
    await update.message.reply_text(
        f"💕 Совместимость\n{divider()}\n{plain_mention(actor)} + {target_display}\n{pct}% — {verdict}",
        parse_mode=ParseMode.MARKDOWN
    )


async def ship(update, context):
    """Рандомный шип двух участников"""
    # Если ответили — шип с reply
    if update.message.reply_to_message:
        a = update.effective_user
        b = update.message.reply_to_message.from_user
    else:
        # Рандом из тех, кто писал в чат
        users = db.top_messages(update.effective_chat.id, 20)
        if len(users) < 2:
            await update.message.reply_text("Мало участников для шипа.")
            return
        pair = random.sample(users, 2)
        a = type("U", (), {"id": pair[0][0], "first_name": pair[0][2] or f"ID {pair[0][0]}"})()
        b = type("U", (), {"id": pair[1][0], "first_name": pair[1][2] or f"ID {pair[1][0]}"})()

    pair = tuple(sorted([a.id, b.id]))
    random.seed(pair)
    pct = random.randint(1, 100)
    random.seed()
    name = (a.first_name[:len(a.first_name)//2] + b.first_name[len(b.first_name)//2:])
    await update.message.reply_text(
        f"🚢 Рандомный шип!\n{divider()}\n"
        f"💑 {plain_mention(a)} + {plain_mention(b)}\n"
        f"💕 Название: {name}\n"
        f"📊 {pct}%\n{'💖' * (pct // 10)}",
        parse_mode=ParseMode.MARKDOWN
    )


# ==================== УТИЛИТЫ ====================

async def weather(update, context):
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
                    f"🌤 {city}\n{divider()}\n"
                    f"🌡 {cur['temp_C']}°C (ощущ. {cur['FeelsLikeC']}°C)\n"
                    f"☁️ {cur['weatherDesc'][0]['value']}\n"
                    f"💧 {cur['humidity']}%\n"
                    f"💨 {cur['windspeedKmph']} км/ч"
                )
    except Exception:
        await update.message.reply_text("Ошибка.")


async def translate(update, context):
    text = None
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    if not text:
        await update.message.reply_text("/tr текст")
        return
    try:
        async with aiohttp.ClientSession() as session:
            params = {"client": "gtx", "sl": "auto",
                      "tl": "ru" if any(c.isascii() for c in text) else "en",
                      "dt": "t", "q": text}
            async with session.get("https://translate.googleapis.com/translate_a/single",
                                   params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                translated = "".join(seg[0] for seg in data[0])
                await update.message.reply_text(f"🌐 {translated}")
    except Exception:
        await update.message.reply_text("Ошибка.")


async def remind(update, context):
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
    um = plain_mention(update.effective_user)
    async def task():
        await asyncio.sleep(sec)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ {um}, напоминание: {text}", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ Напоминание: {text}")
    asyncio.create_task(task())
    await update.message.reply_text(f"✅ Через {t}.")


async def timer_cmd(update, context):
    if not context.args:
        await update.message.reply_text("/timer 60")
        return
    try:
        sec = min(int(context.args[0]), 3600)
    except ValueError:
        return
    chat_id = update.effective_chat.id
    async def task():
        await asyncio.sleep(sec)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏲ Таймер {sec}с завершён!")
        except Exception:
            pass
    asyncio.create_task(task())
    await update.message.reply_text(f"⏲ Таймер {sec}с.")


async def password(update, context):
    length = 16
    if context.args:
        try:
            length = max(6, min(64, int(context.args[0])))
        except ValueError:
            pass
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    pwd = "".join(random.choice(chars) for _ in range(length))
    await update.message.reply_text(f"🔐 Пароль ({length}):\n{pwd}")


async def qr_code(update, context):
    if not context.args:
        await update.message.reply_text("/qr текст")
        return
    text = " ".join(context.args)[:500]
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={text}"
    try:
        await update.message.reply_photo(photo=url, caption="📱 QR")
    except Exception:
        await update.message.reply_text(f"📱 {url}")


async def random_color(update, context):
    c = "#{:06x}".format(random.randint(0, 0xFFFFFF))
    await update.message.reply_text(f"🎨 {c}")


async def joke(update, context):
    await update.message.reply_text(f"😄 {random.choice(JOKES)}")


async def fact(update, context):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://uselessfacts.jsph.pl/random.json?language=en",
                                   timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                await update.message.reply_text(f"🧠 {data['text']}")
    except Exception:
        await update.message.reply_text("Ошибка.")


async def idea(update, context):
    await update.message.reply_text(f"💡 {random.choice(IDEAS)}")


async def choice(update, context):
    if not context.args:
        await update.message.reply_text("/choice a | b | c")
        return
    opts = [o.strip() for o in " ".join(context.args).split("|") if o.strip()]
    if len(opts) < 2:
        await update.message.reply_text("2+ варианта через |")
        return
    await update.message.reply_text(f"🎲 {random.choice(opts)}")


async def predict(update, context):
    preds = ["🍀 Удача!", "📩 Хорошая новость!", "💸 Осторожно с деньгами",
             "💫 Встреча", "🚀 Действуй!", "😌 Отдохни", "😊 Улыбнись", "🎁 Сюрприз"]
    await update.message.reply_text(f"🔮 {random.choice(preds)}")


async def quote_cmd(update, context):
    text, author = random.choice(QUOTES)
    await update.message.reply_text(f"🎭 {text}\n— {author}")


async def avatar(update, context):
    target = update.effective_user
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    try:
        photos = await context.bot.get_user_profile_photos(target.id, limit=1)
        if not photos.photos:
            await update.message.reply_text("🖼 Нет аватара.")
            return
        fid = photos.photos[0][-1].file_id
        await update.message.reply_photo(photo=fid, caption=f"🖼 {target.first_name}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# ==================== МОДЕРАЦИЯ ====================

async def mute(update, context):
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
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
        await update.message.reply_text(f"🔇 {plain_mention(target)} на {duration // 60} мин.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def unmute(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                        can_send_other_messages=True, can_add_web_page_previews=True)
        )
        await update.message.reply_text(f"🔊 {plain_mention(target)} размучен.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def kick(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"👢 {plain_mention(target)} кикнут.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def ban(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🚫 {plain_mention(target)} забанен.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def unban(update, context):
    if not await is_chat_admin(update, context):
        return
    tid = None
    if update.message.reply_to_message:
        tid = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].lstrip("-").isdigit():
        tid = int(context.args[0])
    if not tid:
        return
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, tid)
        await update.message.reply_text(f"✅ Разбанен: {tid}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def warn(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    db.get_user(target.id, target.username, target.first_name)
    cur = db.get_user(target.id)["warns"]
    db.update_user(target.id, warns=cur + 1)
    new = cur + 1
    await update.message.reply_text(f"⚠️ {plain_mention(target)} — {new}/3", parse_mode=ParseMode.MARKDOWN)
    if new >= 3:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, target.id)
            await update.message.reply_text(f"🚫 Забанен за 3 варна.", parse_mode=ParseMode.MARKDOWN)
            db.update_user(target.id, warns=0)
        except Exception:
            pass


async def unwarn(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    cur = db.get_user(target.id)["warns"]
    if cur > 0:
        db.update_user(target.id, warns=cur - 1)
    await update.message.reply_text(f"✅ Снят. Осталось: {max(0, cur - 1)}")


async def warns_cmd(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    db.get_user(u.id)
    await update.message.reply_text(f"⚠️ Варнов у {u.first_name}: {db.get_user(u.id)['warns']}")


async def purge(update, context):
    if not await is_chat_admin(update, context):
        return
    if not context.args or not context.args[0].isdigit():
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


async def rules(update, context):
    chat = db.get_chat(update.effective_chat.id)
    if not chat[2]:
        await update.message.reply_text("Правил нет.")
        return
    await update.message.reply_text(f"📜 Правила:\n{chat[2]}")


async def setrules(update, context):
    if not await is_chat_admin(update, context) or not context.args:
        return
    db.update_chat(update.effective_chat.id, rules=" ".join(context.args)[:1000])
    await update.message.reply_text("✅ Сохранено.")


async def welcome_cmd(update, context):
    if not await is_chat_admin(update, context) or not context.args:
        return
    db.update_chat(update.effective_chat.id, welcome=" ".join(context.args)[:500])
    await update.message.reply_text("✅ Сохранено.")


async def on_new_member(update, context):
    for m in update.message.new_chat_members:
        chat = db.get_chat(update.effective_chat.id)
        text = chat[1] or "👋 Добро пожаловать, {name}!"
        text = text.replace("{name}", m.first_name)
        try:
            await update.message.reply_text(text)
        except Exception:
            pass


# ==================== КЛАНЫ ====================

async def create_clan(update, context):
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
    if user["clan_id"]:
        await update.message.reply_text("❌ Уже в клане.")
        return
    cid = db.create_clan(name, uid, desc)
    if not cid:
        await update.message.reply_text("❌ Ошибка.")
        return
    db.update_user(uid, clan_id=cid)
    await grant_achievement(update, uid, "clan_owner")
    await update.message.reply_text(f"🏰 Клан {name} создан!")


async def clans_list(update, context):
    clans = db.get_all_clans(20)
    if not clans:
        await update.message.reply_text("Пусто.")
        return
    lines = [f"🏰 КЛАНЫ\n{divider()}"]
    for c in clans:
        lines.append(f"🏰 {c[1]} — {c[5]} 💰 ({len(db.get_clan_members(c[0]))})")
    await update.message.reply_text("\n".join(lines))


async def clan_info(update, context):
    if not context.args:
        await update.message.reply_text("/clan_info Имя")
        return
    c = db.get_clan_by_name(context.args[0])
    if not c:
        await update.message.reply_text("Не найден.")
        return
    members = db.get_clan_members(c[0])
    lines = [f"🏰 {c[1]}\n{divider()}",
             f"👑 Владелец: ID {c[2]}",
             f"💰 Баланс: {c[5]}",
             f"📝 {c[3] or '—'}",
             f"👥 Участники ({len(members)}):"]
    for uid, uname, fname, bal in members[:20]:
        lines.append(f"• @{uname}" if uname else f"• {fname or uid}")
    await update.message.reply_text("\n".join(lines))


async def clan_join(update, context):
    if not context.args:
        return
    c = db.get_clan_by_name(context.args[0])
    if not c:
        await update.message.reply_text("Не найден.")
        return
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    if user["clan_id"]:
        await update.message.reply_text("❌ Уже в клане.")
        return
    db.update_user(uid, clan_id=c[0])
    await update.message.reply_text(f"✅ Вступил в {c[1]}")


async def clan_leave(update, context):
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    if not user["clan_id"]:
        await update.message.reply_text("Не в клане.")
        return
    c = db.get_clan(user["clan_id"])
    if c and c[2] == uid:
        await update.message.reply_text("Ты владелец. /clan_delete")
        return
    db.update_user(uid, clan_id=None)
    await update.message.reply_text("👋 Покинул клан.")


async def clan_deposit(update, context):
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    if not user["clan_id"]:
        await update.message.reply_text("Не в клане.")
        return
    if not context.args or not context.args[0].isdigit():
        return
    amount = int(context.args[0])
    if amount <= 0 or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    db.add_balance(uid, -amount)
    db.add_clan_balance(user["clan_id"], amount)
    await update.message.reply_text(f"💰 Внесено {amount}")


async def clan_top(update, context):
    clans = db.get_all_clans(10)
    if not clans:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"🏆 ТОП КЛАНОВ\n{divider()}"]
    for i, c in enumerate(clans):
        lines.append(f"{medals[i]} {c[1]} — {c[5]} 💰")
    await update.message.reply_text("\n".join(lines))


async def clan_delete(update, context):
    uid = update.effective_user.id
    db.get_user(uid)
    user = db.get_user(uid)
    if not user["clan_id"]:
        await update.message.reply_text("Не в клане.")
        return
    c = db.get_clan(user["clan_id"])
    if not c or c[2] != uid:
        await update.message.reply_text("Только владелец.")
        return
    db.delete_clan(c[0])
    await update.message.reply_text("🗑 Удалён.")


# ==================== ЗАМЕТКИ ====================

async def save_note(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("/save имя текст")
        return
    name = context.args[0].lower()
    content = " ".join(context.args[1:])
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO notes(chat_id, name, content) VALUES(?, ?, ?)",
                    (update.effective_chat.id, name, content))
        conn.commit()
    await update.message.reply_text(f"✅ Заметка {name} сохранена.")


async def get_note(update, context):
    if not context.args:
        return
    name = context.args[0].lower()
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT content FROM notes WHERE chat_id=? AND name=?",
                    (update.effective_chat.id, name))
        row = cur.fetchone()
    if row:
        await update.message.reply_text(f"📝 {row[0]}")
    else:
        await update.message.reply_text("Не найдено.")


async def list_notes(update, context):
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM notes WHERE chat_id=?", (update.effective_chat.id,))
        rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Пусто.")
        return
    await update.message.reply_text("📝 " + ", ".join(r[0] for r in rows))


async def del_note(update, context):
    if not context.args:
        return
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE chat_id=? AND name=?",
                    (update.effective_chat.id, context.args[0].lower()))
        conn.commit()
    await update.message.reply_text("🗑 Удалено.")


# ==================== ОБЪЯВЛЕНИЯ ====================

async def announcement(update, context):
    """Объявление за 100 кристаллов — отправится во все чаты"""
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)

    if not context.args:
        await update.message.reply_text(
            f"📢 ОБЪЯВЛЕНИЕ\n{divider()}\n"
            f"Цена: {ANNOUNCEMENT_COST} 💎\n\n"
            f"Использование: /announcement текст\n"
            f"Объявление увидят все чаты бота."
        )
        return

    if db.get_crystals(uid) < ANNOUNCEMENT_COST:
        await update.message.reply_text(f"❌ Нужно {ANNOUNCEMENT_COST} 💎. Заработай /referral.")
        return

    text = " ".join(context.args)[:500]
    db.add_crystals(uid, -ANNOUNCEMENT_COST)
    db.add_announcement(uid, text)
    chats = db.get_all_chats()
    sent = 0
    for cid in chats:
        try:
            await context.bot.send_message(
                chat_id=cid,
                text=f"📢 ОБЪЯВЛЕНИЕ\n{divider()}\n{text}\n\nОт: {update.effective_user.first_name}"
            )
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Отправлено в {sent} чатов.\n-{ANNOUNCEMENT_COST} 💎")


async def announcements_list(update, context):
    items = db.get_last_announcements(5)
    if not items:
        await update.message.reply_text("Объявлений нет.")
        return
    lines = [f"📢 ПОСЛЕДНИЕ ОБЪЯВЛЕНИЯ\n{divider()}"]
    for uid, text, dt in items:
        lines.append(f"👤 ID {uid}: {text[:80]}")
    await update.message.reply_text("\n".join(lines))


# ==================== АДМИН-ПАНЕЛЬ ====================

async def admin_help(update, context):
    uid = update.effective_user.id
    uname = update.effective_user.username
    logger.info(f"ADMIN CHECK: uid={uid}, uname=@{uname}, ADMIN_IDS={ADMIN_IDS}, is_admin={is_bot_admin(uid, uname)}")

    if not is_bot_admin(uid, uname):
        await update.message.reply_text("❌ Доступ только для админов бота.")
        return

    text = (
        "👑 АДМИН-ПАНЕЛЬ 👑\n"
        f"{divider()}\n"
        "👤 ПОЛЬЗОВАТЕЛИ:\n"
        "admin_user @юзер — инфо\n"
        "admin_setbal @юзер сумма\n"
        "admin_addbal @юзер сумма\n"
        "admin_takebal @юзер сумма — забрать монеты\n"
        "admin_setcrystals @юзер сумма — выдать 💎\n"
        "admin_takecrystals @юзер сумма — забрать 💎\n"
        "admin_reset @юзер — сброс\n"
        "admin_ban @юзер — бан в боте\n"
        "admin_unban @юзер\n"
        "admin_freeze @юзер — заморозить\n"
        "admin_unfreeze @юзер — разморозить\n"
        "admin_unmarry @юзер\n"
        "admin_setname @юзер имя\n"
        "admin_giveitem @юзер ID\n"
        "admin_giveach @юзер ach_id — выдать ачивку\n"
        "\n🌐 ЧАТЫ:\n"
        "admin_chats — список\n"
        "admin_broadcast текст — рассылка\n"
        "admin_stats — статистика\n"
        "\n⚙️ СИСТЕМА:\n"
        "admin_ping\n"
        "admin_version"
    )
    await update.message.reply_text(text)


async def admin_stats(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users"); tu = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE married_to IS NOT NULL"); m = cur.fetchone()[0] // 2
        cur.execute("SELECT COUNT(*) FROM chats"); tc = cur.fetchone()[0]
        cur.execute("SELECT SUM(balance) FROM users"); tb = cur.fetchone()[0] or 0
        cur.execute("SELECT SUM(stats_played) FROM users"); tg = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM clans"); tcl = cur.fetchone()[0]
    await update.message.reply_text(
        f"📊 СТАТИСТИКА\n{divider()}\n"
        f"👥 Юзеров: {tu}\n💬 Чатов: {tc}\n💑 Пар: {m}\n"
        f"🏰 Кланов: {tcl}\n💰 Всего монет: {tb}\n🎮 Игр: {tg}"
    )


async def _resolve_admin_target(update, context):
    """Возвращает user_data (dict) или None"""
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        return db.get_user(u.id, u.username, u.first_name)
    if context.args:
        name = context.args[0].lstrip("@")
        if update.effective_chat.type != "private":
            try:
                m = await context.bot.get_chat_member(update.effective_chat.id, name)
                return db.get_user(m.user.id, m.user.username, m.user.first_name)
            except Exception:
                pass
        # fallback — по username из БД
        with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (name,))
            row = cur.fetchone()
            if row:
                return db._row_to_dict(row)
    return None


async def admin_user(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        await update.message.reply_text("Укажи @юзер.")
        return
    await update.message.reply_text(
        f"👤 {data['first_name']}\n{divider()}\n"
        f"ID: {data['user_id']}\n"
        f"@: {data['username'] or '—'}\n"
        f"💰 {data['balance']}\n"
        f"💎 {(data['crystals'] or 0):.1f}\n"
        f"⚠️ {data['warns']}\n"
        f"🚫 Бан: {'ДА' if data['is_banned'] else 'нет'}\n"
        f"🧊 Заморожен: {'ДА' if data['is_frozen'] else 'нет'}\n"
        f"💑 {data['married_to'] or '—'}\n"
        f"👑 Клан: {data['clan_id'] or '—'}\n"
        f"🎮 {data['stats_played']} / 🏆 {data['stats_won']}\n"
        f"💬 {data['messages'] or 0}\n"
        f"⭐ {data['reputation'] or 0}"
    )


async def admin_setbal(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    # если reply — берём args[0]; если @ — args[1]
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx or not context.args[idx].lstrip("-").isdigit():
        await update.message.reply_text("Укажи сумму.")
        return
    amount = int(context.args[idx])
    db.update_user(data["user_id"], balance=amount)
    await update.message.reply_text(f"✅ Баланс {data['first_name']} = {amount}")


async def admin_addbal(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    try:
        amount = int(context.args[idx])
    except ValueError:
        return
    db.add_balance(data["user_id"], amount)
    await update.message.reply_text(f"✅ +{amount} → {data['first_name']}")


async def admin_takebal(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    try:
        amount = int(context.args[idx])
    except ValueError:
        return
    db.add_balance(data["user_id"], -amount)
    await update.message.reply_text(f"✅ -{amount} у {data['first_name']}")


async def admin_setcrystals(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    try:
        amount = float(context.args[idx])
    except ValueError:
        return
    db.update_user(data["user_id"], crystals=amount)
    await update.message.reply_text(f"✅ Кристаллы {data['first_name']} = {amount}")


async def admin_takecrystals(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    try:
        amount = float(context.args[idx])
    except ValueError:
        return
    db.add_crystals(data["user_id"], -amount)
    await update.message.reply_text(f"✅ -{amount} 💎 у {data['first_name']}")


async def admin_reset(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    db.update_user(data["user_id"], balance=START_BALANCE, warns=0, married_to=None,
                   inventory="", stats_played=0, stats_won=0, daily_streak=0,
                   quest_progress="{}", achievements="", clan_id=None, reputation=0,
                   crystals=0, referral_count=0, messages=0, marriage_level=1, marriage_xp=0)
    await update.message.reply_text(f"🔄 {data['first_name']} сброшен.")


async def admin_ban(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_banned=1)
    await update.message.reply_text(f"🚫 {data['first_name']} забанен в боте.")


async def admin_unban(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_banned=0)
    await update.message.reply_text(f"✅ {data['first_name']} разбанен.")


async def admin_freeze(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_frozen=1)
    await update.message.reply_text(f"🧊 {data['first_name']} заморожен.")


async def admin_unfreeze(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_frozen=0)
    await update.message.reply_text(f"🔥 {data['first_name']} разморожен.")


async def admin_unmarry(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data or not data["married_to"]:
        return
    db.update_user(data["user_id"], married_to=None, marriage_level=1, marriage_xp=0)
    db.update_user(data["married_to"], married_to=None, marriage_level=1, marriage_xp=0)
    await update.message.reply_text(f"💔 Разведён(а).")


async def admin_setname(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    new_name = " ".join(context.args[idx:])[:40]
    db.update_user(data["user_id"], first_name=new_name)
    await update.message.reply_text(f"✅ Имя: {new_name}")


async def admin_giveitem(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    iid = context.args[idx].lower()
    if iid not in SHOP_ITEMS:
        await update.message.reply_text("Нет такого.")
        return
    inv = [i for i in (data["inventory"] or "").split(",") if i]
    inv.append(iid)
    db.update_user(data["user_id"], inventory=",".join(inv))
    await update.message.reply_text(f"✅ {SHOP_ITEMS[iid][0]} → {data['first_name']}")


async def admin_giveach(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve_admin_target(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        await update.message.reply_text("Укажи ach_id.")
        return
    aid = context.args[idx]
    if aid not in ACHIEVEMENTS:
        await update.message.reply_text("Нет такой ачивки.")
        return
    db.add_achievement(data["user_id"], aid)
    await update.message.reply_text(f"🏆 {ACHIEVEMENTS[aid][0]} → {data['first_name']}")


async def admin_broadcast(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    if not context.args:
        return
    text = " ".join(context.args)
    chats = db.get_all_chats()
    sent = 0
    for cid in chats:
        try:
            await context.bot.send_message(chat_id=cid, text=f"📢 РАССЫЛКА\n{divider()}\n{text}")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"📢 OK: {sent}")


async def admin_chats(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    chats = db.get_all_chats()
    await update.message.reply_text(f"💬 Всего чатов: {len(chats)}\n" + "\n".join(str(c) for c in chats[:30]))


async def admin_ping(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    t0 = datetime.now()
    msg = await update.message.reply_text("🏓")
    dt = (datetime.now() - t0).total_seconds() * 1000
    await msg.edit_text(f"🏓 {dt:.0f}ms")


async def admin_version(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    await update.message.reply_text("🤖 v7.0")


# ==================== TEXT ROUTER ====================

async def text_router(update, context):
    u = update.effective_user
    db.get_user(u.id, u.username, u.first_name)
    data = db.get_user(u.id)

    # Бан/заморозка
    if data["is_banned"] or data["is_frozen"]:
        return

    # Учёт сообщений
    try:
        db.add_message(u.id, update.effective_chat.id)
    except Exception:
        pass

    # Ачивка за 1000 сообщений
    if (data["messages"] or 0) >= 1000:
        try:
            db.add_achievement(u.id, "chatterbox")
        except Exception:
            pass

    # Обработка угадаек
    await handle_guess(update, context)
    await handle_quiz(update, context)

    # Своя RP-команда (если текст начинается с /) — обрабатывается как команда, не сюда
    # В группах: если текст начинается с /команда, и это своя RP — обработаем через command dispatcher ниже


# ==================== ЗАПУСК ====================

def run_bot():
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())

    db.init_db()

    async def post_init(app):
        try:
            commands = [
                BotCommand("start", "🚀 Старт"),
                BotCommand("help", "📖 Команды"),
                BotCommand("profile", "👤 Профиль"),
                BotCommand("balance", "💰 Баланс"),
                BotCommand("daily", "🎁 Бонус"),
                BotCommand("work", "💼 Работа"),
                BotCommand("fish", "🎣 Рыбалка"),
                BotCommand("top", "🏆 Топ монет"),
                BotCommand("top_ref", "💎 Топ кристаллов"),
                BotCommand("top_casino", "🎰 Топ побед"),
                BotCommand("shop", "🛒 Магазин"),
                BotCommand("games", "🎮 Игры"),
                BotCommand("casino", "🎰 Казино"),
                BotCommand("rp", "💞 RP"),
                BotCommand("referral", "🎁 Кристаллы"),
                BotCommand("msk", "🕐 МСК"),
                BotCommand("currency", "💱 Валюты"),
                BotCommand("marry", "💍 Брак"),
                BotCommand("clans", "👑 Кланы"),
                BotCommand("adminhelp", "👑 Админ"),
            ]
            await app.bot.set_my_commands(commands)
        except Exception as e:
            logger.warning(f"set_my_commands: {e}")

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # Базовые
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("id", id_command))

    # Справки
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

    # Время/валюты
    application.add_handler(CommandHandler("msk", moscow_time))
    application.add_handler(CommandHandler("moscow", moscow_time))
    application.add_handler(CommandHandler("currency", currency))
    application.add_handler(CommandHandler("crypto", crypto))

    # Рефералы
    application.add_handler(CommandHandler("referral", referral))
    application.add_handler(CommandHandler("ref", referral))

    # Топы
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("top_ref", top_ref))
    application.add_handler(CommandHandler("top_casino", top_casino))
    application.add_handler(CommandHandler("top_day", top_messages_day))
    application.add_handler(CommandHandler("top_week", top_messages_week))
    application.add_handler(CommandHandler("top_messages", top_messages_all))
    application.add_handler(CommandHandler("chat_stats", chat_stats))
    application.add_handler(CommandHandler("all_chats", all_chats_stats))

    # Игры
    application.add_handler(CommandHandler("roll", roll))
    application.add_handler(CommandHandler("coin", coin))
    application.add_handler(CommandHandler("dice", dice_game))
    application.add_handler(CommandHandler("basketball", basketball))
    application.add_handler(CommandHandler("basket", basketball))
    application.add_handler(CommandHandler("football", football))
    application.add_handler(CommandHandler("soccer", football))
    application.add_handler(CommandHandler("bowling", bowling))
    application.add_handler(CommandHandler("darts", darts))
    application.add_handler(CommandHandler("slot", slot))
    application.add_handler(CommandHandler("guess", guess))
    application.add_handler(CommandHandler("stopguess", stop_guess))
    application.add_handler(CommandHandler("duel", duel))
    application.add_handler(CommandHandler("quiz", quiz))
    application.add_handler(CommandHandler("trivia", trivia))
    application.add_handler(CommandHandler("8ball", ball8))
    application.add_handler(CommandHandler("random", random_number))

    # Казино
    application.add_handler(CommandHandler("bet_flip", bet_flip))
    application.add_handler(CommandHandler("roulette", roulette))
    application.add_handler(CommandHandler("blackjack", blackjack))
    application.add_handler(CommandHandler("bet_dice", bet_dice))

    # Экономика
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("daily", daily))
    application.add_handler(CommandHandler("work", work))
    application.add_handler(CommandHandler("fish", fish))
    application.add_handler(CommandHandler("rob", rob))
    application.add_handler(CommandHandler("pay", pay))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("inventory", inventory))
    application.add_handler(CommandHandler("quests", quests))
    application.add_handler(CommandHandler("achievements", achievements_cmd))
    application.add_handler(CommandHandler("rep", rep))

    # Профиль
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("bio", bio))
    application.add_handler(CommandHandler("title", title_cmd))

    # Свои RP
    application.add_handler(CommandHandler("add_rp", add_rp))
    application.add_handler(CommandHandler("my_rp", my_rp))

    # Брак
    application.add_handler(CommandHandler("marry", marry))
    application.add_handler(CommandHandler("divorce", divorce))
    application.add_handler(CommandHandler("couple", couple))
    application.add_handler(CommandHandler("marriage_gift", marriage_gift))
    application.add_handler(CommandHandler("love", love_calc))
    application.add_handler(CommandHandler("ship", ship))

    # RP (англ)
    for action_key in RP_ACTIONS.keys():
        application.add_handler(CommandHandler(action_key, make_rp_handler(action_key)))

    # RP (русские алиасы)
    for action_key, data in RP_ACTIONS.items():
        ru = data[3]
        if ru:
            application.add_handler(CommandHandler(ru, make_rp_handler(action_key)))

    # Утилиты
    application.add_handler(CommandHandler("weather", weather))
    application.add_handler(CommandHandler("tr", translate))
    application.add_handler(CommandHandler("remind", remind))
    application.add_handler(CommandHandler("timer", timer_cmd))
    application.add_handler(CommandHandler("password", password))
    application.add_handler(CommandHandler("qr", qr_code))
    application.add_handler(CommandHandler("color", random_color))
    application.add_handler(CommandHandler("joke", joke))
    application.add_handler(CommandHandler("fact", fact))
    application.add_handler(CommandHandler("idea", idea))
    application.add_handler(CommandHandler("choice", choice))
    application.add_handler(CommandHandler("predict", predict))
    application.add_handler(CommandHandler("quote", quote_cmd))
    application.add_handler(CommandHandler("avatar", avatar))

    # Модерация
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("unmute", unmute))
    application.add_handler(CommandHandler("kick", kick))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("warn", warn))
    application.add_handler(CommandHandler("unwarn", unwarn))
    application.add_handler(CommandHandler("warns", warns_cmd))
    application.add_handler(CommandHandler("purge", purge))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("setrules", setrules))
    application.add_handler(CommandHandler("welcome", welcome_cmd))

    # Кланы
    application.add_handler(CommandHandler("create_clan", create_clan))
    application.add_handler(CommandHandler("clan_info", clan_info))
    application.add_handler(CommandHandler("clan_join", clan_join))
    application.add_handler(CommandHandler("clan_leave", clan_leave))
    application.add_handler(CommandHandler("clan_deposit", clan_deposit))
    application.add_handler(CommandHandler("clan_top", clan_top))
    application.add_handler(CommandHandler("clan_delete", clan_delete))
    # кланы-алиасы
    application.add_handler(CommandHandler("clans_list", clans_list))

    # Заметки
    application.add_handler(CommandHandler("save", save_note))
    application.add_handler(CommandHandler("get", get_note))
    application.add_handler(CommandHandler("notes", list_notes))
    application.add_handler(CommandHandler("del", del_note))

    # Объявления
    application.add_handler(CommandHandler("announcement", announcement))
    application.add_handler(CommandHandler("announce", announcement))
    application.add_handler(CommandHandler("announcements", announcements_list))

    # Админ
    application.add_handler(CommandHandler("adminhelp", admin_help))
    application.add_handler(CommandHandler("admin_help", admin_help))
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("admin_user", admin_user))
    application.add_handler(CommandHandler("admin_setbal", admin_setbal))
    application.add_handler(CommandHandler("admin_addbal", admin_addbal))
    application.add_handler(CommandHandler("admin_takebal", admin_takebal))
    application.add_handler(CommandHandler("admin_setcrystals", admin_setcrystals))
    application.add_handler(CommandHandler("admin_takecrystals", admin_takecrystals))
    application.add_handler(CommandHandler("admin_reset", admin_reset))
    application.add_handler(CommandHandler("admin_ban", admin_ban))
    application.add_handler(CommandHandler("admin_unban", admin_unban))
    application.add_handler(CommandHandler("admin_freeze", admin_freeze))
    application.add_handler(CommandHandler("admin_unfreeze", admin_unfreeze))
    application.add_handler(CommandHandler("admin_unmarry", admin_unmarry))
    application.add_handler(CommandHandler("admin_setname", admin_setname))
    application.add_handler(CommandHandler("admin_giveitem", admin_giveitem))
    application.add_handler(CommandHandler("admin_giveach", admin_giveach))
    application.add_handler(CommandHandler("admin_chats", admin_chats))
    application.add_handler(CommandHandler("admin_broadcast", admin_broadcast))
    application.add_handler(CommandHandler("admin_ping", admin_ping))
    application.add_handler(CommandHandler("admin_version", admin_version))

    # Inline
    application.add_handler(CallbackQueryHandler(duel_callback, pattern=r"^duel_"))
    application.add_handler(CallbackQueryHandler(marry_callback, pattern=r"^marry_"))
    application.add_handler(CallbackQueryHandler(blackjack_callback, pattern=r"^bj_"))

    # Новые участники
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))

    # Текст (обычный роутер)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Свои RP-команды (обработчик команд, которые НЕ зарегистрированы в PTB — динамически)
    # PTB не умеет динамически создавать CommandHandler, поэтому ловим через regex-подобный приём:
    # Мы НЕ можем поймать неизвестные команды как COMMAND. Но можем обработать через MessageHandler с фильтром 'text starts with /'.
    # Поэтому ловим все команды в конце — но это может конфликтовать с PTB.
    # Решение: просто не ловим динамически; пользователь вызывает свои RP через /my_rp (список), а применяет — через /команда, если добавит вручную в config.
    # (Оставим проще: при вызове /<custom> PTB не найдёт хендлер, лог `unknown command`.) 

    async def error_handler(update, context):
        logger.error(f"EXCEPTION: {context.error}", exc_info=context.error)

    application.add_error_handler(error_handler)

    logger.info("🚀 Бот запущен!")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        stop_signals=None,
        drop_pending_updates=True,
        bootstrap_retries=-1,
    )


if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Flask на порту {port}")
    flask_app.run(host="0.0.0.0", port=port)
