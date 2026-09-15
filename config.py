import os

TELEGRAM.TOKEN = os.environ.get("8655220760:AAGTs6pnWRl9vQAG0IJhrfLDtmohZmXQotE")
if not TOKEN:
    raise ValueError("Установите TELEGRAM_TOKEN в переменных окружения")
    
# Стоимости и награды
DAILY_REWARD = 50
QUIZ_REWARD = 15
GUESS_REWARD = 30
DUEL_REWARD = 25
DICE_REWARD = 20
SLOT_COST = 10
SLOT_JACKPOT = 100
SLOT_PAIR = 20

# Магазин: {item_id: (название, цена, описание)}
SHOP_ITEMS = {
    "vip": ("⭐ VIP-статус", 500, "Особый статус в профиле"),
    "custom_title": ("📛 Своя приписка", 300, "Добавить приписку рядом с именем"),
    "lucky_charm": ("🍀 Талисман удачи", 200, "+5% шанс выигрыша в казино (пассивно)"),
    "shield": ("🛡 Щит", 400, "Защита от одного мута"),
    "rose": ("🌹 Роза", 100, "Подарить розу другому пользователю"),
}

# Квесты: {quest_id: (описание, цель, награда)}
QUESTS = {
    "play_5": ("Сыграть 5 раз в любые игры", 5, 100),
    "win_3": ("Выиграть 3 раза", 3, 150),
    "daily_3": ("Забрать ежедневный бонус 3 раза", 3, 200),
}

# RP-действия: {команда: (эмодзи, текст, url_api)}
# url_api — ссылка на аниме-гифку (используем nekos.best)
RP_ACTIONS = {
    "hug":    ("🤗", "обнимает",           "https://nekos.best/api/v2/hug"),
    "kiss":   ("😘", "целует",             "https://nekos.best/api/v2/kiss"),
    "slap":   ("👋", "шлёпает",            "https://nekos.best/api/v2/slap"),
    "pat":    ("🥰", "гладит по голове",   "https://nekos.best/api/v2/pat"),
    "kick":   ("🦵", "пинает",             "https://nekos.best/api/v2/kick"),
    "punch":  ("👊", "бьёт",               "https://nekos.best/api/v2/punch"),
    "bite":   ("😬", "кусает",             "https://nekos.best/api/v2/bite"),
    "lick":   ("👅", "лижет",              "https://nekos.best/api/v2/lick"),
    "cuddle": ("🫂", "прижимается к",      "https://nekos.best/api/v2/cuddle"),
    "poke":   ("👉", "тыкает",             "https://nekos.best/api/v2/poke"),
    "wave":   ("👋", "машет",              "https://nekos.best/api/v2/wave"),
    "highfive": ("🙌", "даёт пять",        "https://nekos.best/api/v2/highfive"),
    "bonk":   ("🔨", "стукает",            "https://nekos.best/api/v2/bonk"),
    "yeet":   ("🚀", "швыряет",            "https://nekos.best/api/v2/yeet"),
    "blush":  ("😳", "краснеет рядом с",   "https://nekos.best/api/v2/blush"),
    "smile":  ("😊", "улыбается",          "https://nekos.best/api/v2/smile"),
    "happy":  ("😄", "радуется за",        "https://nekos.best/api/v2/happy"),
    "wink":   ("😉", "подмигивает",        "https://nekos.best/api/v2/wink"),
    "dance":  ("💃", "танцует с",          "https://nekos.best/api/v2/dance"),
    "cry":    ("😭", "плачет рядом с",     "https://nekos.best/api/v2/cry"),
    "pout":   ("😤", "дуется на",          "https://nekos.best/api/v2/pout"),
}
