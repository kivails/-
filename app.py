import os
import random
import logging
import json
import asyncio
import threading
import aiohttp
from datetime import datetime, timedelta
from io import BytesIO
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import (
    TOKEN, DAILY_REWARD, QUIZ_REWARD, GUESS_REWARD, DUEL_REWARD,
    DICE_REWARD, SLOT_COST, SLOT_JACKPOT, SLOT_PAIR, SHOP_ITEMS,
    QUESTS, RP_ACTIONS
)
import database as db

# ---------- Логирование ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Flask для Render ----------
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health():
    return "OK", 200

# ---------- Временные состояния (не критичные для БД) ----------
guess_games = {}
duel_games = {}
quiz_games = {}
reminder_tasks = {}

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
]

JOKES = [
    "— Что сказал программист, когда закончил работу? — Ещё один commit, и я спать.",
    "Программист — это машина для превращения кофе в код.",
    "— Почему программисты путают Хэллоуин и Рождество? — Потому что Oct 31 == Dec 25.",
    "Есть 10 типов людей: те, кто понимает двоичную систему, и те, кто нет.",
    "— Как называется страх перед программированием? — Кодофобия.",
    "99 маленьких багов в коде, 99 маленьких багов... Уберёшь один — их 127.",
]

# ---------- Утилиты ----------
def mention(user) -> str:
    return f"[{user.first_name}](tg://user?id={user.id})"

def mention_by_id(user_id: int, name: str = "Пользователь") -> str:
    return f"[{name}](tg://user?id={user_id})"

