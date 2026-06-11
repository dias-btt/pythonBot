import asyncio
import json
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
import numpy as np
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from openai import OpenAI
from maliks import MALIKS
from naruto_team import register_naruto_team
from naruto_duel import register_naruto_duel
from db import add_sticker, sticker_exists
from dotenv import load_dotenv
import os


# =========================
# 🔑 CONFIG
# =========================
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
client = OpenAI(api_key=OPENAI_API_KEY)
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
register_naruto_team(dp)
register_naruto_duel(dp)

# =========================
# 🧠 LOAD MEMORY
# =========================
with open("result.json", "r", encoding="utf-8") as f:
    data = json.load(f)
chat_memory = [
    m.strip()
    for m in data["messages"]
    if isinstance(m, str) and len(m.strip()) > 2
]

from db import (
    ensure_user,
    add_score,
    top_users,
    get_score,
    get_last_drink,
    update_last_drink,
    get_random_sticker,
    get_players_with_scores,
    reset_all_scores,
)
DRINKS = [
    ("водки «Наша»", 0.1, 0.7, 10),
    ("виски", 0.05, 0.5, 8),
    ("рома", 0.05, 0.5, 6),
    ("текилы", 0.05, 0.35, 9),
    ("джина", 0.05, 0.4, 7),
    ("пива", 0.3, 3.0, 3),
    ("сидра", 0.25, 1.5, 4),
    ("соджу", 0.05, 0.4, 2),
    ("шампанского", 0.1, 0.6, 5),
    ("абсента", 0.03, 0.15, 12),
    ("коньяка", 0.05, 0.4, -5),
    ("палёной водки", 0.05, 0.5, -10),
    ("коктейля «Малик Special»", 0.15, 0.5, 15),
    ("коктейля «Алматы Ночь»", 0.2, 0.6, 11),
    ("коктейля «За дружбу»", 0.1, 0.4, 8),
    ("кваса (но ты думал пиво)", 0.5, 1.0, 1),
    ("курмыса с перцем", 0.2, 0.8, 6),
    ("араки", 0.05, 0.3, 7),
    ("самогона деда", 0.1, 0.6, -8),
    ("энергетика с водкой", 0.15, 0.35, 13),
]
STRONG_DRINKS = [d for d in DRINKS if d[3] >= 6]
LIGHT_DRINKS = [d for d in DRINKS if d[3] <= 4 and d[3] >= 0]
COOLDOWN_SECONDS = 60 * 60  # 1 hour

DRINK_MODES = {
    "zal": {
        "emoji": "🔫",
        "name": "Залп",
        "pool": STRONG_DRINKS,
        "amount_scale": 0.25,
        "points_scale": 2.0,
        "desc": "Мало, но мощно. Только крепкое.",
    },
    "tyazhelo": {
        "emoji": "🪨",
        "name": "Тяжело",
        "pool": DRINKS,
        "amount_scale": 1.6,
        "points_scale": 1.3,
        "desc": "Больше литров — больше страданий.",
    },
    "legko": {
        "emoji": "🫧",
        "name": "Легко",
        "pool": LIGHT_DRINKS or [("пива", 0.3, 1.5, 3)],
        "amount_scale": 0.8,
        "points_scale": 0.5,
        "desc": "Только слабоалкогольное, для слабаков.",
    },
    "ruletka": {
        "emoji": "🎰",
        "name": "Рулетка",
        "pool": DRINKS,
        "amount_scale": 1.0,
        "points_scale": 1.0,
        "event_chance": 0.45,
        "desc": "Шанс на джекпот или полный провал.",
    },
}

