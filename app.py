import os
import random
import logging
import json
import asyncio
import threading
import string
import aiohttp
import pytz
import sqlite3
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
    TOKEN, ADMIN_IDS, ADMIN_USERNAMES, START_BALANCE, START_CRYSTALS, START_DONAT,
    CRYSTAL_TO_DONAT, CRYSTAL_TO_COINS, DONAT_TO_COINS,
    VIP_PRICE_DONAT, CROWN_PRICE_DONAT,
    DAILY_REWARD, DAILY_STREAK_BONUS, DAILY_MAX,
    QUIZ_REWARD, GUESS_REWARD, DUEL_REWARD, DICE_REWARD,
    SLOT_COST, SLOT_JACKPOT, SLOT_PAIR,
    WORK_BASE_COOLDOWN, WORK_MIN, WORK_MAX, WORK_XP_PER_JOB, WORK_LEVEL_MULTIPLIER,
    ROB_COOLDOWN, ROB_SUCCESS_CHANCE, ROB_FINE, FISH_COOLDOWN,
    MARRIAGE_LEVELS, MARRIAGE_TASKS, MARRIAGE_XP_PER_TASK,
    ROULETTE_MIN_BET, BLACKJACK_MIN_BET, COINFLIP_MIN_BET,
    FOOTBALL_MIN_BET, BASKET_MIN_BET, BOWLING_MIN_BET,
    SHOP_ITEMS, BUSINESSES, DEPOSIT_RATES,
    GIFTS_COMMON, GIFTS_LIMITED,
    REFERRAL_BONUS, ANNOUNCEMENT_COST, CUSTOM_RP_COST,
    ACHIEVEMENTS, FISH_ITEMS, WORK_JOBS,
    RP_ACTIONS, RU_COMMANDS,
    BALL_ANSWERS, QUOTES, IDEAS,
    REQUIRED_CHANNELS
)
import database as db

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

flask_app = Flask(__name__)


@flask_app.route('/')
def index():
    return "<html><body style='background:#1a1a2e;color:#eee;text-align:center;padding:50px;font-family:sans-serif'><h1>🤖 Бот</h1><p style='color:#4ade80'>✅ Online</p></body></html>", 200


@flask_app.route('/health')
def health():
    return {"status": "ok"}, 200


# ============ СОСТОЯНИЯ ============
guess_games = {}
duel_games = {}
quiz_games = {}
blackjack_games = {}

QUIZ_QUESTIONS = [
    ("Сколько планет в Солнечной системе?", "8"),
    ("Столица Франции?", "париж"),
    ("Сколько 7 * 8?", "56"),
    ("Какой газ мы вдыхаем?", "кислород"),
    ("Самое большое животное?", "синий кит"),
    ("Сколько цветов в радуге?", "7"),
    ("Кто написал «Война и мир»?", "толстой"),
    ("Формула воды?", "h2o"),
    ("Столица Японии?", "токио"),
    ("Сколько 12 * 12?", "144"),
]

LINE = "━━━━━━━━━━━━━━━━━━━━━━━"


# ============ УТИЛИТЫ ============
def frame(title, emoji="✨"):
    return f"╭──────────────────────╮\n   {emoji} {title} {emoji}\n╰──────────────────────╯"


def divider():
    return "━━━━━━━━━━━━━━━━━━━━━━━━━━"


def display_name(data):
    return data.get("nickname") or data.get("first_name") or f"ID {data['user_id']}"


def user_mention_from_data(data):
    name = display_name(data)
    return f"[{name}](tg://user?id={data['user_id']})"


def user_mention(user):
    return f"[{user.first_name}](tg://user?id={user.id})"


def crown_prefix(data):
    if data.get("has_crown") or data.get("is_vip"):
        return "👑 "
    return ""


async def fetch_gif(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["results"][0]["url"]
    except Exception:
        pass
    return None


def is_bot_admin(user_id, username=None):
    if user_id in ADMIN_IDS:
        return True
    if username and username.lower() in [u.lower() for u in ADMIN_USERNAMES]:
        return True
    return False


async def is_chat_admin(update, context):
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def resolve_target(update, context):
    """reply OR @username. Возвращает (user_or_None, data_or_None, display_str)."""
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        data = db.get_user(u.id, u.username, u.first_name)
        return u, data, user_mention_from_data(data)
    args = context.args or []
    if not args:
        return None, None, None
    raw = args[0]
    if not raw.startswith("@"):
        return None, None, None
    username = raw.lstrip("@")
    if update.effective_chat.type != "private":
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, username)
            data = db.get_user(m.user.id, m.user.username, m.user.first_name)
            return m.user, data, user_mention_from_data(data)
        except Exception:
            pass
    with db.lock, sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (username,))
        row = cur.fetchone()
        if row:
            data = db._row(row)
            return None, data, user_mention_from_data(data)
    return None, None, f"@{username}"


def check_quest(user_id, key, inc=1):
    from config import QUESTS
    if key not in QUESTS:
        return
    user = db.get_user(user_id)
    progress = json.loads(user["quest_progress"] or '{}')
    progress[key] = progress.get(key, 0) + inc
    db.update_user(user_id, quest_progress=json.dumps(progress))
    _, target, reward = QUESTS[key]
    if progress[key] == target:
        db.add_balance(user_id, reward)


async def grant_achievement(update, uid, ach_id):
    if ach_id in ACHIEVEMENTS:
        name, desc = ACHIEVEMENTS[ach_id]
    else:
        row = db.get_custom_achievement(ach_id)
        if not row:
            return
        name, desc = row[2], row[3]
    if db.add_achievement(uid, ach_id):
        try:
            await update.message.reply_text(f"🏆 Новая ачивка!\n{name}\n{desc}")
        except Exception:
            pass


async def check_required_sub(update, context):
    if not REQUIRED_CHANNELS:
        return True
    uid = update.effective_user.id
    not_subbed = []
    for ch in REQUIRED_CHANNELS:
        try:
            m = await context.bot.get_chat_member(ch["id"], uid)
            if m.status in ("left", "kicked"):
                not_subbed.append(ch)
        except Exception:
            not_subbed.append(ch)
    if not_subbed:
        text = "📢 Подпишись на каналы:\n" + "\n".join(f"• [{c['title']}]({c['url']})" for c in not_subbed)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        return False
    return True


# ============ СТАРТ / СПРАВКИ ============
async def start(update, context):
    u = update.effective_user
    db.get_user(u.id, u.username, u.first_name)
    if context.args and context.args[0].startswith("ref_"):
        try:
            rid = int(context.args[0].replace("ref_", ""))
            if rid != u.id and db.add_referral(rid, u.id):
                try:
                    await context.bot.send_message(rid, f"🎉 Новый реферал! +{REFERRAL_BONUS} 💎")
                except Exception:
                    pass
        except (ValueError, IndexError):
            pass
    await grant_achievement(update, u.id, "first_steps")
    await update.message.reply_text(
        f"🌟 Привет, {u.first_name}! 🌟\n{divider()}\n"
        "🎮 игры 💰 экономика 💞 RP 💍 брак 👑 кланы 💠 донат\n\n"
        "📖 /help — все команды\n"
        "💞 /rp — RP\n"
        "🎁 /referral — кристаллы\n"
        "💠 /donate — донат\n\n"
        "💡 Можно писать БЕЗ слэша: `рыбалка`, `работа`, `брак @юзер`"
    )


async def help_command(update, context):
    await update.message.reply_text(
        f"📖 СПРАВКА\n{divider()}\n"
        "🎮 /games 💰 /economy 🎰 /casino\n"
        "💞 /rp 💍 /lovehelp 👑 /clans\n"
        "🛡 /modhelp 🔧 /utils 📌 /noteshelp\n"
        "🏆 /achievements\n\n"
        "🕐 /msk /time 💱 /currency /crypto\n"
        "💠 /donate /top_donat\n"
        "🎁 /referral\n\n"
        "🇷🇺 Русские команды без слэша:\n"
        "рыбалка, работа, баланс, топ, профиль,\n"
        "монетка, кубик, брак @юзер, шип, время"
    )


async def games_help(update, context):
    await update.message.reply_text(
        f"🎮 ИГРЫ\n{divider()}\n"
        "/roll /coin /dice\n"
        "/basketball /football /bowling /darts\n"
        "/slot /guess /stopguess /duel\n"
        "/quiz /trivia /8ball /random"
    )


async def economy_help(update, context):
    await update.message.reply_text(
        f"💰 ЭКОНОМИКА\n{divider()}\n"
        "/balance /daily /work /fish /rob\n"
        "/top /pay /shop /buy /inventory\n"
        "/quests /referral\n"
        "/бизнес /вклад"
    )


async def casino_help(update, context):
    await update.message.reply_text(
        f"🎰 КАЗИНО\n{divider()}\n"
        "/slot\n"
        "/bet_flip орёл|решка сумма\n"
        "/roulette цвет|число сумма\n"
        "/blackjack сумма\n"
        "/bet_dice сумма\n"
        "/football_bet сумма\n"
        "/basket_bet сумма\n"
        "/bowling_bet сумма"
    )


async def rp_help(update, context):
    lines = [f"💞 RP\n{divider()}"]
    for k, d in RP_ACTIONS.items():
        emoji, act, _, aliases = d
        lines.append(f"{emoji} /{k} | {', '.join(aliases[:2])}")
    lines.append("\n💡 Просто напиши: обнять @юзер")
    await update.message.reply_text("\n".join(lines))


async def love_help(update, context):
    await update.message.reply_text(
        f"💍 ОТНОШЕНИЯ\n{divider()}\n"
        "/marry @юзер или /брак @юзер\n"
        "/accept /decline /divorce\n"
        "/couple /love /ship\n"
        "/marriage_gift сумма"
    )


async def mod_help(update, context):
    await update.message.reply_text(
        f"🛡 МОДЕРАЦИЯ\n{divider()}\n"
        "/mute /unmute /kick /ban /unban\n"
        "/warn /unwarn /warns /purge\n"
        "/rules /setrules"
    )


async def utils_help(update, context):
    await update.message.reply_text(
        f"🔧 УТИЛИТЫ\n{divider()}\n"
        "/weather /tr /remind /timer\n"
        "/id /ping /password /qr /color\n"
        "/currency /crypto /msk /time\n"
        "/ник Имя /био текст"
    )


async def fun_help(update, context):
    await update.message.reply_text(
        f"🎲 РАЗВЛЕЧЕНИЯ\n{divider()}\n"
        "/8ball /love /ship /quote\n"
        "/avatar /joke /fact /idea\n"
        "/choice /predict"
    )


async def notes_help(update, context):
    await update.message.reply_text("/save имя текст\n/get имя\n/notes\n/del имя")


async def clans_help(update, context):
    await update.message.reply_text(
        f"👑 КЛАНЫ\n{divider()}\n"
        "/create_clan Имя\n/clans\n/clan_info Имя\n"
        "/clan_join Имя\n/clan_leave\n"
        "/clan_deposit сумма\n/clan_top\n/clan_delete"
    )


async def about(update, context):
    await update.message.reply_text(f"ℹ️ v8.0\n💞 RP: {len(RP_ACTIONS)}\n🏆 Ачивок: {len(ACHIEVEMENTS)}")


async def ping(update, context):
    t0 = datetime.now()
    msg = await update.message.reply_text("🏓")
    dt = (datetime.now() - t0).total_seconds() * 1000
    await msg.edit_text(f"🏓 {dt:.0f}ms")


async def id_command(update, context):
    u = update.effective_user
    c = update.effective_chat
    t = f"🆔 {u.id}\n💬 {c.id}\n📛 {c.type}"
    if update.message.reply_to_message:
        t += f"\n👤 {update.message.reply_to_message.from_user.id}"
    await update.message.reply_text(t)