async def fetch_anime_gif(url: str):
    """Получить URL аниме-гифки с nekos.best"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["results"][0]["url"]
    except Exception as e:
        logger.warning(f"Gif fetch failed: {e}")
    return None

async def send_rp(update, context, action_key: str):
    """Отправить RP-действие с гифкой"""
    emoji, action, api_url = RP_ACTIONS[action_key]
    actor = update.effective_user

    # Определяем цель
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        name = context.args[0].lstrip('@')
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, name)
            target = member.user
        except Exception:
            target = None

    gif = await fetch_anime_gif(api_url)

    if target is None or target.id == actor.id:
        caption = f"{emoji} {mention(actor)} {action} сам(а) себя 😅"
    else:
        caption = f"{emoji} {mention(actor)} {action} {mention(target)}"

    try:
        if gif:
            await update.message.reply_animation(
                animation=gif, caption=caption, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"send_rp error: {e}")
        await update.message.reply_text(caption, parse_mode=ParseMode.MARKDOWN)

def check_quest(user_id: int, quest_key: str, increment: int = 1):
    """Обновить прогресс квеста и вернуть (выполнен?, награда)"""
    user = db.get_user(user_id)
    progress = json.loads(user[12] or '{}')
    progress[quest_key] = progress.get(quest_key, 0) + increment
    db.update_user(user_id, quest_progress=json.dumps(progress))

    description, target, reward = QUESTS[quest_key]
    if progress[quest_key] == target:  # только при первом достижении
        db.add_balance(user_id, reward)
        return True, reward, description
    return False, 0, description

# ==================== БАЗОВЫЕ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 **Многофункциональный бот v2.0**\n\n"
        "🎮 **Игры:**\n"
        "/roll [макс] — кубик\n"
        "/coin — монетка\n"
        "/dice — кости против бота\n"
        "/slot — автомат (ставка 10)\n"
        "/guess — угадай число\n"
        "/stopguess — стоп игру\n"
        "/duel @юзер — дуэль (КНБ)\n"
        "/quiz — викторина\n"
        "/trivia — другая викторина\n\n"
        "💰 **Экономика:**\n"
        "/balance [@юзер] — баланс\n"
        "/daily — бонус (+50)\n"
        "/top — топ-10\n"
        "/pay @юзер сумма — перевод\n"
        "/shop — магазин\n"
        "/buy ID — купить товар\n"
        "/inventory — инвентарь\n"
        "/quests — квесты\n\n"
        "💞 **RP (с аниме-гифками):**\n"
        "/hug /kiss /slap /pat /kick /punch\n"
        "/bite /lick /cuddle /poke /wave\n"
        "/highfive /bonk /yeet /blush /smile\n"
        "/happy /wink /dance /cry /pout\n"
        "*(можно в ответ на сообщение или @юзер)*\n\n"
        "💍 **Отношения:**\n"
        "/marry @юзер — жениться\n"
        "/divorce — развестись\n"
        "/couple — показать пару\n"
        "/bio текст — о себе\n"
        "/profile [@юзер] — профиль\n"
        "/title текст — приписка (нужен VIP)\n\n"
        "🛡 **Модерация (для админов):**\n"
        "/mute [время] — замутить (ответом)\n"
        "/unmute — размутить\n"
        "/kick — кикнуть\n"
        "/ban — забанить\n"
        "/unban — разбанить\n"
        "/warn — предупреждение\n"
        "/unwarn — снять варн\n"
        "/warns — варны пользователя\n"
        "/rules — правила чата\n"
        "/setrules текст — задать правила\n"
        "/welcome текст — приветствие\n\n"
        "📌 **Заметки:**\n"
        "/save имя текст — сохранить\n"
        "/get имя — получить\n"
        "/notes — все заметки\n"
        "/del имя — удалить\n\n"
        "🔧 **Прочее:**\n"
        "/joke — шутка\n"
        "/fact — факт\n"
        "/weather город — погода\n"
        "/tr текст — перевод (en↔ru)\n"
        "/remind 10m текст — напоминание\n"
        "/id — ID чата/юзера\n"
        "/ping — пинг\n"
        "/stats — статистика\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = datetime.now()
    msg = await update.message.reply_text("🏓 Понг...")
    delta = (datetime.now() - start_time).total_seconds() * 1000
    await msg.edit_text(f"🏓 Понг! `{delta:.0f}мс`", parse_mode=ParseMode.MARKDOWN)

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    text = (
        f"🆔 **Ваш ID:** `{user.id}`\n"
        f"💬 **ID чата:** `{chat.id}`\n"
        f"📛 **Тип чата:** {chat.type}"
    )
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        text += f"\n👤 **ID {target.first_name}:** `{target.id}`"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ==================== ИГРЫ ====================

async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        max_num = int(context.args[0]) if context.args else 100
        if max_num < 2:
            max_num = 100
    except (ValueError, IndexError):
        max_num = 100
    result = random.randint(1, max_num)
    await update.message.reply_text(
        f"🎲 {mention(update.effective_user)} бросает кубик...\n"
        f"Выпало: **{result}** (1–{max_num})",
        parse_mode=ParseMode.MARKDOWN
    )

async def coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.choice(["Орёл 🦅", "Решка 🪙"])
    await update.message.reply_text(
        f"🪙 {mention(update.effective_user)} подбрасывает монетку...\n"
        f"Результат: **{result}**",
        parse_mode=ParseMode.MARKDOWN
    )

async def slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.get_balance(user_id) < SLOT_COST:
        await update.message.reply_text("❌ Нужно 10 монет. Заработайте через /daily.")
        return
    symbols = ["🍒", "🍋", "🍊", "💎", "7️⃣", "⭐"]
    reels = [random.choice(symbols) for _ in range(3)]
    db.add_balance(user_id, -SLOT_COST)

    if reels[0] == reels[1] == reels[2]:
        win = SLOT_JACKPOT
        db.add_balance(user_id, win)
        msg = f"🎰 {' | '.join(reels)}\n\n💥 ДЖЕКПОТ! +{win} монет!"
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        win = SLOT_PAIR
        db.add_balance(user_id, win)
        msg = f"🎰 {' | '.join(reels)}\n\n✨ Пара! +{win} монет."
    else:
        msg = f"🎰 {' | '.join(reels)}\n\n😢 Не повезло. -10 монет."

    db.get_user(user_id)
    db.update_user(user_id, stats_played=db.get_user(user_id)[9] + 1)
    if "выиграли" in msg or "ДЖЕКПОТ" in msg or "+" in msg:
        db.update_user(user_id, stats_won=db.get_user(user_id)[10] + 1)

    msg += f"\n\n💰 Баланс: {db.get_balance(user_id)}"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = random.randint(1, 6)
    bot = random.randint(1, 6)
    user_id = update.effective_user.id
    db.get_user(user_id)
    db.update_user(user_id, stats_played=db.get_user(user_id)[9] + 1)

    if player > bot:
        result = "🏆 Вы победили! +20 монет"
        db.add_balance(user_id, DICE_REWARD)
        db.update_user(user_id, stats_won=db.get_user(user_id)[10] + 1)
        await check_quest(user_id, "win_3")
    elif player < bot:
        result = "🤖 Бот победил!"
    else:
        result = "🤝 Ничья!"

    await update.message.reply_text(
        f"🎲 {mention(update.effective_user)}: {player}\n"
        f"🤖 Бот: {bot}\n\n{result}",
        parse_mode=ParseMode.MARKDOWN
    )
    await check_quest(user_id, "play_5")

# ---- Угадай число ----

async def guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in guess_games:
        await update.message.reply_text("❌ Уже идёт. /stopguess.")
        return
    guess_games[chat_id] = {
        'number': random.randint(1, 100),
        'attempts': 0
    }
    await update.message.reply_text(
        "🔢 **Угадай число (1–100)!**\nПобеда = +30 монет",
        parse_mode=ParseMode.MARKDOWN
    )

async def stop_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in guess_games:
        num = guess_games[chat_id]['number']
        del guess_games[chat_id]
        await update.message.reply_text(f"🛑 Было: **{num}**", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Нет активной игры.")

async def handle_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in guess_games:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        return
    guess_num = int(text)
    game = guess_games[chat_id]
    game['attempts'] += 1

    if guess_num < game['number']:
        await update.message.reply_text(f"📈 Больше! ({game['attempts']})")
    elif guess_num > game['number']:
        await update.message.reply_text(f"📉 Меньше! ({game['attempts']})")
    else:
        user_id = update.effective_user.id
        db.add_balance(user_id, GUESS_REWARD)
        await update.message.reply_text(
            f"🎉 {mention(update.effective_user)} угадал(а)! **{game['number']}**\n"
            f"Попыток: {game['attempts']} | +{GUESS_REWARD} монет",
            parse_mode=ParseMode.MARKDOWN
        )
        del guess_games[chat_id]

# ---- Дуэль ----

async def duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not update.message.reply_to_message and not context.args:
        await update.message.reply_text("Использование: /duel @юзер (или ответом).")
        return

    if update.message.reply_to_message:
        opponent = update.message.reply_to_message.from_user
    else:
        target = context.args[0].lstrip('@')
        try:
            member = await context.bot.get_chat_member(chat_id, target)
            opponent = member.user
        except Exception:
            await update.message.reply_text("Не нашёл пользователя.")
            return

    challenger = update.effective_user
    if opponent.id == challenger.id:
        await update.message.reply_text("Нельзя вызвать себя!")
        return

    duel_games[chat_id] = {
        'challenger': challenger.id,
        'opponent': opponent.id,
        'choice1': None,
        'choice2': None,
        'names': {challenger.id: challenger.first_name, opponent.id: opponent.first_name}
    }

    keyboard = [[
        InlineKeyboardButton("✊ Камень", callback_data="duel_rock"),
        InlineKeyboardButton("✌️ Ножницы", callback_data="duel_scissors"),
        InlineKeyboardButton("✋ Бумага", callback_data="duel_paper"),
    ]]
    await update.message.reply_text(
        f"⚔️ {mention(challenger)} vs {mention(opponent)}\nВыбирайте ход!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def duel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_id = query.from_user.id

    if chat_id not in duel_games:
        await query.edit_message_text("Дуэль завершена.")
        return

    game = duel_games[chat_id]
    if user_id not in (game['challenger'], game['opponent']):
        await query.answer("Вы не участник!", show_alert=True)
        return

    choice_map = {'duel_rock': '✊', 'duel_scissors': '✌️', 'duel_paper': '✋'}
    choice = choice_map[query.data]

    if user_id == game['challenger']:
        if game['choice1']:
            await query.answer("Вы уже сделали ход!")
            return
        game['choice1'] = choice
    else:
        if game['choice2']:
            await query.answer("Вы уже сделали ход!")
            return
        game['choice2'] = choice

    if game['choice1'] and game['choice2']:
        c1, c2 = game['choice1'], game['choice2']
        if c1 == c2:
            result = "🤝 Ничья!"
        elif (c1 == '✊' and c2 == '✌️') or (c1 == '✌️' and c2 == '✋') or (c1 == '✋' and c2 == '✊'):
            winner_id = game['challenger']
            db.add_balance(winner_id, DUEL_REWARD)
            result = f"🏆 Победил(а) {game['names'][winner_id]}! +{DUEL_REWARD} монет"
        else:
            winner_id = game['opponent']
            db.add_balance(winner_id, DUEL_REWARD)
            result = f"🏆 Победил(а) {game['names'][winner_id]}! +{DUEL_REWARD} монет"

        n1 = game['names'][game['challenger']]
        n2 = game['names'][game['opponent']]
        await query.edit_message_text(
            f"⚔️ Дуэль завершена!\n\n{n1}: {c1}\n{n2}: {c2}\n\n{result}"
        )
        del duel_games[chat_id]
    else:
        await query.answer("Ход принят! Ждём соперника.", show_alert=True)

# ---- Викторины ----

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    question, answer = random.choice(QUIZ_QUESTIONS)
    quiz_games[chat_id] = {'answer': answer.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(
        f"❓ **Викторина!**\n\n{question}\n\n+{QUIZ_REWARD} монет за верный ответ!",
        parse_mode=ParseMode.MARKDOWN
    )

async def trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Дополнительная викторина — другой набор вопросов"""
    questions = [
        ("Какой самый быстрый наземный зверь?", "гепард"),
        ("Сколько ног у паука?", "8"),
        ("Что означает HTML?", "hypertext markup language"),
        ("Какой океан самый большой?", "тихий"),
        ("Кто написал «Гарри Поттер»?", "роулинг"),
    ]
    chat_id = update.effective_chat.id
    question, answer = random.choice(questions)
    quiz_games[chat_id] = {'answer': answer.lower(), 'reward': QUIZ_REWARD}
    await update.message.reply_text(
        f"🧠 **Тривия!**\n\n{question}\n\n+{QUIZ_REWARD} монет!",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in quiz_games:
        return
    text = update.message.text.strip().lower()
    if text == quiz_games[chat_id]['answer']:
        reward = quiz_games[chat_id]['reward']
        user_id = update.effective_user.id
        db.add_balance(user_id, reward)
        del quiz_games[chat_id]
        await update.message.reply_text(
            f"✅ Верно, {mention(update.effective_user)}! +{reward} монет.",
            parse_mode=ParseMode.MARKDOWN
        )

# ==================== ЭКОНОМИКА ====================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    bal = db.get_balance(user.id)
    await update.message.reply_text(
        f"💰 Баланс {mention(user)}: **{bal}** монет",
        parse_mode=ParseMode.MARKDOWN
    )

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    last = user[11]
    now = datetime.now()

    if last:
        last_dt = datetime.fromisoformat(last)
        if now - last_dt < timedelta(hours=24):
            remain = timedelta(hours=24) - (now - last_dt)
            h = remain.seconds // 3600
            m = (remain.seconds % 3600) // 60
            await update.message.reply_text(f"⏳ Следующий бонус через {h}ч {m}м.")
            return

    streak = user[10] + 1 if last and (now - datetime.fromisoformat(last)) < timedelta(hours=48) else 1
    reward = DAILY_REWARD + (streak - 1) * 10
    reward = min(reward, 200)

    db.add_balance(user_id, reward)
    db.update_user(user_id, last_daily=now.isoformat(), daily_streak=streak)

    await update.message.reply_text(
        f"🎁 Ежедневный бонус: +{reward} монет!\n"
        f"🔥 Стрик: {streak} дней\n"
        f"💰 Баланс: {db.get_balance(user_id)}"
    )
    await check_quest(user_id, "daily_3")

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.top_users(10)
    if not users:
        await update.message.reply_text("Пока никого.")
        return
    lines = ["🏆 **Топ-10:**\n"]
    for i, (uid, fname, uname, bal) in enumerate(users, 1):
        name = fname or uname or f"Игрок{uid}"
        lines.append(f"{i}. {name} — {bal}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        if not context.args or not context.args[0].isdigit():
            await update.message.reply_text("Укажите сумму: /pay 50 (ответом)")
            return
        amount = int(context.args[0])
    else:
        if len(context.args) < 2 or not context.args[1].isdigit():
            await update.message.reply_text("Использование: /pay @юзер сумма")
            return
        target_name = context.args[0].lstrip('@')
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, target_name)
            target = member.user
        except Exception:
            await update.message.reply_text("Пользователь не найден.")
            return
        amount = int(context.args[1])

    sender_id = update.effective_user.id
    if target.id == sender_id:
        await update.message.reply_text("Нельзя себе.")
        return
    if amount <= 0:
        await update.message.reply_text("Сумма должна быть положительной.")
        return
    if db.get_balance(sender_id) < amount:
        await update.message.reply_text("❌ Недостаточно монет.")
        return

    db.add_balance(sender_id, -amount)
    db.add_balance(target.id, amount)
    await update.message.reply_text(
        f"💸 {mention(update.effective_user)} → {mention(target)}: **{amount}**",
        parse_mode=ParseMode.MARKDOWN
    )

# ---- Магазин ----

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["🛒 **Магазин:**\n"]
    for item_id, (name, price, desc) in SHOP_ITEMS.items():
        lines.append(f"`{item_id}` — {name} ({price} монет)\n    _{desc}_")
    lines.append("\nКупить: /buy ID")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /buy ID товара")
        return
    item_id = context.args[0].lower()
    if item_id not in SHOP_ITEMS:
        await update.message.reply_text("❌ Нет такого товара.")
        return

    name, price, desc = SHOP_ITEMS[item_id]
    user_id = update.effective_user.id
    if db.get_balance(user_id) < price:
        await update.message.reply_text(f"❌ Нужно {price} монет.")
        return

    db.add_balance(user_id, -price)
    user = db.get_user(user_id)
    inv = (user[8] or "").split(",")
    inv = [i for i in inv if i]
    inv.append(item_id)
    db.update_user(user_id, inventory=",".join(inv))

    await update.message.reply_text(f"✅ Куплено: {name}\n💰 Осталось: {db.get_balance(user_id)}")

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    data = db.get_user(user.id)
    inv = (data[8] or "").split(",")
    inv = [i for i in inv if i]
    if not inv:
        await update.message.reply_text("🎒 Инвентарь пуст.")
        return
    lines = [f"🎒 **Инвентарь {user.first_name}:**\n"]
    for item_id in inv:
        if item_id in SHOP_ITEMS:
            lines.append(f"• {SHOP_ITEMS[item_id][0]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def quests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    progress = json.loads(user[12] or '{}')
    lines = ["📜 **Квесты:**\n"]
    for qid, (desc, target, reward) in QUESTS.items():
        cur = progress.get(qid, 0)
        status = "✅" if cur >= target else "⏳"
        lines.append(f"{status} {desc}\n    {cur}/{target} | +{reward} монет")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ==================== RP-ДЕЙСТВИЯ ====================

def make_rp_handler(action_key: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await send_rp(update, context, action_key)
    return handler

# ==================== ОТНОШЕНИЯ / ПРОФИЛЬ ====================

async def marry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actor = update.effective_user
    user = db.get_user(actor.id)
    if user[5]:
        await update.message.reply_text("💔 Вы уже в браке. /divorce.")
        return

    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        name = context.args[0].lstrip('@')
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, name)
            target = member.user
        except Exception:
            pass

    if not target:
        await update.message.reply_text("Укажите @юзера или ответьте на сообщение.")
        return
    if target.id == actor.id:
        await update.message.reply_text("Нельзя на себе!")
        return

    target_data = db.get_user(target.id)
    if target_data[5]:
        await update.message.reply_text("Этот пользователь уже в браке.")
        return

    db.update_user(actor.id, married_to=target.id)
    db.update_user(target.id, married_to=actor.id)
    await update.message.reply_text(
        f"💍 {mention(actor)} и {mention(target)} теперь в браке! 🎉",
        parse_mode=ParseMode.MARKDOWN
    )

async def divorce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actor = update.effective_user
    user = db.get_user(actor.id)
    if not user[5]:
        await update.message.reply_text("Вы не в браке.")
        return
    partner_id = user[5]
    db.update_user(actor.id, married_to=None)
    db.update_user(partner_id, married_to=None)
    await update.message.reply_text("💔 Брак расторгнут.")

async def couple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    actor = update.effective_user
    user = db.get_user(actor.id)
    if not user[5]:
        await update.message.reply_text("Вы не в браке. /marry @юзер")
        return
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user[5])
        partner = member.user
        await update.message.reply_text(
            f"💞 {mention(actor)} + {mention(partner)} = ❤️",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        await update.message.reply_text(f"💞 Ваш партнёр: ID {user[5]}")

async def bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /bio текст")
        return
    text = " ".join(context.args)[:200]
    db.update_user(update.effective_user.id, bio=text)
    await update.message.reply_text("✅ Био сохранено.")

async def title_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    inv = (db.get_user(user_id)[8] or "").split(",")
    if "vip" not in inv and "custom_title" not in inv:
        await update.message.reply_text("❌ Нужен VIP или «Своя приписка» из /shop.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /title текст")
        return
    text = " ".join(context.args)[:30]
    db.update_user(user_id, title=text)
    await update.message.reply_text(f"✅ Приписка: {text}")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user

    data = db.get_user(user.id)
    partner_text = "нет"
    if data[5]:
        try:
            m = await context.bot.get_chat_member(update.effective_chat.id, data[5])
            partner_text = m.user.first_name
        except Exception:
            partner_text = f"ID {data[5]}"

    title = f" [{data[7]}]" if data[7] else ""
    bio_text = data[6] or "—"
    inv = (data[8] or "").split(",")
    inv = [i for i in inv if i]

    text = (
        f"👤 **Профиль {user.first_name}**{title}\n"
        f"🆔 `{user.id}`\n"
        f"💰 Баланс: **{data[3]}** монет\n"
        f"⚠️ Варнов: {data[4]}\n"
        f"💞 Партнёр: {partner_text}\n"
        f"📝 Био: {bio_text}\n"
        f"🎮 Игр: {data[9]} | 🏆 Побед: {data[10]}\n"
        f"🔥 Дейли-стрик: {data[11] or 0}\n"
        f"🎒 Предметов: {len(inv)}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    data = db.get_user(user.id)
    await update.message.reply_text(
        f"📊 **Статистика {user.first_name}**\n"
        f"🎮 Сыграно: {data[9]}\n"
        f"🏆 Побед: {data[10]}\n"
        f"📈 Процент побед: {(data[10]/data[9]*100) if data[9] else 0:.1f}%\n"
        f"💰 Монет: {data[3]}",
        parse_mode=ParseMode.MARKDOWN
    )

# ==================== МОДЕРАЦИЯ ====================

async def is_admin(update, context) -> bool:
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение пользователя.")
        return

    target = update.message.reply_to_message.from_user
    duration = 60  # секунд по умолчанию
    if context.args:
        arg = context.args[0].lower()
        if arg.endswith("m"):
            duration = int(arg[:-1]) * 60
        elif arg.endswith("h"):
            duration = int(arg[:-1]) * 3600
        elif arg.endswith("d"):
            duration = int(arg[:-1]) * 86400
        elif arg.isdigit():
            duration = int(arg)

    until = datetime.now() + timedelta(seconds=duration)
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await update.message.reply_text(
            f"🔇 {mention(target)} замучен на {duration // 60} мин.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True
            )
        )
        await update.message.reply_text(f"🔊 {mention(target)} размучен.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"👢 {mention(target)} кикнут.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение.")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🚫 {mention(target)} забанен.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not update.message.reply_to_message and not context.args:
        await update.message.reply_text("Ответьте на сообщение или /unban ID")
        return
    try:
        if update.message.reply_to_message:
            target_id = update.message.reply_to_message.from_user.id
        else:
            target_id = int(context.args[0])
        await context.bot.unban_chat_member(update.effective_chat.id, target_id)
        await update.message.reply_text(f"✅ Разбанен: {target_id}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение.")
        return
    target = update.message.reply_to_message.from_user
    db.get_user(target.id)
    cur = db.get_user(target.id)[4]
    db.update_user(target.id, warns=cur + 1)
    new_warns = cur + 1
    await update.message.reply_text(
        f"⚠️ {mention(target)} получил предупреждение ({new_warns}/3)",
        parse_mode=ParseMode.MARKDOWN
    )
    if new_warns >= 3:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, target.id)
            await update.message.reply_text(f"🚫 {mention(target)} забанен за 3 варна.", parse_mode=ParseMode.MARKDOWN)
            db.update_user(target.id, warns=0)
        except Exception as e:
            await update.message.reply_text(f"Ошибка бана: {e}")

async def unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if not update.message.reply_to_message:
        return
    target = update.message.reply_to_message.from_user
    cur = db.get_user(target.id)[4]
    if cur > 0:
        db.update_user(target.id, warns=cur - 1)
    await update.message.reply_text(f"✅ Снят варн. Осталось: {max(0, cur-1)}")

async def warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
    cur = db.get_user(user.id)[4]
    await update.message.reply_text(f"⚠️ Варнов у {user.first_name}: {cur}")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = db.get_chat(update.effective_chat.id)
    if not chat[2]:
        await update.message.reply_text("Правила не заданы.")
        return
    await update.message.reply_text(f"📜 **Правила чата:**\n\n{chat[2]}", parse_mode=ParseMode.MARKDOWN)

async def setrules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /setrules текст")
        return
    text = " ".join(context.args)[:1000]
    db.update_chat(update.effective_chat.id, rules=text)
    await update.message.reply_text("✅ Правила сохранены.")

async def welcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        await update.message.reply_text("❌ Только для админов.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /welcome текст\nИспользуйте {name} для имени.")
        return
    text = " ".join(context.args)[:500]
    db.update_chat(update.effective_chat.id, welcome=text)
    await update.message.reply_text("✅ Приветствие сохранено.")

async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        chat = db.get_chat(update.effective_chat.id)
        text = chat[1] or "👋 Добро пожаловать, {name}!"
        text = text.replace("{name}", mention(member))
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(f"👋 Добро пожаловать, {member.first_name}!")

# ==================== ЗАМЕТКИ ====================

async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /save имя текст")
        return
    name = context.args[0].lower()
    content = " ".join(context.args[1:])
    chat_id = update.effective_chat.id
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO notes(chat_id, name, content) VALUES(?, ?, ?)",
            (chat_id, name, content)
        )
        conn.commit()
    await update.message.reply_text(f"✅ Заметка `{name}` сохранена.", parse_mode=ParseMode.MARKDOWN)

async def get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /get имя")
        return
    name = context.args[0].lower()
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT content FROM notes WHERE chat_id=? AND name=?", (update.effective_chat.id, name))
        row = cur.fetchone()
    if row:
        await update.message.reply_text(f"📝 {row[0]}")
    else:
        await update.message.reply_text("Заметка не найдена.")

async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM notes WHERE chat_id=?", (update.effective_chat.id,))
        rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Заметок нет.")
        return
    names = ", ".join(f"`{r[0]}`" for r in rows)
    await update.message.reply_text(f"📝 Заметки: {names}", parse_mode=ParseMode.MARKDOWN)

async def del_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /del имя")
        return
    name = context.args[0].lower()
    with db.lock, db.sqlite3.connect(db.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE chat_id=? AND name=?", (update.effective_chat.id, name))
        conn.commit()
    await update.message.reply_text("🗑 Удалено.")

# ==================== УТИЛИТЫ ====================

async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"😄 {random.choice(JOKES)}")

async def fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://uselessfacts.jsph.pl/random.json?language=en",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                await update.message.reply_text(f"🧠 {data['text']}")
    except Exception:
        await update.message.reply_text("Не удалось получить факт.")

async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /weather Москва")
        return
    city = " ".join(context.args)
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://wttr.in/{city}?format=j1"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                cur = data["current_condition"][0]
                text = (
                    f"🌤 **Погода в {city}:**\n"
                    f"🌡 Температура: {cur['temp_C']}°C (ощущается {cur['FeelsLikeC']}°C)\n"
                    f"☁️ {cur['weatherDesc'][0]['value']}\n"
                    f"💧 Влажность: {cur['humidity']}%\n"
                    f"💨 Ветер: {cur['windspeedKmph']} км/ч"
                )
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("Не удалось получить погоду.")

async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message and not context.args:
        await update.message.reply_text("Ответьте на сообщение или: /tr текст")
        return
    if update.message.reply_to_message:
        text = update.message.reply_to_message.text or ""
    else:
        text = " ".join(context.args)

    if not text:
        await update.message.reply_text("Пусто.")
        return

    # Простейший перевод через Google Translate (неофициальный endpoint)
    try:
        async with aiohttp.ClientSession() as session:
            params = {"client": "gtx", "sl": "auto", "tl": "ru" if any(c.isascii() for c in text) else "en", "dt": "t", "q": text}
            async with session.get(
                "https://translate.googleapis.com/translate_a/single",
                params=params, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                data = await resp.json()
                translated = "".join(seg[0] for seg in data[0])
                await update.message.reply_text(f"🌐 {translated}")
    except Exception:
        await update.message.reply_text("Ошибка перевода.")

async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /remind 10m текст\n(m = минуты, h = часы)")
        return
    time_str = context.args[0].lower()
    text = " ".join(context.args[1:])

    try:
        if time_str.endswith("m"):
            seconds = int(time_str[:-1]) * 60
        elif time_str.endswith("h"):
            seconds = int(time_str[:-1]) * 3600
        elif time_str.endswith("s"):
            seconds = int(time_str[:-1])
        else:
            seconds = int(time_str)
    except ValueError:
        await update.message.reply_text("Неверный формат времени.")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_mention = mention(update.effective_user)

    async def reminder_task():
        await asyncio.sleep(seconds)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ {user_mention}, напоминание: {text}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Reminder failed: {e}")

    task = asyncio.create_task(reminder_task())
    await update.message.reply_text(f"✅ Напомню через {time_str}.")

# ==================== ЗАПУСК ====================

def run_bot():
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())

    db.init_db()
    application = Application.builder().token(TOKEN).build()
    
    # Базовые
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("id", id_command))

    # Игры
    application.add_handler(CommandHandler("roll", roll))
    application.add_handler(CommandHandler("coin", coin))
    application.add_handler(CommandHandler("slot", slot))
    application.add_handler(CommandHandler("dice", dice_game))
    application.add_handler(CommandHandler("guess", guess))
    application.add_handler(CommandHandler("stopguess", stop_guess))
    application.add_handler(CommandHandler("duel", duel))
    application.add_handler(CommandHandler("quiz", quiz))
    application.add_handler(CommandHandler("trivia", trivia))

    # Экономика
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("daily", daily))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("pay", pay))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("inventory", inventory))
    application.add_handler(CommandHandler("quests", quests))

    # RP — все действия из конфига
    for action_key in RP_ACTIONS.keys():
        application.add_handler(CommandHandler(action_key, make_rp_handler(action_key)))

    # Отношения / профиль
    application.add_handler(CommandHandler("marry", marry))
    application.add_handler(CommandHandler("divorce", divorce))
    application.add_handler(CommandHandler("couple", couple))
    application.add_handler(CommandHandler("bio", bio))
    application.add_handler(CommandHandler("title", title_cmd))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("stats", stats_cmd))

    # Модерация
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("unmute", unmute))
    application.add_handler(CommandHandler("kick", kick))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("warn", warn))
    application.add_handler(CommandHandler("unwarn", unwarn))
    application.add_handler(CommandHandler("warns", warns))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("setrules", setrules))
    application.add_handler(CommandHandler("welcome", welcome_cmd))

    # Заметки
    application.add_handler(CommandHandler("save", save_note))
    application.add_handler(CommandHandler("get", get_note))
    application.add_handler(CommandHandler("notes", list_notes))
    application.add_handler(CommandHandler("del", del_note))

    # Утилиты
    application.add_handler(CommandHandler("joke", joke))
    application.add_handler(CommandHandler("fact", fact))
    application.add_handler(CommandHandler("weather", weather))
    application.add_handler(CommandHandler("tr", translate))
    application.add_handler(CommandHandler("remind", remind))

    # Callback (дуэль)
    application.add_handler(CallbackQueryHandler(duel_callback, pattern=r"^duel_"))

    # Новые участники
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))

    # Текстовые обработчики (числа → guess / quiz)
    async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await handle_guess(update, context)
        await handle_quiz(update, context)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info("🚀 Бот запущен!")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        stop_signals=None
    )

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Flask на порту {port}")
    flask_app.run(host="0.0.0.0", port=port)