DRUNK_EVENTS = [
    ("🎰 ДЖЕКПОТ!", 3.0, "Сегодня фортуна на твоей стороне!"),
    ("🔥 ЗАЛП УДАЧИ!", 2.0, "Горло горит, но баллы капают!"),
    ("🍀 Малик одобряет", 1.5, "Малик кивнул — ты молодец."),
    ("🤝 За компанию", 1.25, "Чат с тобой — +25% за вайб."),
    ("🎭 Философ", 1.0, "Ты пьяный философ. Мудрость +100, баллы как есть."),
    ("😵 Похмелье", 0.5, "Утро будет жёстким..."),
    ("🤮 Рвота", -0.5, "Лучше бы не пил..."),
    ("💀 Blackout", 0.0, "Ты ничего не помнишь. Баллы обнулились за этот залп."),
    ("🚔 ГАИ остановил", -0.3, "Дуло в лицо — минус баллы."),
    ("🎤 Караоке", 1.2, "Ты завёл чат песней «Жанна»."),
]

DRUNK_REACTIONS = [
    "Брат, ты уже не трезвый. Это факт.",
    "Малик бы гордился... наверное.",
    "Ещё один — и ты станешь философом.",
    "Чат чувствует запах перегара через экран.",
    "Ты сейчас на том уровне, где всё кажется хорошей идеей.",
    "Алкаш года — это ты через пару залпов.",
    "Кто-то позови такси. Или нет. Как хочешь.",
    "Твоя печень только что написала заявление на увольнение.",
    "Нормально, завтра не вспомнишь.",
    "Это был залп чести. Или отчаяния. Хз.",
    "Главное — не писать бывшей. Пока.",
    "Уровень: «я тебя уважаю, брат».",
]

DRUNK_TITLES = [
    (0, "🧊 Трезвяк"),
    (100, "🍺 Начинающий"),
    (300, "🥴 Лёгкий намёк"),
    (600, "🔥 Завсегдатай бара"),
    (1000, "👑 Король вечеринки"),
    (1500, "🎭 Легенда чата"),
    (2500, "💀 Алкаш года"),
    (4000, "🌌 Мифический перегар"),
    (6000, "🛐 Бог алкоголя"),
]


def _drunk_title(score: int) -> str:
    title = DRUNK_TITLES[0][1]
    for threshold, t in DRUNK_TITLES:
        if score >= threshold:
            title = t
    return title


def _cooldown_text(remaining: int) -> str:
    minutes = remaining // 60
    seconds = remaining % 60
    return f"{minutes} мин {seconds} сек."


def _format_modes_help() -> str:
    lines = ["<b>Режимы:</b>"]
    for key, mode in DRINK_MODES.items():
        lines.append(
            f"{mode['emoji']} <code>/alyp_koyaik {key}</code> — "
            f"{mode['name']}: {mode['desc']}"
        )
    lines.append("📊 <code>/alyp_koyaik stat</code> — статистика без выпивки")
    lines.append("⏳ <code>/alyp_koyaik poka</code> — таймер до следующей бутылки")
    return "\n".join(lines)
# =========================
# 🎭 STYLE SYSTEM
# =========================
STYLE_PROMPT = """
You are a Telegram group chat member.
You speak casually, like a chaotic friend group.
Style rules:
- use slang like: "баля", "нууу", "че", "пон", "шоль"
- sometimes be chaotic but still understandable
- short-medium messages
- react emotionally like a human
- never be formal
- sometimes reference group memory naturally
Do NOT be an assistant. Be a group member.
"""

# =========================
# 🔥 POEBAT ROAST SYSTEM
# =========================
POEBAT_PROMPT = """
Ты злой, токсичный, но очень смешной участник чата.
Твоя задача — жёстко и весело **поебать** человека.
Используй максимально дерзкий, пьяный, групповой сленг.
Можно троллить внешность, характер, поведение, прошлые косяки — всё что угодно.
Коротко, жёстко, смешно. Максимум 2-3 предложения.
"""
# =========================
# 🧠 RETRIEVE CONTEXT
# =========================
def get_context(query: str, k=6):
    return random.sample(chat_memory, k=min(k, len(chat_memory)))