# ============ RP ============
async def send_rp(update, context, action_key):
    emoji, action, api_url, _ = RP_ACTIONS[action_key]
    actor = update.effective_user
    adata = db.get_user(actor.id, actor.username, actor.first_name)

    target_user, target_data, target_display = await resolve_target(update, context)
    gif = await fetch_gif(api_url)

    actor_name = crown_prefix(adata) + user_mention_from_data(adata)
    if target_display is None:
        caption = f"{emoji} {actor_name} {action}"
    elif target_data and target_data["user_id"] == actor.id:
        caption = f"{emoji} {actor_name} {action} себя 😅"
    else:
        tname = crown_prefix(target_data) + target_display if target_data else target_display
        caption = f"{emoji} {actor_name} {action} {tname}"

    if target_data and adata.get("married_to") == target_data["user_id"]:
        db.add_marriage_xp(actor.id, 5)
        db.add_marriage_xp(target_data["user_id"], 5)

    try:
        if gif:
            await update.message.reply_animation(animation=gif, caption=caption, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        try:
            await update.message.reply_text(caption)
        except Exception:
            await update.message.reply_text(f"{emoji} {actor.first_name} {action}")

    check_quest(actor.id, "rp_10")


def make_rp_handler(key):
    async def h(update, context):
        await send_rp(update, context, key)
    return h


async def ru_rp_handler(update, context):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    words = text.split()
    if not words:
        return
    first = words[0].lower().strip("!,.?")
    for k, d in RP_ACTIONS.items():
        aliases = [a.lower() for a in (d[3] or [])]
        if first in aliases:
            context.args = words[1:]
            await send_rp(update, context, k)
            return


# ============ ВРЕМЯ / ВАЛЮТЫ ============
async def moscow_time(update, context):
    msk = datetime.now(timezone(timedelta(hours=3)))
    await update.message.reply_text(f"🕐 МСК: {msk.strftime('%d.%m.%Y %H:%M:%S')}")


TIMEZONES = {
    "москва": "Europe/Moscow",
    "мск": "Europe/Moscow",
    "киев": "Europe/Kiev",
    "минск": "Europe/Minsk",
    "алматы": "Asia/Almaty",
    "токио": "Asia/Tokyo",
    "лондон": "Europe/London",
    "париж": "Europe/Paris",
    "нью-йорк": "America/New_York",
    "лос-анджелес": "America/Los_Angeles",
    "пекин": "Asia/Shanghai",
    "дубай": "Asia/Dubai",
    "сидней": "Australia/Sydney",
    "берлин": "Europe/Berlin",
    "стамбул": "Europe/Istanbul",
    "дели": "Asia/Kolkata",
}


async def time_cmd(update, context):
    if context.args:
        city = " ".join(context.args).lower()
        tz_name = TIMEZONES.get(city)
        if not tz_name:
            await update.message.reply_text("❓ Не знаю такой город. Попробуй: Москва, Токио, Лондон, Нью-Йорк, Дубай")
            return
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        await update.message.reply_text(f"🕐 {city.title()}: {now.strftime('%d.%m.%Y %H:%M:%S')} ({tz_name})")
        return
    lines = [f"🕐 ВРЕМЯ В ГОРОДАХ\n{divider()}"]
    for city, tz_name in list(TIMEZONES.items())[:10]:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        lines.append(f"• {city.title()}: {now.strftime('%H:%M')}")
    lines.append("\n/time город — подробнее")
    await update.message.reply_text("\n".join(lines))


async def currency(update, context):
    if not context.args:
        await update.message.reply_text(
            "💱 ВАЛЮТЫ\n"
            "/currency 100 USD RUB\n"
            "/currency USD\n"
            "/crypto BTC\n\n"
            "Фиат: RUB, USD, EUR, UAH, BYN, KZT, AED, GBP\n"
            "Крипта: BTC, ETH, TON, SOL, BNB, XRP"
        )
        return
    args = context.args
    if len(args) >= 3 and args[0].replace('.', '').isdigit():
        try:
            amount = float(args[0])
            fc = args[1].upper()
            tc = args[2].upper()
            async with aiohttp.ClientSession() as session:
                url = f"https://open.er-api.com/v6/latest/{fc}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
                    if data.get("result") != "success":
                        await update.message.reply_text("❌ Не нашёл валюту.")
                        return
                    rate = data["rates"].get(tc)
                    if not rate:
                        await update.message.reply_text("❌ Нет целевой валюты.")
                        return
                    await update.message.reply_text(f"💱 {amount:g} {fc} = {amount*rate:.2f} {tc}")
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
        return

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
                        f"💎 {code}\n🇺🇸 ${info['usd']:,.2f}\n🇷🇺 {info['rub']:,.2f} ₽"
                    )
        except Exception:
            await update.message.reply_text("Ошибка.")
        return

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://open.er-api.com/v6/latest/{code}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                if data.get("result") != "success":
                    await update.message.reply_text("❌ Не нашёл валюту.")
                    return
                r = data["rates"]
                await update.message.reply_text(
                    f"💱 КУРС {code}\n"
                    f"🇷🇺 RUB: {r.get('RUB')}\n"
                    f"🇺🇸 USD: {r.get('USD')}\n"
                    f"🇪🇺 EUR: {r.get('EUR')}\n"
                    f"🇺🇦 UAH: {r.get('UAH')}\n"
                    f"🇧🇾 BYN: {r.get('BYN')}\n"
                    f"🇦🇪 AED: {r.get('AED')}"
                )
    except Exception:
        await update.message.reply_text("Ошибка.")


async def crypto(update, context):
    if not context.args:
        await update.message.reply_text("💎 /crypto BTC|ETH|TON|SOL|BNB|XRP")
        return
    context.args = [context.args[0]]
    await currency(update, context)


# ============ РЕФЕРАЛЫ / ДОНАТ ИНФО ============
async def referral(update, context):
    u = update.effective_user
    data = db.get_user(u.id, u.username, u.first_name)
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{u.id}"
    await update.message.reply_text(
        f"🎁 КРИСТАЛЛЫ\n{divider()}\n"
        f"🔗 `{link}`\n\n"
        f"👥 {data['referral_count'] or 0}\n"
        f"💎 {data['crystals']:.1f}\n\n"
        f"+{REFERRAL_BONUS} 💎 за нового"
    )


async def donate_info(update, context):
    await update.message.reply_text(
        f"💠 ДОНАТ-ВАЛЮТА\n{divider()}\n"
        f"VIP-статус: {VIP_PRICE_DONAT} 💠\n"
        f"Корона: {CROWN_PRICE_DONAT} 💠\n\n"
        "💳 Для покупки обратитесь к админам:\n"
        "• @kvails\n"
        "• @notuwife\n\n"
        "📊 /top_donat — топ донатеров"
    )


# ============ ТОПЫ ============
def _name_from_row(username, nickname, first_name, uid):
    return nickname or (f"@{username}" if username else (first_name or f"ID {uid}"))


async def top(update, context):
    users = db.top_users(10)
    if not users:
        await update.message.reply_text("Пусто.")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"🏆 ТОП-10 МОНЕТ\n{divider()}"]
    for i, (uid, un, nk, fn, bal) in enumerate(users):
        lines.append(f"{medals[i]} {_name_from_row(un, nk, fn, uid)} — {bal} 💰")
    await update.message.reply_text("\n".join(lines))


async def top_ref(update, context):
    users = db.top_crystals(3)
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"💎 ТОП-3 КРИСТАЛЛЫ\n{divider()}"]
    for i, (uid, un, nk, fn, c) in enumerate(users):
        lines.append(f"{medals[i]} {_name_from_row(un, nk, fn, uid)} — {(c or 0):.1f} 💎")
    await update.message.reply_text("\n".join(lines))


async def top_donat(update, context):
    users = db.top_donat(10)
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"💠 ТОП ДОНАТОВ\n{divider()}"]
    for i, (uid, un, nk, fn, d) in enumerate(users):
        lines.append(f"{medals[i]} {_name_from_row(un, nk, fn, uid)} — {d or 0} 💠")
    await update.message.reply_text("\n".join(lines))


async def top_casino(update, context):
    users = db.top_wins(3)
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🎰 ТОП-3 ПОБЕД\n{divider()}"]
    for i, (uid, un, nk, fn, w) in enumerate(users):
        lines.append(f"{medals[i]} {_name_from_row(un, nk, fn, uid)} — {w or 0} 🏆")
    await update.message.reply_text("\n".join(lines))


async def top_messages_all(update, context):
    users = db.top_messages(None, 10)
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"💬 ТОП-10 СООБЩЕНИЯ (всё время)\n{divider()}"]
    for i, (uid, un, nk, fn, m) in enumerate(users):
        lines.append(f"{medals[i]} {_name_from_row(un, nk, fn, uid)} — {m or 0} 💬")
    await update.message.reply_text("\n".join(lines))


async def top_messages_day(update, context):
    users = db.top_messages(update.effective_chat.id, 10, hours=24)
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"💬 ТОП-10 СООБЩЕНИЯ (сутки)\n{divider()}"]
    for i, (uid, un, nk, fn, m) in enumerate(users):
        lines.append(f"{medals[i]} {_name_from_row(un, nk, fn, uid)} — {m or 0} 💬")
    await update.message.reply_text("\n".join(lines))


async def top_messages_week(update, context):
    users = db.top_messages(update.effective_chat.id, 10, hours=168)
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"💬 ТОП-10 СООБЩЕНИЯ (неделя)\n{divider()}"]
    for i, (uid, un, nk, fn, m) in enumerate(users):
        lines.append(f"{medals[i]} {_name_from_row(un, nk, fn, uid)} — {m or 0} 💬")
    await update.message.reply_text("\n".join(lines))


async def chat_stats(update, context):
    cid = update.effective_chat.id
    users = db.top_messages(cid, 100)
    total = sum(m or 0 for *_, m in users)
    await update.message.reply_text(
        f"📊 СТАТИСТИКА ЧАТА\n{divider()}\n"
        f"💬 Всего: {total}\n👥 Активных: {len(users)}\n🆔 {cid}"
    )