# =========================
# 🤖 GPT ENGINE
# =========================
def gpt_reply(user_text: str):
    context = get_context(user_text)
    messages = [
        {"role": "system", "content": STYLE_PROMPT},
        {
            "role": "system",
            "content": "Here are past group messages for context:\n"
                       + "\n".join(context)
        },
        {"role": "user", "content": user_text}
    ]
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.9
    )
    return response.choices[0].message.content
# =========================
# 🤖 COMMANDS
# =========================
@dp.message(Command("che_malik"))
async def answer(message: types.Message, command: CommandObject):
    text = (command.args or "").strip()
   
    if not text:
        await message.reply("Напиши текст после /че_малик")
        return
    roll = random.random()
   
    if roll < 0.2:
        await message.reply("Токены мне еще потрать, пшел ты")
        return
    elif roll < 0.6:
        sticker = get_random_sticker()
        await message.answer_sticker(sticker)
        return
   
    reply = gpt_reply(text)
    await message.reply(reply)

@dp.message(Command("poebat"))
async def poebat(message: types.Message, command: CommandObject):
    user = message.from_user
    
    # Get target user
    target = None
    
    # 1. If replied to someone
    if message.reply_to_message:
        target = message.reply_to_message.from_user
    # 2. If mentioned username after command
    elif command.args:
        args = command.args.strip()
        # Try to find user by username
        if args.startswith('@'):
            username = args[1:].lower()
            # For simplicity we can just use the text as name
            target_name = args
        else:
            target_name = args
    else:
        # Random victim if no target
        target = user  # or make it random member, but harder
    
    if message.reply_to_message:
        target_name = target.full_name or target.username or "анон"
    elif not target_name:
        target_name = user.full_name or user.username or "ты"
    
    # Special cases
    if target and target.id == bot.id:
        await message.reply("Я себя поебать не дам, иди нахуй 😂")
        return
    
    if target and target.id == user.id:
        roast = random.choice([
            "Сам себя поебал? Молодец, прогресс есть 🔥",
            "Брат, у тебя настолько плохо, что даже я тебя жалеть начал...",
            "Поебать самого себя — это уже новый уровень депрессии"
        ])
        await message.reply(roast)
        return

    # Generate savage roast
    try:
        roast_text = gpt_reply_poebat(target_name)
        await message.reply(f"🔥 <b>{target_name}</b>, получай:\n\n{roast_text}")
    except Exception as e:
        await message.reply(f"Не смог поебать {target_name}, он слишком сильный 💀")


# Separate function for better roasts
def gpt_reply_poebat(target_name: str):
    messages = [
        {"role": "system", "content": POEBAT_PROMPT},
        {"role": "system", "content": "Вот стиль чата для понимания тона:\n" + "\n".join(random.sample(chat_memory, 5))},
        {"role": "user", "content": f"Жёстко поеби {target_name}"}
    ]
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=1.0,      # more chaotic
        max_tokens=300
    )
    return response.choices[0].message.content.strip()

# =========================
# 👑 МАЛИК ДНЯ + ГЕЙ ДНЯ
# =========================
@dp.message(Command("kto_segodnya"))
async def kto_segodnya(message: types.Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.reply("Это работает только в группе, брат")
        return

    try:
        # Получаем администраторов (обычно самые активные)
        admins = await bot.get_chat_administrators(message.chat.id)
        users = [admin.user for admin in admins if not admin.user.is_bot]
        
        if len(users) < 2:
            await message.reply("Мало народу, чтобы раздавать титулы 😂")
            return

        # Выбираем двух разных людей
        malik = random.choice(users)
        gay = random.choice([u for u in users if u.id != malik.id])

        malik_name = malik.first_name or malik.username or "Малик"
        gay_name = gay.first_name or gay.username or "Гей"

        # Красивый вывод
        text = f"""
🎉 <b>СЕГОДНЯ В ЧАТЕ:</b> 🎉

👑 <b>МАЛИК ДНЯ:</b> {malik_name}
🔥 Король, легенда, бог вечеринки

🏳️‍🌈 <b>ГЕЙ ДНЯ:</b> {gay_name}
💅 Поздравляем, ты сегодня особенно сияешь!

😂 Не согласен? Пиши /kto_segodnya ещё раз
        """

        await message.reply(text)

    except Exception as e:
        # Fallback — если не получилось взять админов
        await message.reply(
            "🎲 <b>МАЛИК ДНЯ:</b> " + random.choice(["Ты", "Малик", message.from_user.first_name, "Кто-то"]) +
            "\n\n🏳️‍🌈 <b>ГЕЙ ДНЯ:</b> " + random.choice(["Ты", message.from_user.first_name, "Твой сосед", "Я", "Бот"])
        )


@dp.message(Command("info"))
async def info(message: types.Message):
    await message.reply(
        f"""
🔥 GPT Group AI
📊 messages: {len(chat_memory)}
🧠 model: GPT-4o-mini
🎭 mode: group personality
"""
    )


@dp.message(Command("malik"))
async def malik_today(message: types.Message):
    await message.reply(
        f"🎲 Какой Малик ты сегодня?\n\n{random.choice(MALIKS)}"
    )


@dp.message(Command("do_malika"))
async def until_malik(message: types.Message):
    today = date.today()
    malik_day = date(today.year, 6, 23)
    if today > malik_day:
        malik_day = date(today.year + 1, 6, 23)
    days_left = (malik_day - today).days
    if days_left == 0:
        text = "🚀 МАЛИК ПРИЕХАЛ СЕГОДНЯ!"
    elif days_left == 1:
        text = "🔥 До приезда Малика остался 1 день!"
    else:
        text = f"⏳ До приезда Малика осталось {days_left} дней."
    await message.reply(text)


# =========================
# 🛢️ ВАХТА МАЛИКА
# =========================
VAXTA_START = date(2026, 6, 11)
VAXTA_PERIOD_DAYS = 21

MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
    "май": 5, "июнь": 6, "июль": 7, "август": 8,
    "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12,
}

MONTH_DISPLAY = {
    1: "Января", 2: "Февраля", 3: "Марта", 4: "Апреля",
    5: "Мая", 6: "Июня", 7: "Июля", 8: "Августа",
    9: "Сентября", 10: "Октября", 11: "Ноября", 12: "Декабря",
}


def parse_vaxta_date(text: str):
    text = text.strip()
    match = re.match(r"^(\d{1,2})\s+([а-яёa-z]+)(?:\s+(\d{4}))?$", text, re.IGNORECASE)
    if not match:
        return None

    day = int(match.group(1))
    month_name = match.group(2).lower()
    year = int(match.group(3)) if match.group(3) else date.today().year

    month = MONTHS_RU.get(month_name)
    if not month:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


def malik_vaxta_status(target_date):
    days_since_start = (target_date - VAXTA_START).days
    period = days_since_start // VAXTA_PERIOD_DAYS
    if period % 2 == 0:
        return "ауылда"
    return "на Вахте"


@dp.message(Command("vaxta"))
async def vaxta(message: types.Message, command: CommandObject):
    args = (command.args or "").strip()
    if not args:
        await message.reply("Напиши дату после /vaxta, например: /vaxta 30 Июня")
        return

    target = parse_vaxta_date(args)
    if not target:
        await message.reply("Не понял дату. Пример: /vaxta 30 Июня")
        return

    status = malik_vaxta_status(target)
    day = target.day
    month = MONTH_DISPLAY[target.month]
    await message.reply(f"{day} {month} Малик {status}")