async def all_chats_stats(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        await update.message.reply_text("❌ Только для админов.")
        return
    chats = db.get_all_chats()
    await update.message.reply_text(f"🌐 Чатов: {len(chats)}\n" + "\n".join(str(c) for c in chats[:30]))


# ============ ИГРЫ ============
async def roll(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    msg = await update.message.reply_dice(emoji="🎲")
    result = msg.dice.value
    await update.message.reply_text(f"🎲 {user_mention(update.effective_user)} — {result}", parse_mode=ParseMode.MARKDOWN)
    check_quest(uid, "play_5")


async def coin(update, context):
    msg = await update.message.reply_dice(emoji="🎯")
    r = "🦅 Орёл" if msg.dice.value in (1, 2, 3) else "🪙 Решка"
    await update.message.reply_text(f"🪙 {user_mention(update.effective_user)}: {r}", parse_mode=ParseMode.MARKDOWN)


async def dice_game(update, context):
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    m1 = await update.message.reply_dice(emoji="🎲")
    m2 = await update.message.reply_dice(emoji="🎲")
    p, b = m1.dice.value, m2.dice.value
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
    if p > b:
        db.add_balance(uid, DICE_REWARD)
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
        res = f"🏆 Победа! +{DICE_REWARD}"
    elif p < b:
        res = "🤖 Бот победил"
    else:
        res = "🤝 Ничья"
    await update.message.reply_text(
        f"🎯 {user_mention(update.effective_user)}: {p}\n🤖 Бот: {b}\n{res}",
        parse_mode=ParseMode.MARKDOWN
    )
    check_quest(uid, "play_5")


async def basketball_free(update, context):
    msg = await update.message.reply_dice(emoji="🏀")
    s = msg.dice.value
    txt = "🏀 Точный бросок!" if s >= 4 else ("🏀 Почти!" if s >= 2 else "🏀 Мимо...")
    await update.message.reply_text(f"{user_mention(update.effective_user)} бросает!\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def football_free(update, context):
    msg = await update.message.reply_dice(emoji="⚽")
    s = msg.dice.value
    txt = "⚽ ГООООЛ!" if s == 5 else ("⚽ Гол!" if s == 4 else ("⚽ Вратарь!" if s == 3 else "⚽ Мимо..."))
    await update.message.reply_text(f"{user_mention(update.effective_user)} бьёт!\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def bowling_free(update, context):
    msg = await update.message.reply_dice(emoji="🎳")
    s = msg.dice.value
    txt = "🎳 СТРАЙК!" if s == 6 else f"🎳 Сбито {s} кеглей"
    await update.message.reply_text(f"{user_mention(update.effective_user)} бросает!\n{txt}", parse_mode=ParseMode.MARKDOWN)


async def darts_free(update, context):
    msg = await update.message.reply_dice(emoji="🎯")
    s = msg.dice.value
    txt = "🎯 В яблочко!" if s == 6 else f"🎯 Очки: {s * 10}"
    await update.message.reply_text(f"{user_mention(update.effective_user)} кидает!\n{txt}", parse_mode=ParseMode.MARKDOWN)


# ============ КАЗИНО СО СТАВКАМИ ============
async def football_bet(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("/football_bet сумма (мин 20)")
        return
    amount = int(context.args[0])
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if amount < FOOTBALL_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text(f"❌ Мин {FOOTBALL_MIN_BET} или мало монет.")
        return
    db.add_balance(uid, -amount)
    msg = await update.message.reply_dice(emoji="⚽")
    s = msg.dice.value
    if s >= 4:
        win = amount * (2 if s == 4 else 3)
        db.add_balance(uid, win)
        res = f"🎉 Гол! Выигрыш {win}"
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    elif s == 3:
        db.add_balance(uid, amount)
        res = "🤝 Вратарь поймал. Ставка возвращена"
    else:
        res = f"😢 Мимо. -{amount}"
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
    await update.message.reply_text(f"{res}\n💰 {db.get_balance(uid)}")
    check_quest(uid, "play_5")


async def basket_bet(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("/basket_bet сумма (мин 20)")
        return
    amount = int(context.args[0])
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if amount < BASKET_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text(f"❌ Мин {BASKET_MIN_BET} или мало монет.")
        return
    db.add_balance(uid, -amount)
    msg = await update.message.reply_dice(emoji="🏀")
    s = msg.dice.value
    if s == 5:
        win = amount * 3
        db.add_balance(uid, win)
        res = f"🎉 Идеально! +{win}"
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    elif s == 4:
        win = amount * 2
        db.add_balance(uid, win)
        res = f"🏀 Точный! +{win}"
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    else:
        res = f"😢 Мимо. -{amount}"
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
    await update.message.reply_text(f"{res}\n💰 {db.get_balance(uid)}")


async def bowling_bet(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("/bowling_bet сумма (мин 20)")
        return
    amount = int(context.args[0])
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if amount < BOWLING_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text(f"❌ Мин {BOWLING_MIN_BET} или мало монет.")
        return
    db.add_balance(uid, -amount)
    msg = await update.message.reply_dice(emoji="🎳")
    s = msg.dice.value
    if s == 6:
        win = amount * 3
        db.add_balance(uid, win)
        res = f"🎉 СТРАЙК! +{win}"
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    elif s >= 4:
        win = amount * 2
        db.add_balance(uid, win)
        res = f"🎳 Отлично! +{win}"
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    else:
        res = f"😢 Слабо. -{amount}"
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)
    await update.message.reply_text(f"{res}\n💰 {db.get_balance(uid)}")


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
    await update.message.reply_text(f"🎰 {res}\n💰 {db.get_balance(uid)}")


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
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if amount < COINFLIP_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
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
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if amount < ROULETTE_MIN_BET or db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    red = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    r = random.randint(0, 36)
    color = "зелёное" if r == 0 else ("красное" if r in red else "чёрное")
    db.add_balance(uid, -amount)
    win = 0
    if ch in ("красное", "красный") and color == "красное":
        win = amount * 2
    elif ch in ("чёрное", "черное", "чёрный", "черный") and color == "чёрное":
        win = amount * 2
    elif ch.isdigit() and int(ch) == r:
        win = amount * 36
    if win:
        db.add_balance(uid, win)
        await update.message.reply_text(f"🎡 {r} ({color})\n🎉 +{win}")
        d = db.get_user(uid)
        db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
    else:
        await update.message.reply_text(f"🎡 {r} ({color})\n😢 -{amount}")
    d = db.get_user(uid)
    db.update_user(uid, stats_played=(d["stats_played"] or 0) + 1)


async def blackjack(update, context):
    if not context.args:
        await update.message.reply_text("/blackjack сумма")
        return
    try:
        amount = int(context.args[0])
    except ValueError:
        return
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
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
        f"🃏 Блэкджек ({amount})\n🎴 Ваши: {' '.join(player)} = {p}\n🎴 Дилер: {dealer[0]} ?",
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
            del blackjack_games[uid]
            return
        kb = [[InlineKeyboardButton("🎴 Ещё", callback_data=f"bj_hit:{uid}"),
               InlineKeyboardButton("🛑 Хватит", callback_data=f"bj_stand:{uid}")]]
        await q.edit_message_text(
            f"🃏 Блэкджек ({amount})\n🎴 Ваши: {' '.join(g['player'])} = {p}\n🎴 Дилер: {g['dealer'][0]} ?",
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
            win = amount * 2
            db.add_balance(uid, win)
            msg = f"🏆 +{win}"
            d = db.get_user(uid)
            db.update_user(uid, stats_won=(d["stats_won"] or 0) + 1)
        elif p == dv:
            db.add_balance(uid, amount)
            msg = "🤝 Ничья."
        else:
            msg = f"😢 -{amount}"
        await q.edit_message_text(f"🎴 Ваши: {' '.join(g['player'])} = {p}\n🎴 Дилер: {' '.join(g['dealer'])} = {dv}\n{msg}")
        del blackjack_games[uid]


async def bet_dice(update, context):
    if not context.args or not context.args[0].isdigit():
        return
    amount = int(context.args[0])
    uid = update.effective_user.id
    db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
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


# ============ УГАДАЙ / ВИКТОРИНА ============
async def guess(update, context):
    cid = update.effective_chat.id
    if cid in guess_games:
        await update.message.reply_text("❌ Уже идёт. /stopguess")
        return
    guess_games[cid] = {'number': random.randint(1, 100), 'attempts': 0}
    await update.message.reply_text(f"🔢 Угадай число 1–100! +{GUESS_REWARD}")


async def stop_guess(update, context):
    cid = update.effective_chat.id
    if cid in guess_games:
        n = guess_games[cid]['number']
        del guess_games[cid]
        await update.message.reply_text(f"🛑 Было: {n}")


async def handle_guess(update, context):
    cid = update.effective_chat.id
    if cid not in guess_games:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        return
    n = int(text)
    g = guess_games[cid]
    g['attempts'] += 1
    if n < g['number']:
        await update.message.reply_text(f"📈 Больше! ({g['attempts']})")
    elif n > g['number']:
        await update.message.reply_text(f"📉 Меньше! ({g['attempts']})")
    else:
        uid = update.effective_user.id
        db.add_balance(uid, GUESS_REWARD)
        await update.message.reply_text(f"🎉 {user_mention(update.effective_user)}! {g['number']}\n+{GUESS_REWARD}", parse_mode=ParseMode.MARKDOWN)
        del guess_games[cid]


async def duel(update, context):
    cid = update.effective_chat.id
    tuser, tdata, tdisp = await resolve_target(update, context)
    if not tuser:
        await update.message.reply_text("/duel @юзер")
        return
    if tuser.id == update.effective_user.id:
        await update.message.reply_text("Нельзя себя!")
        return
    ch = update.effective_user
    duel_games[cid] = {
        'challenger': ch.id, 'opponent': tuser.id,
        'choice1': None, 'choice2': None,
        'names': {ch.id: ch.first_name, tuser.id: display_name(tdata)}
    }
    kb = [[
        InlineKeyboardButton("✊", callback_data="duel_rock"),
        InlineKeyboardButton("✌️", callback_data="duel_scissors"),
        InlineKeyboardButton("✋", callback_data="duel_paper"),
    ]]
    await update.message.reply_text(
        f"⚔️ {user_mention(ch)} vs {tdisp}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def duel_callback(update, context):
    q = update.callback_query
    await q.answer()
    cid = q.message.chat.id
    uid = q.from_user.id
    if cid not in duel_games:
        await q.edit_message_text("Дуэль завершена.")
        return
    g = duel_games[cid]
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
            check_quest(wid, "duel_5")
        else:
            wid = g['opponent']
            db.add_balance(wid, DUEL_REWARD)
            res = f"🏆 {g['names'][wid]}! +{DUEL_REWARD}"
            check_quest(wid, "duel_5")
        await q.edit_message_text(f"⚔️ Дуэль!\n{g['names'][g['challenger']]}: {c1}\n{g['names'][g['opponent']]}: {c2}\n{res}")
        del duel_games[cid]
    else:
        await q.answer("Ждём соперника.")


async def quiz(update, context):
    cid = update.effective_chat.id
    q, a = random.choice(QUIZ_QUESTIONS)
    quiz_games[cid] = {'answer': a.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(f"❓ {q}\n+{QUIZ_REWARD}")


async def trivia(update, context):
    qs = [("Самый быстрый зверь?", "гепард"), ("Сколько ног у паука?", "8"),
          ("Самый большой океан?", "тихий"), ("Автор Гарри Поттера?", "роулинг")]
    cid = update.effective_chat.id
    q, a = random.choice(qs)
    quiz_games[cid] = {'answer': a.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(f"🧠 {q}")


async def handle_quiz(update, context):
    cid = update.effective_chat.id
    if cid not in quiz_games:
        return
    if update.message.text.strip().lower() == quiz_games[cid]['answer']:
        r = quiz_games[cid]['reward']
        uid = update.effective_user.id
        db.add_balance(uid, r)
        del quiz_games[cid]
        await update.message.reply_text(f"✅ Верно! +{r}")


async def ball8(update, context):
    if not context.args:
        await update.message.reply_text("🎱 /8ball вопрос")
        return
    await update.message.reply_text(f"🎱 {random.choice(BALL_ANSWERS)}")


async def random_number(update, context):
    try:
        if len(context.args) >= 2:
            a, b = int(context.args[0]), int(context.args[1])
            if a > b: a, b = b, a
        else:
            a, b = 1, 100
    except ValueError:
        a, b = 1, 100
    await update.message.reply_text(f"🎲 {a}–{b}: {random.randint(a, b)}")


# ============ ЭКОНОМИКА ============
async def balance(update, context):
    t = update.effective_user
    if update.message.reply_to_message:
        t = update.message.reply_to_message.from_user
    data = db.get_user(t.id, t.username, t.first_name)
    await update.message.reply_text(
        f"💰 {user_mention_from_data(data)}\n"
        f"Монет: {data['balance']}\n"
        f"💎 Кристаллы: {(data['crystals'] or 0):.1f}\n"
        f"💠 Донат: {data['donat'] or 0}",
        parse_mode=ParseMode.MARKDOWN
    )


async def daily(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    last = data["last_daily"]
    now = datetime.now()
    if last:
        ld = datetime.fromisoformat(last)
        if now - ld < timedelta(hours=24):
            r = timedelta(hours=24) - (now - ld)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ Через {h}ч {m}м.")
            return
    streak = (data["daily_streak"] or 0) + 1 if last and (now - datetime.fromisoformat(last)) < timedelta(hours=48) else 1
    reward = min(DAILY_REWARD + (streak - 1) * DAILY_STREAK_BONUS, DAILY_MAX)
    db.add_balance(uid, reward)
    db.update_user(uid, last_daily=now.isoformat(), daily_streak=streak)
    if streak >= 7: await grant_achievement(update, uid, "daily_7")
    if streak >= 30: await grant_achievement(update, uid, "daily_30")
    await update.message.reply_text(f"🎁 +{reward}\n🔥 Стрик: {streak}\n💰 {db.get_balance(uid)}")
    check_quest(uid, "daily_3")


async def work(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    last = data["last_work"]
    now = datetime.now()
    cd = WORK_BASE_COOLDOWN + (data["work_level"] or 1) * 60
    if last:
        ld = datetime.fromisoformat(last)
        if now - ld < timedelta(seconds=cd):
            r = timedelta(seconds=cd) - (now - ld)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ Отдохни {h}ч {m}м.")
            return
    job = random.choice(WORK_JOBS)
    base = random.randint(WORK_MIN, WORK_MAX)
    mult = WORK_LEVEL_MULTIPLIER ** ((data["work_level"] or 1) - 1)
    earned = int(base * mult)
    inv = (data["inventory"] or "").split(",")
    if "pickaxe" in inv:
        earned = int(earned * 1.3)
    db.add_balance(uid, earned)
    new_xp = (data["work_xp"] or 0) + WORK_XP_PER_JOB
    new_lvl = data["work_level"] or 1
    while new_xp >= new_lvl * 50:
        new_xp -= new_lvl * 50
        new_lvl += 1
    db.update_user(uid, last_work=now.isoformat(), work_xp=new_xp, work_level=new_lvl)
    await update.message.reply_text(
        f"💼 {job}\n💵 +{earned}\n📈 Уровень работы: {new_lvl} (×{WORK_LEVEL_MULTIPLIER ** (new_lvl - 1):.2f})"
    )
    check_quest(uid, "work_5")


async def fish(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    last = data["last_fish"]
    now = datetime.now()
    if last:
        ld = datetime.fromisoformat(last)
        if now - ld < timedelta(seconds=FISH_COOLDOWN):
            m = (timedelta(seconds=FISH_COOLDOWN) - (now - ld)).seconds // 60
            await update.message.reply_text(f"⏳ Через {m} мин.")
            return
    inv = (data["inventory"] or "").split(",")
    bonus = 1.3 if "fishing_rod" in inv else 1.0
    roll = random.random()
    cum = 0
    caught = None
    for name, price, chance in FISH_ITEMS:
        cum += chance * bonus
        if roll <= cum:
            caught = (name, price)
            break
    if caught:
        name, price = caught
        if price > 0:
            db.add_balance(uid, price)
            await update.message.reply_text(f"🎣 {name}\n💵 +{price}")
        else:
            await update.message.reply_text(f"🎣 {name}\n😅 Ничего не заработал")
    else:
        await update.message.reply_text("🎣 Ничего...")
    db.update_user(uid, last_fish=now.isoformat())
    check_quest(uid, "fish_10")


async def rob(update, context):
    tuser, tdata, tdisp = await resolve_target(update, context)
    if not tuser and not tdata:
        await update.message.reply_text("Укажи @юзер или ответь.")
        return
    uid = update.effective_user.id
    if tdata and tdata["user_id"] == uid:
        await update.message.reply_text("Себя нельзя!")
        return
    me = db.get_user(uid)
    last = me["last_rob"]
    now = datetime.now()
    if last:
        ld = datetime.fromisoformat(last)
        if now - ld < timedelta(seconds=ROB_COOLDOWN):
            r = timedelta(seconds=ROB_COOLDOWN) - (now - ld)
            h, m = r.seconds // 3600, (r.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ {h}ч {m}м.")
            return
    if not tdata:
        await update.message.reply_text("Не нашёл цель.")
        return
    tb = tdata["balance"]
    if tb < 50:
        await update.message.reply_text("Мало монет.")
        return
    if random.random() < ROB_SUCCESS_CHANCE:
        amount = random.randint(10, min(200, tb // 2))
        db.add_balance(uid, amount)
        db.add_balance(tdata["user_id"], -amount)
        await update.message.reply_text(f"🥷 +{amount} у {tdisp}", parse_mode=ParseMode.MARKDOWN)
    else:
        fine = min(ROB_FINE, db.get_balance(uid))
        db.add_balance(uid, -fine)
        await update.message.reply_text(f"🚨 Штраф {fine}.")
    db.update_user(uid, last_rob=now.isoformat())


async def pay(update, context):
    tuser, tdata, tdisp = await resolve_target(update, context)
    if not tdata:
        await update.message.reply_text("❌ /pay @юзер 100 или ответом")
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx or not context.args[idx].isdigit():
        await update.message.reply_text("❌ Укажи сумму.")
        return
    amount = int(context.args[idx])
    uid = update.effective_user.id
    if tdata["user_id"] == uid:
        await update.message.reply_text("Себе нельзя.")
        return
    if amount <= 0:
        return
    if db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало.")
        return
    db.add_balance(uid, -amount)
    db.add_balance(tdata["user_id"], amount)
    await update.message.reply_text(
        f"💸 {user_mention(update.effective_user)} → {tdisp}: {amount}",
        parse_mode=ParseMode.MARKDOWN
    )


async def shop(update, context):
    lines = [f"🛒 МАГАЗИН\n{divider()}"]
    for iid, (name, price, desc) in SHOP_ITEMS.items():
        lines.append(f"{name}\n   {price} 💰 | {desc}\n   ID: {iid}")
    lines.append("\nКупить: /buy ID")
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
    data = db.get_user(uid)
    if data["balance"] < price:
        await update.message.reply_text(f"❌ Нужно {price}")
        return
    db.add_balance(uid, -price)
    inv = [i for i in (data["inventory"] or "").split(",") if i]
    inv.append(iid)
    db.update_user(uid, inventory=",".join(inv))
    await update.message.reply_text(f"✅ {name}\n💰 {db.get_balance(uid)}")
    check_quest(uid, "shop_3")


async def inventory(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    data = db.get_user(u.id, u.username, u.first_name)
    inv = [i for i in (data["inventory"] or "").split(",") if i]
    gifts = [g for g in (data["gifts"] or "").split(",") if g]
    lines = [f"🎒 {display_name(data)}"]
    for iid in inv:
        if iid in SHOP_ITEMS:
            lines.append(f"• {SHOP_ITEMS[iid][0]}")
    if gifts:
        lines.append("\n🎁 Подарки:")
        for gk in gifts:
            if gk in GIFTS_COMMON:
                lines.append(f"• {GIFTS_COMMON[gk][0]}")
            elif gk in GIFTS_LIMITED:
                lines.append(f"• {GIFTS_LIMITED[gk][0]} (лимит)")
    await update.message.reply_text("\n".join(lines) if len(lines) > 1 else "Пусто.")


async def quests(update, context):
    from config import QUESTS
    uid = update.effective_user.id
    data = db.get_user(uid)
    progress = json.loads(data["quest_progress"] or '{}')
    lines = [f"📜 КВЕСТЫ\n{divider()}"]
    for qid, (desc, target, reward) in QUESTS.items():
        cur = progress.get(qid, 0)
        st = "✅" if cur >= target else "⏳"
        lines.append(f"{st} {desc} {cur}/{target} +{reward}")
    await update.message.reply_text("\n".join(lines))


async def achievements_cmd(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    data = db.get_user(u.id, u.username, u.first_name)
    got = [g for g in (data["achievements"] or "").split(",") if g]
    lines = [f"🏆 АЧИВКИ {display_name(data)} ({len(got)})\n{divider()}"]
    for aid, (name, desc) in ACHIEVEMENTS.items():
        mark = "✅" if aid in got else "🔒"
        lines.append(f"{mark} {name}")
    lines.append("\n💡 /pin_ach ID — закрепить в профиле")
    await update.message.reply_text("\n".join(lines))


async def pin_ach(update, context):
    if not context.args:
        await update.message.reply_text("/pin_ach ID_ачивки")
        return
    aid = context.args[0]
    uid = update.effective_user.id
    data = db.get_user(uid)
    got = (data["achievements"] or "").split(",")
    if aid not in got:
        await update.message.reply_text("❌ У тебя нет такой ачивки.")
        return
    db.update_user(uid, pinned_achievement=aid)
    await update.message.reply_text("✅ Закреплено в профиле.")


async def rep(update, context):
    tuser, tdata, tdisp = await resolve_target(update, context)
    if not tdata:
        await update.message.reply_text("Укажи @юзер.")
        return
    if tdata["user_id"] == update.effective_user.id:
        return
    nr = (tdata["reputation"] or 0) + 1
    db.update_user(tdata["user_id"], reputation=nr)
    await update.message.reply_text(f"⭐ {tdisp} — репа: {nr}", parse_mode=ParseMode.MARKDOWN)


# ============ ПРОФИЛЬ ============
async def profile(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    data = db.get_user(u.id, u.username, u.first_name)
    partner = "нет"
    if data["married_to"]:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, data["married_to"])
            pdata = db.get_user(m.user.id)
            partner = display_name(pdata)
        except Exception:
            partner = f"ID {data['married_to']}"
    clan = "нет"
    if data["clan_id"]:
        c = db.get_clan(data["clan_id"])
        if c: clan = c[1]
    title = f" [{data['title']}]" if data["title"] else ""
    bio = data["bio"] or "—"
    reg = data["registered"][:10] if data["registered"] else "—"
    got = [a for a in (data["achievements"] or "").split(",") if a]
    pin_ach_name = ""
    if data["pinned_achievement"]:
        if data["pinned_achievement"] in ACHIEVEMENTS:
            pin_ach_name = ACHIEVEMENTS[data["pinned_achievement"]][0]
    gifts = [g for g in (data["gifts"] or "").split(",") if g]
    crown = "👑 " if data["has_crown"] or data["is_vip"] else ""
    vip = "⭐ VIP" if data["is_vip"] else ""
    lines = [
        f"{crown}{display_name(data)}{title}",
        divider(),
        f"📛 @{data['username'] or '—'}",
        f"🆔 {u.id}",
        f"📅 Зашёл: {reg}",
        f"💬 Сообщений: {data['messages'] or 0}",
        f"⭐ Репутация: {data['reputation'] or 0}",
        divider(),
        f"💰 Монет: {data['balance']}",
        f"💎 Кристаллы: {(data['crystals'] or 0):.1f}",
        f"💠 Донат: {data['donat'] or 0}",
        f"⚠️ Варнов: {data['warns']}",
        f"💞 Партнёр: {partner}",
        f"💍 Уровень брака: {data['marriage_level'] or 1} ({MARRIAGE_LEVELS.get(data['marriage_level'] or 1, '')})",
        f"👑 Клан: {clan}",
        f"📝 Био: {bio}",
        f"💼 Работа: {data['work_level'] or 1} lvl",
        f"🎖 Ачивок: {len(got)}",
    ]
    if pin_ach_name:
        lines.append(f"🏆 Закреплено: {pin_ach_name}")
    if gifts:
        lines.append(f"🎁 Подарков: {len(gifts)}")
    if vip:
        lines.append(vip)
    await update.message.reply_text("\n".join(lines))


async def stats_cmd(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    data = db.get_user(u.id, u.username, u.first_name)
    played, won = data["stats_played"] or 0, data["stats_won"] or 0
    pct = (won / played * 100) if played else 0
    await update.message.reply_text(
        f"📊 {display_name(data)}\n"
        f"🎮 {played}\n🏆 {won} ({pct:.1f}%)\n"
        f"💰 {data['balance']}\n💎 {(data['crystals'] or 0):.1f}\n"
        f"💬 {data['messages'] or 0}"
    )


async def nick_cmd(update, context):
    if not context.args:
        await update.message.reply_text("/ник Имя")
        return
    new_nick = " ".join(context.args)[:30]
    db.get_user(update.effective_user.id)
    db.update_user(update.effective_user.id, nickname=new_nick)
    await update.message.reply_text(f"✅ Ник: {new_nick}")


async def bio(update, context):
    if not context.args:
        await update.message.reply_text("/био текст")
        return
    db.get_user(update.effective_user.id)
    db.update_user(update.effective_user.id, bio=" ".join(context.args)[:200])
    await update.message.reply_text("✅ Био сохранено.")


async def title_cmd(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid)
    inv = (data["inventory"] or "").split(",")
    if "vip" not in inv and "custom_title" not in inv:
        await update.message.reply_text("❌ Нужен VIP или приписка.")
        return
    if not context.args:
        return
    db.update_user(uid, title=" ".join(context.args)[:30])
    await update.message.reply_text("✅")


# ============ БРАК ============
async def marry(update, context):
    actor = update.effective_user
    adata = db.get_user(actor.id, actor.username, actor.first_name)
    if adata["married_to"]:
        await update.message.reply_text("💔 Уже в браке. /divorce")
        return
    tuser, tdata, tdisp = await resolve_target(update, context)
    if not tdata:
        await update.message.reply_text("Укажи @юзер или ответь на сообщение.")
        return
    if tdata["user_id"] == actor.id:
        await update.message.reply_text("😅 Нельзя на себе.")
        return
    if tdata["married_to"]:
        await update.message.reply_text("Уже в браке.")
        return
    db.create_marriage_proposal(actor.id, tdata["user_id"])
    kb = [[
        InlineKeyboardButton("✅ Принять", callback_data=f"marry_yes:{actor.id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"marry_no:{actor.id}"),
    ]]
    await update.message.reply_text(
        f"💍 Предложение!\n{user_mention(actor)} → {tdisp}",
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
        await q.answer("Нельзя!", show_alert=True)
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
        await q.edit_message_text(f"💍💞 Свадьба!\n{user_mention_from_data(td)} 🎉", parse_mode=ParseMode.MARKDOWN)
        db.add_achievement(pid, "married")
        db.add_achievement(target.id, "married")
    else:
        db.delete_marriage_proposal(pid, target.id)
        await q.edit_message_text("💔 Отказ...")


async def divorce(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid)
    if not data["married_to"]:
        await update.message.reply_text("Не в браке.")
        return
    pid = data["married_to"]
    db.update_user(uid, married_to=None, marriage_level=1, marriage_xp=0)
    db.update_user(pid, married_to=None, marriage_level=1, marriage_xp=0)
    await update.message.reply_text("💔 Брак расторгнут.")


async def couple(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid)
    if not data["married_to"]:
        await update.message.reply_text("Не в браке. /marry")
        return
    pdata = db.get_user(data["married_to"])
    if not pdata:
        await update.message.reply_text("Партнёр не найден.")
        return
    await update.message.reply_text(
        f"💞 {user_mention_from_data(data)} + {user_mention_from_data(pdata)}\n"
        f"💍 Уровень: {data['marriage_level']} ({MARRIAGE_LEVELS.get(data['marriage_level'], '')})\n"
        f"💫 XP: {data['marriage_xp'] or 0}/{100 * (data['marriage_level'] or 1)}",
        parse_mode=ParseMode.MARKDOWN
    )


async def marriage_gift(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid)
    if not data["married_to"]:
        await update.message.reply_text("Не в браке.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("/marriage_gift сумма")
        return
    amount = int(context.args[0])
    if amount <= 0 or data["balance"] < amount:
        await update.message.reply_text("❌ Недостаточно монет.")
        return
    xp = amount // 50
    db.add_balance(uid, -amount)
    new_lvl = db.add_marriage_xp(uid, xp)
    db.add_marriage_xp(data["married_to"], xp)
    await update.message.reply_text(f"🎁 Подарок!\n💍 Уровень: {new_lvl}\n+{xp} XP")
    if new_lvl >= 5:
        await grant_achievement(update, uid, "love_lvl5")


async def love_calc(update, context):
    tuser, tdata, tdisp = await resolve_target(update, context)
    if not tdata:
        await update.message.reply_text("Укажи @юзер.")
        return
    actor = update.effective_user
    pair = tuple(sorted([actor.id, tdata["user_id"]]))
    random.seed(pair)
    pct = random.randint(1, 100)
    random.seed()
    if pct >= 90: v = "💖 Идеальная пара!"
    elif pct >= 70: v = "💕 Отличная!"
    elif pct >= 50: v = "💛 Неплохо"
    elif pct >= 30: v = "💔 Сложно"
    else: v = "🖤 Не судьба"
    await update.message.reply_text(
        f"💕 Совместимость\n{user_mention(actor)} + {tdisp}\n{pct}% — {v}",
        parse_mode=ParseMode.MARKDOWN
    )


async def ship(update, context):
    if update.message.reply_to_message:
        a = update.effective_user
        b = update.message.reply_to_message.from_user
    else:
        users = db.top_messages(update.effective_chat.id, 20)
        if len(users) < 2:
            await update.message.reply_text("Мало участников.")
            return
        pair = random.sample(users, 2)
        a_id, a_un, a_nk, a_fn = pair[0][0], pair[0][1], pair[0][2], pair[0][3]
        b_id, b_un, b_nk, b_fn = pair[1][0], pair[1][1], pair[1][2], pair[1][3]
        class U:
            def __init__(self, i, n):
                self.id = i
                self.first_name = n
        a = U(a_id, a_nk or a_fn or f"ID {a_id}")
        b = U(b_id, b_nk or b_fn or f"ID {b_id}")
    pair = tuple(sorted([a.id, b.id]))
    random.seed(pair)
    pct = random.randint(1, 100)
    random.seed()
    name = a.first_name[:len(a.first_name)//2] + b.first_name[len(b.first_name)//2:]
    await update.message.reply_text(
        f"🚢 Шип!\n💑 {user_mention(a)} + {user_mention(b)}\n💕 {name}\n📊 {pct}%",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ БИЗНЕС / ВКЛАД ============
async def biz(update, context):
    if not context.args:
        lines = [f"🏢 БИЗНЕСЫ\n{divider()}"]
        for k, (name, price, income, cd) in BUSINESSES.items():
            lines.append(f"{name} — {price} 💰\n   Доход: {income} каждые {cd//3600}ч | ID: {k}")
        lines.append("\nКупить: /бизнес_купить ID\nСобрать: /бизнес_собрать")
        await update.message.reply_text("\n".join(lines))
        return
    sub = context.args[0].lower()
    if sub == "купить" and len(context.args) >= 2:
        bk = context.args[1].lower()
        if bk not in BUSINESSES:
            await update.message.reply_text("Нет такого бизнеса.")
            return
        name, price, income, cd = BUSINESSES[bk]
        uid = update.effective_user.id
        if db.get_balance(uid) < price:
            await update.message.reply_text(f"❌ Нужно {price}")
            return
        db.add_balance(uid, -price)
        db.add_business(uid, bk)
        await update.message.reply_text(f"✅ Куплен {name}")
    elif sub == "собрать":
        uid = update.effective_user.id
        bizs = db.get_user_businesses(uid)
        if not bizs:
            await update.message.reply_text("Нет бизнесов.")
            return
        total = 0
        now = datetime.now()
        for bid, bk, last_collect in bizs:
            if bk not in BUSINESSES:
                continue
            name, price, income, cd = BUSINESSES[bk]
            lc = datetime.fromisoformat(last_collect) if last_collect else now
            if (now - lc).total_seconds() >= cd:
                total += income
                db.update_business_last_collect(bid)
        if total > 0:
            db.add_balance(uid, total)
            await update.message.reply_text(f"💰 Собрано: {total}")
        else:
            await update.message.reply_text("Пока нечего собирать.")
    else:
        await update.message.reply_text("/бизнес | /бизнес купить ID | /бизнес собрать")


async def deposit_cmd(update, context):
    if not context.args:
        lines = [f"🏦 ВКЛАДЫ\n{divider()}"]
        for amt, (rate, hours) in DEPOSIT_RATES.items():
            lines.append(f"• {amt} 💰 → ×{rate} через {hours}ч")
        lines.append("\n/вклад сумма")
        await update.message.reply_text("\n".join(lines))
        return
    if not context.args[0].isdigit():
        return
    amount = int(context.args[0])
    if amount not in DEPOSIT_RATES:
        await update.message.reply_text(f"❌ Доступно: {list(DEPOSIT_RATES.keys())}")
        return
    uid = update.effective_user.id
    if db.get_balance(uid) < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    rate, hours = DEPOSIT_RATES[amount]
    db.add_balance(uid, -amount)
    end_at = (datetime.now() + timedelta(hours=hours)).isoformat()
    db.add_deposit(uid, amount, rate, end_at)
    await update.message.reply_text(f"🏦 Вклад {amount} на {hours}ч (×{rate})")


async def deposit_collect(update, context):
    uid = update.effective_user.id
    deps = db.get_active_deposits(uid)
    total = 0
    now = datetime.now()
    for did, amount, rate, end_at in deps:
        if datetime.fromisoformat(end_at) <= now:
            payout = int(amount * rate)
            db.add_balance(uid, payout)
            db.remove_deposit(did)
            total += payout
    if total > 0:
        await update.message.reply_text(f"💰 Получено: {total}")
    else:
        await update.message.reply_text("Нет готовых вкладов.")


# ============ КРИСТАЛЛЫ ↔ ДОНАТ / МОНЕТЫ ============
async def convert(update, context):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "/convert TYPE сумма\n"
            "TYPE:\n"
            "  cd — 💎→💠 (2:1)\n"
            "  cc — 💎→💰 (1:100)\n"
            "  dc — 💠→💰 (1:200)"
        )
        return
    typ = context.args[0].lower()
    try:
        amt = float(context.args[1])
    except ValueError:
        return
    uid = update.effective_user.id
    if typ == "cd":
        cost = amt * 2
        if db.get_crystals(uid) < cost:
            await update.message.reply_text("❌ Мало кристаллов.")
            return
        db.add_crystals(uid, -cost)
        db.add_donat(uid, int(amt))
        await update.message.reply_text(f"✅ +{int(amt)} 💠")
    elif typ == "cc":
        if db.get_crystals(uid) < amt:
            await update.message.reply_text("❌ Мало кристаллов.")
            return
        db.add_crystals(uid, -amt)
        coins = int(amt * CRYSTAL_TO_COINS)
        db.add_balance(uid, coins)
        await update.message.reply_text(f"✅ +{coins} 💰")
    elif typ == "dc":
        if db.get_donat(uid) < amt:
            await update.message.reply_text("❌ Мало донат-валюты.")
            return
        db.add_donat(uid, -int(amt))
        coins = int(amt * DONAT_TO_COINS)
        db.add_balance(uid, coins)
        await update.message.reply_text(f"✅ +{coins} 💰")
    else:
        await update.message.reply_text("Тип: cd, cc, dc")


# ============ ПОДАРКИ ============
async def gift(update, context):
    if not context.args:
        lines = [f"🎁 ПОДАРКИ\n{divider()}"]
        for k, (name, price) in GIFTS_COMMON.items():
            lines.append(f"{name} — {price} 💰 | ID: {k}")
        limited = db.get_active_limited_gifts()
        if limited:
            lines.append("\n🔮 ЛИМИТИРОВАННЫЕ:")
            for _, k, name, price in limited:
                lines.append(f"{name} — {price} 💰 | ID: {k}")
        lines.append("\n/buy_gift ID")
        await update.message.reply_text("\n".join(lines))
        return


async def buy_gift(update, context):
    if not context.args:
        await update.message.reply_text("/buy_gift ID")
        return
    gk = context.args[0].lower()
    price = None
    if gk in GIFTS_COMMON:
        price = GIFTS_COMMON[gk][1]
    else:
        for _, k, _, p in db.get_active_limited_gifts():
            if k == gk:
                price = p
                break
    if price is None:
        await update.message.reply_text("❌ Нет такого подарка.")
        return
    uid = update.effective_user.id
    if db.get_balance(uid) < price:
        await update.message.reply_text(f"❌ Нужно {price}")
        return
    db.add_balance(uid, -price)
    data = db.get_user(uid)
    gifts = [g for g in (data["gifts"] or "").split(",") if g]
    gifts.append(gk)
    db.update_user(uid, gifts=",".join(gifts))
    await update.message.reply_text(f"🎁 Куплен подарок!")


# ============ СВОИ RP ============
async def add_rp(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if not (data["is_vip"] or "vip" in (data["inventory"] or "")):
        await update.message.reply_text("❌ Только для VIP.")
        return
    if len(context.args) < 3:
        await update.message.reply_text("/add_rp команда эмодзи текст")
        return
    cmd = context.args[0].lower().lstrip("/")
    emoji = context.args[1]
    action = " ".join(context.args[2:])[:60]
    if data["balance"] < CUSTOM_RP_COST:
        await update.message.reply_text(f"❌ Нужно {CUSTOM_RP_COST}")
        return
    if db.add_custom_rp(uid, cmd, emoji, action):
        db.add_balance(uid, -CUSTOM_RP_COST)
        await update.message.reply_text(f"✅ /{cmd} создана!")
    else:
        await update.message.reply_text("❌ Занята.")


async def my_rp(update, context):
    rps = db.get_my_custom_rp(update.effective_user.id)
    if not rps:
        await update.message.reply_text("Нет своих RP.")
        return
    lines = ["💞 Твои RP:"]
    for cmd, emoji, action in rps:
        lines.append(f"{emoji} {cmd} — {action}")
    await update.message.reply_text("\n".join(lines))


# ============ УТИЛИТЫ ============
async def weather(update, context):
    if not context.args:
        await update.message.reply_text("/weather город")
        return
    city = " ".join(context.args)
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://wttr.in/{city}?format=j1"
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                d = await r.json()
                c = d["current_condition"][0]
                await update.message.reply_text(
                    f"🌤 {city}\n🌡 {c['temp_C']}°C (ощущ. {c['FeelsLikeC']}°C)\n"
                    f"☁️ {c['weatherDesc'][0]['value']}\n💧 {c['humidity']}%"
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
        async with aiohttp.ClientSession() as s:
            params = {"client": "gtx", "sl": "auto",
                      "tl": "ru" if any(c.isascii() for c in text) else "en",
                      "dt": "t", "q": text}
            async with s.get("https://translate.googleapis.com/translate_a/single",
                             params=params, timeout=aiohttp.ClientTimeout(total=8)) as r:
                d = await r.json()
                await update.message.reply_text("🌐 " + "".join(seg[0] for seg in d[0]))
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
    cid = update.effective_chat.id
    um = user_mention(update.effective_user)
    async def task():
        await asyncio.sleep(sec)
        try:
            await context.bot.send_message(chat_id=cid, text=f"⏰ {um}, напоминание: {text}", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await context.bot.send_message(chat_id=cid, text=f"⏰ {text}")
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
    cid = update.effective_chat.id
    async def task():
        await asyncio.sleep(sec)
        try:
            await context.bot.send_message(chat_id=cid, text=f"⏲ Таймер {sec}с завершён!")
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
    await update.message.reply_text(f"🔐 {pwd}")


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
    from config import IDEAS
    jokes = ["😄 Программист — машина для превращения кофе в код.",
             "😄 99 багов в коде... уберёшь один — их 127.",
             "😄 — Как дела? — Как в проде."]
    await update.message.reply_text(random.choice(jokes))


async def fact(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://uselessfacts.jsph.pl/random.json?language=en",
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                d = await r.json()
                await update.message.reply_text(f"🧠 {d['text']}")
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
        return
    await update.message.reply_text(f"🎲 {random.choice(opts)}")


async def predict(update, context):
    preds = ["🍀 Удача!", "📩 Новость!", "💸 Осторожно", "💫 Встреча",
             "🚀 Действуй!", "😌 Отдохни", "😊 Улыбнись", "🎁 Сюрприз"]
    await update.message.reply_text(f"🔮 {random.choice(preds)}")


async def quote_cmd(update, context):
    text, author = random.choice(QUOTES)
    await update.message.reply_text(f"🎭 {text}\n— {author}")


async def avatar(update, context):
    t = update.effective_user
    if update.message.reply_to_message:
        t = update.message.reply_to_message.from_user
    try:
        photos = await context.bot.get_user_profile_photos(t.id, limit=1)
        if not photos.photos:
            await update.message.reply_text("🖼 Нет аватара.")
            return
        await update.message.reply_photo(photo=photos.photos[0][-1].file_id, caption=f"🖼 {t.first_name}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# ============ МОДЕРАЦИЯ ============
async def mute(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    t = update.message.reply_to_message.from_user
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
            update.effective_chat.id, t.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await update.message.reply_text(f"🔇 {user_mention(t)} на {duration//60} мин.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def unmute(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    t = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, t.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                        can_send_other_messages=True, can_add_web_page_previews=True)
        )
        await update.message.reply_text(f"🔊 Размучен.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def kick(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    t = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, t.id)
        await context.bot.unban_chat_member(update.effective_chat.id, t.id)
        await update.message.reply_text(f"👢 Кикнут.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def ban(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    t = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, t.id)
        await update.message.reply_text(f"🚫 Забанен.")
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
        await update.message.reply_text(f"✅ Разбанен.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def warn(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    t = update.message.reply_to_message.from_user
    data = db.get_user(t.id, t.username, t.first_name)
    cur = data["warns"] or 0
    db.update_user(t.id, warns=cur + 1)
    new = cur + 1
    await update.message.reply_text(f"⚠️ Варн {new}/3")
    if new >= 3:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, t.id)
            db.update_user(t.id, warns=0)
            await update.message.reply_text("🚫 Забанен за 3 варна.")
        except Exception:
            pass


async def unwarn(update, context):
    if not await is_chat_admin(update, context) or not update.message.reply_to_message:
        return
    t = update.message.reply_to_message.from_user
    cur = db.get_user(t.id)["warns"] or 0
    if cur > 0:
        db.update_user(t.id, warns=cur - 1)
    await update.message.reply_text(f"✅ Осталось: {max(0, cur-1)}")


async def warns_cmd(update, context):
    u = update.effective_user
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
    cur = db.get_user(u.id)["warns"] or 0
    await update.message.reply_text(f"⚠️ Варнов: {cur}")


async def purge(update, context):
    if not await is_chat_admin(update, context):
        return
    if not context.args or not context.args[0].isdigit():
        return
    n = min(max(int(context.args[0]), 1), 100)
    cid = update.effective_chat.id
    mid = update.message.message_id
    deleted = 0
    for i in range(n + 1):
        try:
            await context.bot.delete_message(cid, mid - i)
            deleted += 1
        except Exception:
            pass
    await context.bot.send_message(cid, f"🧹 {deleted}.")


async def rules(update, context):
    chat = db.get_chat(update.effective_chat.id)
    if not chat[2]:
        await update.message.reply_text("Правил нет.")
        return
    await update.message.reply_text(f"📜 {chat[2]}")


async def setrules(update, context):
    if not await is_chat_admin(update, context) or not context.args:
        return
    db.update_chat(update.effective_chat.id, rules=" ".join(context.args)[:1000])
    await update.message.reply_text("✅")


async def welcome_cmd(update, context):
    if not await is_chat_admin(update, context) or not context.args:
        return
    db.update_chat(update.effective_chat.id, welcome=" ".join(context.args)[:500])
    await update.message.reply_text("✅")


async def on_new_member(update, context):
    for m in update.message.new_chat_members:
        chat = db.get_chat(update.effective_chat.id)
        text = chat[1] or f"👋 Добро пожаловать, {m.first_name}!"
        text = text.replace("{name}", m.first_name)
        try:
            await update.message.reply_text(text)
        except Exception:
            pass


# ============ КЛАНЫ ============
async def create_clan(update, context):
    if not context.args:
        await update.message.reply_text("/create_clan Имя")
        return
    name = context.args[0][:30]
    desc = " ".join(context.args[1:])[:200] if len(context.args) > 1 else ""
    uid = update.effective_user.id
    data = db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if data["clan_id"]:
        await update.message.reply_text("❌ Уже в клане.")
        return
    if db.get_clan_by_name(name):
        await update.message.reply_text("❌ Имя занято.")
        return
    cid = db.create_clan(name, uid, desc)
    if not cid:
        await update.message.reply_text("❌ Ошибка.")
        return
    db.update_user(uid, clan_id=cid)
    await grant_achievement(update, uid, "clan_owner")
    await update.message.reply_text(f"🏰 {name} создан!")


async def clans_list(update, context):
    clans = db.get_all_clans(20)
    if not clans:
        await update.message.reply_text("Пусто.")
        return
    lines = [f"🏰 КЛАНЫ\n{divider()}"]
    for c in clans:
        lines.append(f"• {c[1]} — {c[5]} 💰 ({len(db.get_clan_members(c[0]))})")
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
    lines = [f"🏰 {c[1]}\n👑 ID {c[2]}\n💰 {c[5]}\n📝 {c[3] or '—'}",
             f"👥 Участники ({len(members)}):"]
    for uid, un, nk, fn, bal in members[:20]:
        lines.append(f"• {_name_from_row(un, nk, fn, uid)}")
    await update.message.reply_text("\n".join(lines))


async def clan_join(update, context):
    if not context.args:
        return
    c = db.get_clan_by_name(context.args[0])
    if not c:
        await update.message.reply_text("Не найден.")
        return
    uid = update.effective_user.id
    data = db.get_user(uid)
    if data["clan_id"]:
        await update.message.reply_text("Уже в клане.")
        return
    db.update_user(uid, clan_id=c[0])
    await update.message.reply_text(f"✅ Вступил в {c[1]}")


async def clan_leave(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid)
    if not data["clan_id"]:
        await update.message.reply_text("Не в клане.")
        return
    c = db.get_clan(data["clan_id"])
    if c and c[2] == uid:
        await update.message.reply_text("Ты владелец. /clan_delete")
        return
    db.update_user(uid, clan_id=None)
    await update.message.reply_text("👋 Покинул.")


async def clan_deposit(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid)
    if not data["clan_id"]:
        await update.message.reply_text("Не в клане.")
        return
    if not context.args or not context.args[0].isdigit():
        return
    amount = int(context.args[0])
    if amount <= 0 or data["balance"] < amount:
        await update.message.reply_text("❌ Мало монет.")
        return
    db.add_balance(uid, -amount)
    db.add_clan_balance(data["clan_id"], amount)
    await update.message.reply_text(f"💰 Внесено {amount}")


async def clan_top(update, context):
    clans = db.get_all_clans(10)
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"🏆 ТОП КЛАНОВ\n{divider()}"]
    for i, c in enumerate(clans):
        lines.append(f"{medals[i]} {c[1]} — {c[5]} 💰")
    await update.message.reply_text("\n".join(lines))


async def clan_delete(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid)
    if not data["clan_id"]:
        return
    c = db.get_clan(data["clan_id"])
    if not c or c[2] != uid:
        await update.message.reply_text("Только владелец.")
        return
    db.delete_clan(c[0])
    await update.message.reply_text("🗑 Удалён.")


# ============ ЗАМЕТКИ ============
async def save_note(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("/save имя текст")
        return
    name = context.args[0].lower()
    content = " ".join(context.args[1:])
    with db.lock, sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO notes(chat_id, name, content) VALUES(?, ?, ?)",
                    (update.effective_chat.id, name, content))
        conn.commit()
    await update.message.reply_text(f"✅ {name}")


async def get_note(update, context):
    if not context.args:
        return
    name = context.args[0].lower()
    with db.lock, sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT content FROM notes WHERE chat_id=? AND name=?",
                    (update.effective_chat.id, name))
        row = cur.fetchone()
    if row:
        await update.message.reply_text(f"📝 {row[0]}")
    else:
        await update.message.reply_text("Не найдено.")


async def list_notes(update, context):
    with db.lock, sqlite3.connect(db.DB_PATH) as conn:
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
    with db.lock, sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE chat_id=? AND name=?",
                    (update.effective_chat.id, context.args[0].lower()))
        conn.commit()
    await update.message.reply_text("🗑")


# ============ ОБЪЯВЛЕНИЯ ============
async def announcement(update, context):
    uid = update.effective_user.id
    data = db.get_user(uid, update.effective_user.username, update.effective_user.first_name)
    if not context.args:
        await update.message.reply_text(f"📢 Объявление — {ANNOUNCEMENT_COST} 💎\n/announcement текст")
        return
    if (data["crystals"] or 0) < ANNOUNCEMENT_COST:
        await update.message.reply_text(f"❌ Нужно {ANNOUNCEMENT_COST} 💎")
        return
    text = " ".join(context.args)[:500]
    db.add_crystals(uid, -ANNOUNCEMENT_COST)
    db.add_announcement(uid, text)
    chats = db.get_all_chats()
    sent = 0
    for cid in chats:
        try:
            await context.bot.send_message(chat_id=cid, text=f"📢 {text}\n— {display_name(data)}")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ В {sent} чатов.")


# ============ ПРОМОКОДЫ ============
async def promo_use(update, context):
    if not context.args:
        await update.message.reply_text("/promo КОД")
        return
    code = context.args[0].upper()
    uid = update.effective_user.id
    reward, msg = db.use_promo(code, uid)
    if reward is None:
        await update.message.reply_text(f"❌ {msg}")
        return
    db.add_balance(uid, reward)
    await update.message.reply_text(f"✅ Активирован! +{reward} 💰")


# ============ СПОНСОРЫ ============
async def sponsor_list(update, context):
    sponsors = db.get_all_sponsors()
    if not sponsors:
        await update.message.reply_text("Спонсоров нет.")
        return
    lines = [f"📢 СПОНСОРЫ\n{divider()}"]
    kb = []
    for sid, cid, title, url, reward in sponsors:
        done = db.is_sponsor_done(sid, update.effective_user.id)
        mark = "✅" if done else "🔴"
        lines.append(f"{mark} [{title}]({url}) — {reward} 💰")
        if not done:
            kb.append([InlineKeyboardButton(f"Я подписался: {title}", callback_data=f"sp_check:{sid}")])
    if kb:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                        disable_web_page_preview=True,
                                        reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                        disable_web_page_preview=True)


async def sponsor_check_cb(update, context):
    q = update.callback_query
    await q.answer()
    sid = int(q.data.split(":")[1])
    sponsors = db.get_all_sponsors()
    sp = next((s for s in sponsors if s[0] == sid), None)
    if not sp:
        await q.edit_message_text("Спонсор не найден.")
        return
    _, cid, title, url, reward = sp
    uid = q.from_user.id
    if db.is_sponsor_done(sid, uid):
        await q.answer("Уже получено.", show_alert=True)
        return
    try:
        m = await context.bot.get_chat_member(cid, uid)
        if m.status in ("left", "kicked"):
            await q.answer("❌ Ты не подписан!", show_alert=True)
            return
    except Exception:
        await q.answer("Не могу проверить подписку.", show_alert=True)
        return
    if db.mark_sponsor_done(sid, uid):
        db.add_balance(uid, reward)
        await q.answer(f"✅ +{reward} 💰", show_alert=True)
        await q.edit_message_text(f"✅ Спонсор {title} выполнен! +{reward} 💰")


# ============ АДМИН-ПАНЕЛЬ ============
async def admin_help(update, context):
    uid = update.effective_user.id
    uname = update.effective_user.username
    if not is_bot_admin(uid, uname):
        await update.message.reply_text("❌ Только для админов бота.")
        return
    text = (
        "👑 АДМИН-ПАНЕЛЬ\n" + divider() + "\n"
        "💰 ФИНАНСЫ:\n"
        "admin_setbal @юзер сумма\n"
        "admin_addbal @юзер сумма\n"
        "admin_takebal @юзер сумма\n"
        "admin_setcrystals @юзер сумма\n"
        "admin_adddonat @юзер сумма\n"
        "admin_takedonat @юзер сумма\n\n"
        "👤 ПОЛЬЗОВАТЕЛИ:\n"
        "admin_user @юзер\n"
        "admin_reset @юзер\n"
        "admin_ban @юзер / admin_unban\n"
        "admin_freeze / admin_unfreeze\n"
        "admin_setname @юзер имя\n"
        "admin_unmarry @юзер\n"
        "admin_giveitem @юзер ID\n"
        "admin_setvip @юзер (1/0)\n"
        "admin_setcrown @юзер (1/0)\n\n"
        "🏆 АЧИВКИ:\n"
        "admin_makeach ключ | Название | Описание\n"
        "admin_giveach @юзер ключ\n"
        "admin_takeach @юзер ключ\n\n"
        "📢 СПОНСОРЫ И ПРОМО:\n"
        "admin_sponsor @канал_username Название награда\n"
        "admin_promo КОД сумма активации часы\n\n"
        "🌐 ЧАТЫ:\n"
        "admin_chats\n"
        "admin_broadcast текст\n"
        "admin_stats\n\n"
        "⚙️: admin_ping / admin_version"
    )
    await update.message.reply_text(text)


async def admin_stats(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    with db.lock, sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users"); tu = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users WHERE married_to IS NOT NULL"); m = cur.fetchone()[0] // 2
        cur.execute("SELECT COUNT(*) FROM chats"); tc = cur.fetchone()[0]
        cur.execute("SELECT SUM(balance) FROM users"); tb = cur.fetchone()[0] or 0
        cur.execute("SELECT SUM(donat) FROM users"); td = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM clans"); tcl = cur.fetchone()[0]
    await update.message.reply_text(
        f"📊 СТАТИСТИКА\n👥 {tu}\n💬 {tc}\n💑 {m}\n🏰 {tcl}\n💰 {tb}\n💠 {td}"
    )


async def _resolve(update, context):
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
        with db.lock, sqlite3.connect(db.DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (name,))
            row = cur.fetchone()
            if row:
                return db._row(row)
    return None


async def admin_user(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        await update.message.reply_text("Укажи @юзер.")
        return
    await update.message.reply_text(
        f"👤 {display_name(data)}\n"
        f"ID: {data['user_id']}\n"
        f"💰 {data['balance']}\n💎 {(data['crystals'] or 0):.1f}\n💠 {data['donat'] or 0}\n"
        f"⚠️ {data['warns']}\n"
        f"🚫 бан: {data['is_banned']}\n🧊 мороз: {data['is_frozen']}\n"
        f"⭐ VIP: {data['is_vip']}\n👑 корона: {data['has_crown']}\n"
        f"💬 {data['messages'] or 0}"
    )


async def admin_setbal(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx or not context.args[idx].lstrip("-").isdigit():
        return
    amount = int(context.args[idx])
    db.update_user(data["user_id"], balance=amount)
    await update.message.reply_text(f"✅ = {amount}")


async def admin_addbal(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
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
    await update.message.reply_text(f"✅ +{amount}")


async def admin_takebal(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
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
    await update.message.reply_text(f"✅ -{amount}")


async def admin_setcrystals(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
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
    await update.message.reply_text(f"✅ = {amount} 💎")


async def admin_adddonat(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    try:
        amount = int(context.args[idx])
    except ValueError:
        return
    db.add_donat(data["user_id"], amount)
    await update.message.reply_text(f"✅ +{amount} 💠")


async def admin_takedonat(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    try:
        amount = int(context.args[idx])
    except ValueError:
        return
    db.add_donat(data["user_id"], -amount)
    await update.message.reply_text(f"✅ -{amount} 💠")


async def admin_setvip(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx or context.args[idx] not in ("0", "1"):
        return
    val = int(context.args[idx])
    db.update_user(data["user_id"], is_vip=val)
    await update.message.reply_text(f"✅ VIP = {val}")


async def admin_setcrown(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx or context.args[idx] not in ("0", "1"):
        return
    val = int(context.args[idx])
    db.update_user(data["user_id"], has_crown=val)
    await update.message.reply_text(f"✅ Корона = {val}")


async def admin_reset(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    db.update_user(data["user_id"],
                   balance=START_BALANCE, warns=0, married_to=None,
                   inventory="", stats_played=0, stats_won=0, daily_streak=0,
                   quest_progress="{}", achievements="", clan_id=None, reputation=0,
                   crystals=0, donat=0, messages=0, marriage_level=1, marriage_xp=0)
    await update.message.reply_text(f"🔄 Сброшен.")


async def admin_ban(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_banned=1)
    await update.message.reply_text("🚫 Забанен в боте.")


async def admin_unban(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_banned=0)
    await update.message.reply_text("✅ Разбанен.")


async def admin_freeze(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_frozen=1)
    await update.message.reply_text("🧊 Заморожен.")


async def admin_unfreeze(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    db.update_user(data["user_id"], is_frozen=0)
    await update.message.reply_text("🔥 Разморожен.")


async def admin_unmarry(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data or not data["married_to"]:
        return
    db.update_user(data["user_id"], married_to=None, marriage_level=1, marriage_xp=0)
    db.update_user(data["married_to"], married_to=None, marriage_level=1, marriage_xp=0)
    await update.message.reply_text("💔 Разведён.")


async def admin_setname(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    new_name = " ".join(context.args[idx:])[:40]
    db.update_user(data["user_id"], nickname=new_name)
    await update.message.reply_text(f"✅ Ник: {new_name}")


async def admin_giveitem(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    iid = context.args[idx].lower()
    if iid not in SHOP_ITEMS:
        return
    inv = [i for i in (data["inventory"] or "").split(",") if i]
    inv.append(iid)
    db.update_user(data["user_id"], inventory=",".join(inv))
    await update.message.reply_text(f"✅ {SHOP_ITEMS[iid][0]}")


async def admin_giveach(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    aid = context.args[idx]
    if aid not in ACHIEVEMENTS and not db.get_custom_achievement(aid):
        await update.message.reply_text("Нет такой.")
        return
    db.add_achievement(data["user_id"], aid)
    await update.message.reply_text("🏆 Выдано.")


async def admin_takeach(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    data = await _resolve(update, context)
    if not data:
        return
    idx = 0 if update.message.reply_to_message else 1
    if len(context.args) <= idx:
        return
    aid = context.args[idx]
    got = [a for a in (data["achievements"] or "").split(",") if a]
    if aid in got:
        got.remove(aid)
    db.update_user(data["user_id"], achievements=",".join(got))
    await update.message.reply_text("🗑 Снято.")


async def admin_makeach(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    if len(context.args) < 3:
        await update.message.reply_text("/admin_makeach ключ | Название | Описание")
        return
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        await update.message.reply_text("Формат: ключ | Название | Описание")
        return
    key, name, desc = parts[0], parts[1], parts[2]
    if db.add_custom_achievement(key, name, desc, "🏆", update.effective_user.id):
        await update.message.reply_text(f"✅ Ачивка {key} создана.")
    else:
        await update.message.reply_text("❌ Ключ занят.")


async def admin_sponsor(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    if len(context.args) < 3:
        await update.message.reply_text("/admin_sponsor @канал Название награда")
        return
    ch = context.args[0]
    reward = context.args[-1]
    title = " ".join(context.args[1:-1])
    try:
        reward = int(reward)
    except ValueError:
        await update.message.reply_text("Награда — число.")
        return
    try:
        chat = await context.bot.get_chat(ch)
        cid = chat.id
        url = f"https://t.me/{ch.lstrip('@')}"
        db.add_sponsor(cid, title, url, reward)
        await update.message.reply_text(f"✅ Спонсор {title} добавлен.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


async def admin_promo(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    if len(context.args) < 4:
        await update.message.reply_text("/admin_promo КОД сумма активации часы")
        return
    code = context.args[0]
    try:
        reward = int(context.args[1])
        max_acts = int(context.args[2])
        hours = int(context.args[3])
    except ValueError:
        return
    if db.create_promo(code, reward, max_acts, hours):
        await update.message.reply_text(f"✅ Промокод {code.upper()} создан.")
    else:
        await update.message.reply_text("❌ Уже есть.")


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
            await context.bot.send_message(chat_id=cid, text=f"📢 {text}")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"📢 OK: {sent}")


async def admin_chats(update, context):
    if not is_bot_admin(update.effective_user.id, update.effective_user.username):
        return
    chats = db.get_all_chats()
    await update.message.reply_text(f"💬 Чатов: {len(chats)}\n" + "\n".join(str(c) for c in chats[:30]))


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
    await update.message.reply_text("🤖 v8.0")


# ============ TEXT ROUTER ============
async def text_router(update, context):
    u = update.effective_user
    data = db.get_user(u.id, u.username, u.first_name)
    if data["is_banned"] or data["is_frozen"]:
        return
    try:
        db.add_message(u.id, update.effective_chat.id)
    except Exception:
        pass
    if (data["messages"] or 0) >= 1000:
        db.add_achievement(u.id, "chatterbox")
    await handle_guess(update, context)
    await handle_quiz(update, context)


async def ru_commands_handler(update, context):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    words = text.split()
    if not words:
        return
    first = words[0].lower().strip("!,.?")
    # проверяем русские команды
    if first in RU_COMMANDS:
        target_func_name = RU_COMMANDS[first]
        func = globals().get(target_func_name)
        if func:
            context.args = words[1:]
            try:
                await func(update, context)
            except Exception as e:
                logger.error(f"ru cmd err: {e}")
        return


# ============ ЗАПУСК ============
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
                BotCommand("top", "🏆 Топ монет"),
                BotCommand("top_ref", "💎 Топ кристаллов"),
                BotCommand("top_donat", "💠 Топ донатов"),
                BotCommand("top_casino", "🎰 Топ побед"),
                BotCommand("shop", "🛒 Магазин"),
                BotCommand("games", "🎮 Игры"),
                BotCommand("casino", "🎰 Казино"),
                BotCommand("rp", "💞 RP"),
                BotCommand("referral", "🎁 Кристаллы"),
                BotCommand("donate", "💠 Донат"),
                BotCommand("time", "🕐 Время"),
                BotCommand("currency", "💱 Валюты"),
                BotCommand("marry", "💍 Брак"),
                BotCommand("clans", "👑 Кланы"),
                BotCommand("adminhelp", "👑 Админ"),
            ])
        except Exception as e:
            logger.warning(f"set_my_commands: {e}")

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # ===== ОСНОВНОЕ =====
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("id", id_command))

    # ===== СПРАВКИ =====
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

    # ===== ВРЕМЯ / ВАЛЮТЫ =====
    application.add_handler(CommandHandler("msk", moscow_time))
    application.add_handler(CommandHandler("moscow", moscow_time))
    application.add_handler(CommandHandler("time", time_cmd))
    application.add_handler(CommandHandler("currency", currency))
    application.add_handler(CommandHandler("crypto", crypto))

    # ===== РЕФЕРАЛЫ / ДОНАТ =====
    application.add_handler(CommandHandler("referral", referral))
    application.add_handler(CommandHandler("ref", referral))
    application.add_handler(CommandHandler("donate", donate_info))

    # ===== ТОПЫ =====
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("top_ref", top_ref))
    application.add_handler(CommandHandler("top_donat", top_donat))
    application.add_handler(CommandHandler("top_casino", top_casino))
    application.add_handler(CommandHandler("top_day", top_messages_day))
    application.add_handler(CommandHandler("top_week", top_messages_week))
    application.add_handler(CommandHandler("top_messages", top_messages_all))
    application.add_handler(CommandHandler("chat_stats", chat_stats))
    application.add_handler(CommandHandler("all_chats", all_chats_stats))

    # ===== ИГРЫ =====
    application.add_handler(CommandHandler("roll", roll))
    application.add_handler(CommandHandler("coin", coin))
    application.add_handler(CommandHandler("dice", dice_game))
    application.add_handler(CommandHandler("basketball", basketball_free))
    application.add_handler(CommandHandler("basket", basketball_free))
    application.add_handler(CommandHandler("football", football_free))
    application.add_handler(CommandHandler("soccer", football_free))
    application.add_handler(CommandHandler("bowling", bowling_free))
    application.add_handler(CommandHandler("darts", darts_free))
    application.add_handler(CommandHandler("slot", slot))
    application.add_handler(CommandHandler("guess", guess))
    application.add_handler(CommandHandler("stopguess", stop_guess))
    application.add_handler(CommandHandler("duel", duel))
    application.add_handler(CommandHandler("quiz", quiz))
    application.add_handler(CommandHandler("trivia", trivia))
    application.add_handler(CommandHandler("8ball", ball8))
    application.add_handler(CommandHandler("random", random_number))

    # ===== КАЗИНО =====
    application.add_handler(CommandHandler("bet_flip", bet_flip))
    application.add_handler(CommandHandler("roulette", roulette))
    application.add_handler(CommandHandler("blackjack", blackjack))
    application.add_handler(CommandHandler("bet_dice", bet_dice))
    application.add_handler(CommandHandler("football_bet", football_bet))
    application.add_handler(CommandHandler("basket_bet", basket_bet))
    application.add_handler(CommandHandler("bowling_bet", bowling_bet))

    # ===== ЭКОНОМИКА =====
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
    application.add_handler(CommandHandler("pin_ach", pin_ach))
    application.add_handler(CommandHandler("rep", rep))

    # ===== ПРОФИЛЬ =====
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("nick", nick_cmd))
    application.add_handler(CommandHandler("bio", bio))
    application.add_handler(CommandHandler("title", title_cmd))

    # ===== БРАК =====
    application.add_handler(CommandHandler("marry", marry))
    application.add_handler(CommandHandler("divorce", divorce))
    application.add_handler(CommandHandler("couple", couple))
    application.add_handler(CommandHandler("marriage_gift", marriage_gift))
    application.add_handler(CommandHandler("love", love_calc))
    application.add_handler(CommandHandler("ship", ship))

    # ===== БИЗНЕС / ВКЛАД =====
    application.add_handler(CommandHandler("бизнес", biz))
    application.add_handler(CommandHandler("biz", biz))
    application.add_handler(CommandHandler("вклад", deposit_cmd))
    application.add_handler(CommandHandler("deposit", deposit_cmd))
    application.add_handler(CommandHandler("deposit_collect", deposit_collect))
    application.add_handler(CommandHandler("convert", convert))

    # ===== ПОДАРКИ =====
    application.add_handler(CommandHandler("gift", gift))
    application.add_handler(CommandHandler("buy_gift", buy_gift))

    # ===== СВОИ RP =====
    application.add_handler(CommandHandler("add_rp", add_rp))
    application.add_handler(CommandHandler("my_rp", my_rp))

    # ===== RP (латиница) =====
    for k in RP_ACTIONS.keys():
        application.add_handler(CommandHandler(k, make_rp_handler(k)))

    # ===== УТИЛИТЫ =====
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

    # ===== МОДЕРАЦИЯ =====
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

    # ===== КЛАНЫ =====
    application.add_handler(CommandHandler("create_clan", create_clan))
    application.add_handler(CommandHandler("clan_info", clan_info))
    application.add_handler(CommandHandler("clan_join", clan_join))
    application.add_handler(CommandHandler("clan_leave", clan_leave))
    application.add_handler(CommandHandler("clan_deposit", clan_deposit))
    application.add_handler(CommandHandler("clan_top", clan_top))
    application.add_handler(CommandHandler("clan_delete", clan_delete))
    application.add_handler(CommandHandler("clans_list", clans_list))

    # ===== ЗАМЕТКИ =====
    application.add_handler(CommandHandler("save", save_note))
    application.add_handler(CommandHandler("get", get_note))
    application.add_handler(CommandHandler("notes", list_notes))
    application.add_handler(CommandHandler("del", del_note))

    # ===== ОБЪЯВЛЕНИЯ =====
    application.add_handler(CommandHandler("announcement", announcement))

    # ===== ПРОМОКОДЫ / СПОНСОРЫ =====
    application.add_handler(CommandHandler("promo", promo_use))
    application.add_handler(CommandHandler("sponsors", sponsor_list))

    # ===== АДМИН =====
    application.add_handler(CommandHandler("adminhelp", admin_help))
    application.add_handler(CommandHandler("admin_help", admin_help))
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("admin_user", admin_user))
    application.add_handler(CommandHandler("admin_setbal", admin_setbal))
    application.add_handler(CommandHandler("admin_addbal", admin_addbal))
    application.add_handler(CommandHandler("admin_takebal", admin_takebal))
    application.add_handler(CommandHandler("admin_setcrystals", admin_setcrystals))
    application.add_handler(CommandHandler("admin_adddonat", admin_adddonat))
    application.add_handler(CommandHandler("admin_takedonat", admin_takedonat))
    application.add_handler(CommandHandler("admin_setvip", admin_setvip))
    application.add_handler(CommandHandler("admin_setcrown", admin_setcrown))
    application.add_handler(CommandHandler("admin_reset", admin_reset))
    application.add_handler(CommandHandler("admin_ban", admin_ban))
    application.add_handler(CommandHandler("admin_unban", admin_unban))
    application.add_handler(CommandHandler("admin_freeze", admin_freeze))
    application.add_handler(CommandHandler("admin_unfreeze", admin_unfreeze))
    application.add_handler(CommandHandler("admin_unmarry", admin_unmarry))
    application.add_handler(CommandHandler("admin_setname", admin_setname))
    application.add_handler(CommandHandler("admin_giveitem", admin_giveitem))
    application.add_handler(CommandHandler("admin_giveach", admin_giveach))
    application.add_handler(CommandHandler("admin_takeach", admin_takeach))
    application.add_handler(CommandHandler("admin_makeach", admin_makeach))
    application.add_handler(CommandHandler("admin_sponsor", admin_sponsor))
    application.add_handler(CommandHandler("admin_promo", admin_promo))
    application.add_handler(CommandHandler("admin_chats", admin_chats))
    application.add_handler(CommandHandler("admin_broadcast", admin_broadcast))
    application.add_handler(CommandHandler("admin_ping", admin_ping))
    application.add_handler(CommandHandler("admin_version", admin_version))

    # ===== INLINE =====
    application.add_handler(CallbackQueryHandler(duel_callback, pattern=r"^duel_"))
    application.add_handler(CallbackQueryHandler(marry_callback, pattern=r"^marry_"))
    application.add_handler(CallbackQueryHandler(blackjack_callback, pattern=r"^bj_"))
    application.add_handler(CallbackQueryHandler(sponsor_check_cb, pattern=r"^sp_check:"))

    # ===== НОВЫЕ УЧАСТНИКИ =====
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))

    # ===== РУССКИЕ (без слэша) — в группе 1 =====
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ru_commands_handler),
        group=1
    )

    # ===== ОБЫЧНЫЙ ТЕКСТ =====
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

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