# =========================
# 🎂 ВОЗРАСТ МАЛИКА
# =========================
MALIK_BIRTH = datetime(2002, 10, 3, 9, 0, 0)


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n = n % 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def malik_age_parts(now: datetime | None = None):
    now = now or datetime.now()
    birth = MALIK_BIRTH

    years = now.year - birth.year
    if (now.month, now.day, now.hour, now.minute, now.second) < (
        birth.month, birth.day, birth.hour, birth.minute, birth.second,
    ):
        years -= 1

    last_bday = datetime(now.year, birth.month, birth.day, birth.hour, birth.minute, birth.second)
    if last_bday > now:
        last_bday = datetime(now.year - 1, birth.month, birth.day, birth.hour, birth.minute, birth.second)

    delta = now - last_bday
    seconds = delta.seconds
    return years, delta.days, seconds // 3600, (seconds % 3600) // 60, seconds % 60


@dp.message(Command("malik_let"))
async def malik_let(message: types.Message):
    years, days, hours, minutes, seconds = malik_age_parts()
    text = (
        f"🎂 <b>Малику сегодня:</b>\n\n"
        f"{years} {_ru_plural(years, 'год', 'года', 'лет')}, "
        f"{days} {_ru_plural(days, 'день', 'дня', 'дней')}, "
        f"{hours} {_ru_plural(hours, 'час', 'часа', 'часов')}, "
        f"{minutes} {_ru_plural(minutes, 'минута', 'минуты', 'минут')}, "
        f"{seconds} {_ru_plural(seconds, 'секунда', 'секунды', 'секунд')}"
    )
    await message.reply(text)


@dp.message(Command("alyp_koyaik"))
async def alyp_koyaiyk(message: types.Message, command: CommandObject):
    user = message.from_user
    ensure_user(user.id, user.username or user.first_name)

    arg = (command.args or "").strip().lower()
    if arg in ("help", "?", "режимы", "rezhimy"):
        await message.reply(
            "🍻 <b>АЛЫП ҚОЯЙЫҚ</b> — пей и копи баллы алкаша!\n\n"
            f"{_format_modes_help()}\n\n"
            "Пример: <code>/alyp_koyaik zal</code>"
        )
        return

    now = int(time.time())
    last_drink = get_last_drink(user.id)
    remaining = COOLDOWN_SECONDS - (now - last_drink)

    if arg in ("stat", "stats", "стат", "стата"):
        total = get_score(user.id)
        title = _drunk_title(total)
        rank_text = ""
        rating = top_users(50)
        for i, (name, score) in enumerate(rating, start=1):
            if name == (user.username or user.first_name):
                rank_text = f"📍 Место в рейтинге: <b>{i}</b>\n"
                break
        await message.reply(
            f"📊 <b>Твоя статистика</b>\n\n"
            f"{title}\n"
            f"🏆 Баллов: <b>{total}</b>\n"
            f"{rank_text}"
            f"{'⏳ Кулдаун: ' + _cooldown_text(remaining) if remaining > 0 else '✅ Можешь пить прямо сейчас!'}"
        )
        return

    if arg in ("poka", "timer", "кд", "cd"):
        if remaining > 0:
            await message.reply(f"⏳ Следующая бутылка через {_cooldown_text(remaining)}")
        else:
            await message.reply("✅ Кулдаун прошёл — жми /alyp_koyaik и пей!")
        return

    if remaining > 0:
        await message.reply(
            f"🚫 Ты уже пил.\n\n"
            f"Следующая бутылка через {_cooldown_text(remaining)}\n"
            f"💡 <code>/alyp_koyaik poka</code> — проверить таймер"
        )
        return

    mode = DRINK_MODES.get(arg)
    pool = mode["pool"] if mode else DRINKS
    amount_scale = mode["amount_scale"] if mode else 1.0
    points_scale = mode["points_scale"] if mode else 1.0
    event_chance = mode.get("event_chance", 0.18) if mode else 0.18

    drink, min_l, max_l, mult = random.choice(pool)
    amount = round(random.uniform(min_l, max_l) * amount_scale, 2)
    amount = max(0.05, amount)
    base_points = int(amount * 100 * mult * points_scale)

    event_block = ""
    if random.random() < event_chance:
        event_name, event_mult, event_desc = random.choice(DRUNK_EVENTS)
        if event_mult == 0.0:
            base_points = 0
        else:
            base_points = int(base_points * event_mult)
        event_block = f"\n{event_name}\n<i>{event_desc}</i>\n"

    points = base_points
    add_score(user.id, points)
    update_last_drink(user.id)
    total = get_score(user.id)
    sign = "➕" if points >= 0 else "➖"
    reaction = random.choice(DRUNK_REACTIONS)
    title = _drunk_title(total)
    mode_line = f"{mode['emoji']} Режим: <b>{mode['name']}</b>\n" if mode else ""

    await message.reply(
        f"🍻 <b>АЛЫП ҚОЯЙЫҚ!</b>\n"
        f"{mode_line}"
        f"Ты выпил <b>{amount} л</b> {drink}\n"
        f"{event_block}"
        f"{sign} <b>{abs(points)}</b> баллов алкаша\n"
        f"🏆 Всего: <b>{total}</b> ({title})\n\n"
        f"💬 <i>{reaction}</i>"
    )


@dp.message(Command("alkashi"))
async def alkashi_rating(message: types.Message):
    rating = top_users()
    if not rating:
        await message.reply("Пока никто не бухал 🍺")
        return
    text = "🏆 Рейтинг алкашей\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, score) in enumerate(rating, start=1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        text += f"{medal} {name} — {score} баллов\n"
    await message.reply(text)


# =========================
# 🔄 СБРОС БАЛЛОВ АЛКАШЕЙ
# =========================
RESET_VOTE_TTL = 60 * 60  # 1 hour


@dataclass
class AlkashiResetVote:
    vote_id: str
    initiator_id: int
    initiator_name: str
    required: dict[int, str] = field(default_factory=dict)
    agreed: set[int] = field(default_factory=set)
    declined: set[int] = field(default_factory=set)
    chat_id: int = 0
    message_id: int = 0
    created_at: int = 0


_active_reset_vote: AlkashiResetVote | None = None


def _reset_vote_keyboard(vote_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Согласен", callback_data=f"ars:yes:{vote_id}"),
                InlineKeyboardButton(text="❌ Против", callback_data=f"ars:no:{vote_id}"),
            ]
        ]
    )


def _reset_vote_status(vote: AlkashiResetVote) -> str:
    total = len(vote.required)
    agreed_names = [vote.required[uid] for uid in vote.agreed if uid in vote.required]
    pending = [
        name for uid, name in vote.required.items() if uid not in vote.agreed
    ]

    lines = [
        "🗳️ <b>Голосование: сброс всех баллов алкашей</b>",
        "",
        f"Инициатор: <b>{vote.initiator_name}</b>",
        f"Прогресс: <b>{len(vote.agreed)}/{total}</b>",
        "",
    ]

    if agreed_names:
        lines.append("✅ Согласны:")
        lines.extend(f"  • {name}" for name in agreed_names)
        lines.append("")

    if pending:
        lines.append("⏳ Ждём:")
        lines.extend(f"  • {name}" for name in pending)
        lines.append("")

    lines.append("Если <b>все</b> согласны — баллы обнулятся.")
    return "\n".join(lines)


async def _finish_reset_vote(bot: Bot, vote: AlkashiResetVote, success: bool, reason: str):
    global _active_reset_vote
    _active_reset_vote = None

    text = _reset_vote_status(vote) + f"\n\n{reason}"
    try:
        await bot.edit_message_text(
            text,
            chat_id=vote.chat_id,
            message_id=vote.message_id,
            reply_markup=None,
        )
    except Exception:
        pass


@dp.message(Command("alkashi_reset"))
async def alkashi_reset_start(message: types.Message):
    global _active_reset_vote

    user = message.from_user
    players = get_players_with_scores()
    if not players:
        await message.reply("🍺 Нечего сбрасывать — у всех 0 баллов.")
        return

    if _active_reset_vote:
        if time.time() - _active_reset_vote.created_at > RESET_VOTE_TTL:
            _active_reset_vote = None
        else:
            await message.reply("⏳ Уже идёт голосование за сброс. Жми кнопки в том сообщении.")
            return

    required = {uid: name for uid, name, _ in players}
    if user.id not in required:
        await message.reply("🚫 Сброс могут инициировать только те, у кого есть баллы в рейтинге.")
        return

    vote_id = uuid.uuid4().hex[:8]
    vote = AlkashiResetVote(
        vote_id=vote_id,
        initiator_id=user.id,
        initiator_name=user.username or user.first_name or "Анон",
        required=required,
        agreed={user.id},
        created_at=int(time.time()),
    )
    _active_reset_vote = vote

    if len(vote.required) == 1:
        reset_all_scores()
        _active_reset_vote = None
        await message.reply(
            "🧹 Ты один в рейтинге — баллы обнулены. Все с 0!"
        )
        return

    sent = await message.reply(
        _reset_vote_status(vote),
        reply_markup=_reset_vote_keyboard(vote_id),
    )
    vote.chat_id = sent.chat.id
    vote.message_id = sent.message_id


@dp.callback_query(F.data.startswith("ars:"))
async def alkashi_reset_vote(callback: types.CallbackQuery):
    global _active_reset_vote

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка данных", show_alert=True)
        return

    _, action, vote_id = parts
    vote = _active_reset_vote

    if not vote or vote.vote_id != vote_id:
        await callback.answer("Голосование уже неактуально", show_alert=True)
        return

    if time.time() - vote.created_at > RESET_VOTE_TTL:
        await _finish_reset_vote(callback.bot, vote, False, "⏰ Время вышло — голосование отменено.")
        await callback.answer("Время вышло", show_alert=True)
        return

    user = callback.from_user
    if user.id not in vote.required:
        await callback.answer("Ты не в рейтинге — твой голос не нужен", show_alert=True)
        return

    if action == "no":
        vote.declined.add(user.id)
        name = vote.required[user.id]
        await _finish_reset_vote(
            callback.bot,
            vote,
            False,
            f"❌ <b>{name}</b> против. Сброс отменён.",
        )
        await callback.answer("Ты проголосовал против")
        return

    if action != "yes":
        await callback.answer("Неизвестное действие", show_alert=True)
        return

    if user.id in vote.agreed:
        await callback.answer("Ты уже согласился")
        return

    vote.agreed.add(user.id)
    await callback.answer("Ты согласился на сброс")

    if len(vote.agreed) >= len(vote.required):
        reset_all_scores()
        await _finish_reset_vote(
            callback.bot,
            vote,
            True,
            "🧹 <b>Все согласны!</b> Баллы алкашей обнулены. Все с 0!",
        )
        return

    if callback.message:
        try:
            await callback.message.edit_text(
                _reset_vote_status(vote),
                reply_markup=_reset_vote_keyboard(vote.vote_id),
            )
        except Exception:
            pass


# ========================
# NEW HANDLER - "наа" video
# ========================
@dp.message(F.text)
async def naa_video(message: types.Message):
    if not message.text:
        return
    
    text_lower = message.text.strip().lower()
    
    # Triggers on any message starting with "наа"
    if text_lower.startswith("наа"):
        try:
            await message.answer_video(
                types.FSInputFile("naa.mp4"),
                caption="нааааааа 🔥"
            )
        except FileNotFoundError:
            await message.reply("❌ Видео naa.mp4 не найдено в папке с ботом")
        except Exception as e:
            await message.reply("❌ Не смог отправить видео")


# =========================
# STICKER CATCHER (last handler)
# =========================
@dp.message()
async def catch_sticker(message: types.Message):
    if not message.sticker:
        return
    file_id = message.sticker.file_id
    user_id = message.from_user.id
    if sticker_exists(file_id):
        return
    add_sticker(file_id, user_id)


# =========================
# 🚀 START
# =========================
async def main():
    print("GPT Group AI running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())