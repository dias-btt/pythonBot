import asyncio
import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, TelegramObject

from db import get_naruto_duel_ratings, record_naruto_duel_result
from naruto_battle import resolve_jutsu_clash
from naruto_characters import NARUTO_CHARACTERS
from naruto_chemistry import (
    ChemistryBonus,
    chemistry_heal_multiplier,
    format_chemistry_block,
    get_team_chemistry,
)
from naruto_jutsu import get_jutsu_kit, jutsu_button_text
from naruto_team import POSITIONS, ROLE_KEYS, _rating_bar, is_chat_busy

COMMANDER_CHAKRA_START = 50
CHAKRA_REGEN = 8
CHAKRA_MAX = 65

DUEL_COMMANDS = ("/duel",)
PICK_DELAY = 2.0
BATTLE_DELAY = 2.5
CHAT_SEND_INTERVAL = 2.0
CHOICE_TIMEOUT = 28
BAN_TIMEOUT = 25
INACTIVITY_TIMEOUT = 300
INACTIVITY_CHECK_INTERVAL = 30

STRATEGIES = {
    "aggr": ("⚔️ Агрессия", "постоянно +6 к силе"),
    "bal": ("⚖️ Баланс", "стабильные +2 к силе"),
    "def": ("🛡️ Защита", "получаешь на 25% меньше урона"),
}

ITEMS = {
    "kunai": ("🗡️ Кунай", "шанс крита ×2"),
    "scroll": ("📜 Свиток", "лечение +15 HP на 3-м раунде"),
    "pill": ("💊 Пилюля", "+6 к силе каждый раунд"),
    "cursed": ("☠️ Проклятый печать", "+14 силы, но −8 HP в начале боя"),
}

BATTLEFIELDS = {
    "rain": ("🌧️ Ливень", "ниндзюцу сильнее, тайдзюцу слабее"),
    "sand": ("🏜️ Пустыня Суны", "танки +10 к силе джутсу"),
    "storm": ("⚡ Чакра-буря", "±8 к силе джутсу каждый раунд"),
    "forest": ("🌲 Лес Конохи", "баффы +4 сильнее"),
    "moon": ("🌙 Лунная арена", "гендзюцу +6"),
}

CHALLENGE_LINES = [
    "Кто осмелится бросить перчатку?",
    "Деревня смотрит. Кто примет вызов?",
    "Ставки сделаны. Ждём соперника!",
    "Это будет легендарно... или позорно.",
]

ROUND_HYPE = [
    "Арена замирает...",
    "Толпа затаила дыхание!",
    "Да начнётся хаос!",
    "Чакра в воздухе ощущается физически.",
]

RIVALRIES: dict[frozenset[str], str] = {
    frozenset({"Наруто Узумаки", "Саске Учиха"}): "🔥 <b>КЛАССИКА!</b> Наруто vs Саске — чат взрывается!",
    frozenset({"Madara Uchiha", "Hashirama Senju"}): "🌳💀 <b>ЛЕГЕНДЫ СТОЛЕТИЙ!</b> Мадара vs Хаширама!",
    frozenset({"Itachi Uchiha", "Саске Учиха"}): "👁️ <b>БРАТСКАЯ ДРАМА!</b> Итачи против Саске!",
    frozenset({"Малик Жалмурзин", "Наруто Узумаки"}): "👑 <b>БИТВА ЗА ТАЙТЛ ГЛАВНОГО ГЕРОЯ!</b>",
    frozenset({"Малик Жалмурзин", "Madara Uchiha"}): "⚡ <b>КАЙНАР ПРОТИВ ЛЕГЕНДЫ!</b> Кто сильнее мемов и лора?",
}

PICK_REACTIONS: dict[str, str] = {
    "Малик Жалмурзин": "Выбор босса. Удачи остальным.",
    "Наруто Узумаки": "DATTEBAYO! Сильный пик!",
    "Саске Учиха": "Хм. Ты серьёзно?",
    "Rock Lee": "МОЛОДОСТЬ ВЫБРАНА!",
    "Shikamaru Nara": "Какая морока... но пик умный.",
    "Choji Akimichi": "Пик с перекусом в кармане.",
}

TEAM_TITLES = [
    (90, "🔥 Легендарный отряд Kage-уровня"),
    (80, "⚡ Элитный Jonin-squad"),
    (70, "✅ Крепкая рабочая команда"),
    (60, "😐 Среднячок, но с душой"),
    (50, "😅 Chunin vibes — будет больно"),
    (0, "💀 Genin squad. Молитесь."),
]

WIN_LINES = [
    "🏆 <b>{winner}</b> забирает победу!\nСчёт: {score}\n💀 {loser} отправлен в больницу Конохи на рамен и рефлексию.",
    "🏆 <b>{winner}</b> уничтожил соперника!\nСчёт: {score}\n📜 {loser} подписывает капитуляцию от боли.",
    "🏆 Победа <b>{winner}</b>!\nСчёт: {score}\n🍥 {loser} говорит «это нечестно» и всё равно проиграл.",
]

DRAW_LINES = [
    "🤝 Ничья! HP: {score}\nОба выжили — Хокаге в шоке, чат доволен.",
    "🤝 Ничья! HP: {score}\nНикто не победил, но все получили контент.",
]

AFK_LEFT_LINES = [
    "🍃 <b>{name}</b> испарился в дымовую завесу и бросил duel!\n"
    "Похоже, его затянуло в раменную. <b>{other}</b> остаётся один на арене.",
    "💤 <b>{name}</b> уснул на лавке у Хокаге и не вернулся 5 минут.\n"
    "Duel отменён — <b>{other}</b> может спокойно идти домой.",
    "🐌 <b>{name}</b> слишком долго медитировал в другом измерении.\n"
    "Арена закрыта. <b>{other}</b>, тебе повезло — соперник сам сбежал!",
    "👻 <b>{name}</b> использовал «Технику исчезновения из чата» и не появился.\n"
    "Duel снят с учёта. <b>{other}</b> победил по нокауту от скуки.",
    "🍥 <b>{name}</b> пошёл за мисо-раменом и забыл про бой.\n"
    "Пять минут ожидания — и duel рассыпался. <b>{other}</b> свободен!",
]

NO_ACCEPT_LINES = [
    "🥱 Пять минут тишины... Никто не осмелился принять вызов <b>{name}</b>!\n"
    "Duel растворился в тумане, как слабый клон.",
    "🦗 Вызов <b>{name}</b> эхом отдавался в чате 5 минут — ответа ноль.\n"
    "Перчатка лежит на земле, duel отменён.",
    "⏳ <b>{name}</b> ждал героя, но пришла только тишина.\n"
    "Вызов сгорел. Можно снова жать /duel!",
]

INSTRUCTIONS_TEXT = (
    "📖 <b>ПРАВИЛА NARUTO DUEL — ТАКТИЧЕСКИЙ БОЙ</b>\n\n"
    "<b>0. Бан</b> — каждый банит 1 персонажа из 5 (для обоих недоступен)\n\n"
    "<b>1. Драфт</b> — 6 ролей, раунды 4–6 только 2 варианта, 1 переролл\n"
    "• 🏘️ 3–6 ниндзя одной деревни = бонус химии (сила, чакра, хил, защита)\n\n"
    "<b>2. Подготовка</b> — стратегия, предмет, 🃏 туз (+12 в секретном раунде)\n\n"
    "<b>3. Тактический бой</b>\n"
    f"• У командира <b>{COMMANDER_CHAKRA_START}💠</b> чакры (+{CHAKRA_REGEN}/раунд)\n"
    "• Каждый раунд — бой 1 на 1 по ролям\n"
    "• У каждого бойца <b>3 уникальных джутсу</b> — выбирай одно!\n"
    "• 🔥 Ниндзюцу — урон | 👊 Тайдзюцу — бьёт гендзюцу\n"
    "• 👁 Гендзюцу — ослабляет | 💚 Хил — лечит командира\n"
    "• ⬆️ Бафф — усиливает след. джутсу | 🪞 Контр — карает ниндзюцу\n"
    "• Сильнее джутсу на линии → урон HP командира соперника\n"
    f"• ⏱ {CHOICE_TIMEOUT} сек на выбор джутсу\n\n"
    "<b>4. Победа</b> — больше HP командира после 6 раундов\n\n"
    "👇 Оба игрока должны нажать «Прочитал»!"
)

_duels: dict[str, "Duel"] = {}
_chat_duel: dict[int, str] = {}
_lock = asyncio.Lock()
_chat_send_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_chat_last_send: dict[int, float] = {}


async def _safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> types.Message:
    async with _chat_send_locks[chat_id]:
        elapsed = time.monotonic() - _chat_last_send.get(chat_id, 0.0)
        if elapsed < CHAT_SEND_INTERVAL:
            await asyncio.sleep(CHAT_SEND_INTERVAL - elapsed)

        while True:
            try:
                msg = await bot.send_message(chat_id, text, **kwargs)
                _chat_last_send[chat_id] = time.monotonic()
                return msg
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)


@dataclass
class Duel:
    id: str
    chat_id: int
    challenger_id: int
    challenger_name: str
    opponent_id: int | None = None
    opponent_name: str | None = None
    phase: str = "waiting"
    role_index: int = 0
    teams: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    picks_done: dict[int, set[int]] = field(default_factory=dict)
    options: dict[int, dict[int, list[dict]]] = field(default_factory=dict)
    used_names: dict[int, set[str]] = field(default_factory=dict)
    challenge_msg_id: int | None = None
    rerolls_used: dict[int, bool] = field(default_factory=dict)
    strategies: dict[int, str] = field(default_factory=dict)
    items: dict[int, str] = field(default_factory=dict)
    commander_chakra: dict[int, int] = field(default_factory=dict)
    scroll_used: dict[int, bool] = field(default_factory=dict)
    prep_choices: dict[str, str] = field(default_factory=dict)
    prep_event: asyncio.Event | None = None
    round_jutsu: dict[int, int] = field(default_factory=dict)
    jutsu_event: asyncio.Event | None = None
    waiting_jutsu_round: int = 0
    jutsu_buff: dict[int, int] = field(default_factory=dict)
    guard_buff: dict[int, bool] = field(default_factory=dict)
    instructions_read: set[int] = field(default_factory=set)
    bans: dict[int, str] = field(default_factory=dict)
    ban_options: dict[int, list[dict]] = field(default_factory=dict)
    ban_event: asyncio.Event | None = None
    battlefield: str = ""
    ace_slot: dict[int, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    last_active: dict[int, float] = field(default_factory=dict)
    inactivity_task: asyncio.Task | None = field(default=None, compare=False, repr=False)
    team_chemistry: dict[int, ChemistryBonus | None] = field(default_factory=dict)


def is_duel_active(chat_id: int) -> bool:
    duel_id = _chat_duel.get(chat_id)
    if not duel_id:
        return False
    duel = _duels.get(duel_id)
    return duel is not None and duel.phase in (
        "instructions", "ban", "draft", "prep", "battle",
    )


def _get_duel_in_chat(chat_id: int) -> Duel | None:
    duel_id = _chat_duel.get(chat_id)
    if not duel_id:
        return None
    duel = _duels.get(duel_id)
    if duel and duel.phase not in ("done", "cancelled"):
        return duel
    return None


def _duel_aborted(duel: Duel) -> bool:
    return duel.phase in ("done", "cancelled")


def _touch_duel_activity(duel: Duel, user_id: int) -> None:
    duel.last_active[user_id] = time.monotonic()


def _other_player_id(duel: Duel, user_id: int) -> int | None:
    if duel.opponent_id is None:
        return None
    return duel.opponent_id if user_id == duel.challenger_id else duel.challenger_id


async def _abort_duel(duel: Duel) -> bool:
    async with _lock:
        if duel.phase in ("done", "cancelled"):
            return False
        duel.phase = "cancelled"
        if duel.prep_event:
            duel.prep_event.set()
        if duel.jutsu_event:
            duel.jutsu_event.set()
        if duel.ban_event:
            duel.ban_event.set()
        return True


def _ensure_inactivity_watch(bot: Bot, duel: Duel) -> None:
    if duel.inactivity_task and not duel.inactivity_task.done():
        return
    duel.inactivity_task = asyncio.create_task(_inactivity_watch(bot, duel))


async def _inactivity_watch(bot: Bot, duel: Duel) -> None:
    try:
        while not _duel_aborted(duel):
            await asyncio.sleep(INACTIVITY_CHECK_INTERVAL)
            if _duel_aborted(duel):
                break

            now = time.monotonic()

            if duel.phase == "waiting" and duel.opponent_id is None:
                if now - duel.started_at >= INACTIVITY_TIMEOUT:
                    if not await _abort_duel(duel):
                        return
                    msg = random.choice(NO_ACCEPT_LINES).format(name=duel.challenger_name)
                    await _safe_send(bot, duel.chat_id, msg)
                    await _cleanup_duel(duel)
                continue

            if duel.opponent_id is None:
                continue

            for user_id in (duel.challenger_id, duel.opponent_id):
                last = duel.last_active.get(user_id, duel.started_at)
                if now - last >= INACTIVITY_TIMEOUT:
                    if not await _abort_duel(duel):
                        return
                    name = _player_name(duel, user_id)
                    other_id = _other_player_id(duel, user_id)
                    other = _player_name(duel, other_id) if other_id else "соперник"
                    msg = random.choice(AFK_LEFT_LINES).format(name=name, other=other)
                    await _safe_send(bot, duel.chat_id, msg)
                    await _cleanup_duel(duel)
                    return
    except asyncio.CancelledError:
        pass


async def _cancel_duel(bot: Bot, duel: Duel, canceller_name: str) -> None:
    if not await _abort_duel(duel):
        return
    opponent = duel.opponent_name or "соперник"
    await _safe_send(
        bot,
        duel.chat_id,
        f"🛑 <b>Duel отменён</b> инициатором <b>{canceller_name}</b>.\n"
        f"{opponent} свободен. Чат снова открыт.",
    )
    await _cleanup_duel(duel)


def _player_ids(duel: Duel) -> list[int]:
    return [duel.challenger_id, duel.opponent_id]  # type: ignore[list-item]


def _player_name(duel: Duel, user_id: int) -> str:
    if user_id == duel.challenger_id:
        return duel.challenger_name
    return duel.opponent_name or "Ниндзя"


def _prep_key(user_id: int, kind: str) -> str:
    return f"{user_id}:{kind}"


async def _wait_prep(duel: Duel) -> None:
    duel.prep_choices.clear()
    duel.prep_event = asyncio.Event()
    try:
        await asyncio.wait_for(duel.prep_event.wait(), timeout=CHOICE_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    if _duel_aborted(duel):
        duel.prep_event = None
        return
    for user_id in _player_ids(duel):
        if _prep_key(user_id, "strategy") not in duel.prep_choices:
            duel.prep_choices[_prep_key(user_id, "strategy")] = random.choice(list(STRATEGIES))
        if _prep_key(user_id, "item") not in duel.prep_choices:
            duel.prep_choices[_prep_key(user_id, "item")] = random.choice(list(ITEMS))
        duel.strategies[user_id] = duel.prep_choices[_prep_key(user_id, "strategy")]
        duel.items[user_id] = duel.prep_choices[_prep_key(user_id, "item")]
        if _prep_key(user_id, "ace") not in duel.prep_choices:
            duel.prep_choices[_prep_key(user_id, "ace")] = str(random.randint(0, len(POSITIONS) - 1))
        duel.ace_slot[user_id] = int(duel.prep_choices[_prep_key(user_id, "ace")])
    duel.prep_event = None


def _signal_prep(duel: Duel) -> None:
    needed = {
        _prep_key(uid, k) for uid in _player_ids(duel) for k in ("strategy", "item", "ace")
    }
    if needed.issubset(duel.prep_choices.keys()) and duel.prep_event:
        duel.prep_event.set()


async def _wait_bans(duel: Duel) -> None:
    duel.bans.clear()
    duel.ban_event = asyncio.Event()
    try:
        await asyncio.wait_for(duel.ban_event.wait(), timeout=BAN_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    if _duel_aborted(duel):
        duel.ban_event = None
        return
    for user_id in _player_ids(duel):
        if user_id not in duel.bans:
            opts = duel.ban_options.get(user_id, [])
            if opts:
                duel.bans[user_id] = random.choice(opts)["name"]
    duel.ban_event = None


def _signal_ban(duel: Duel) -> None:
    if len(duel.bans) >= 2 and duel.ban_event:
        duel.ban_event.set()


def _global_bans(duel: Duel) -> set[str]:
    return set(duel.bans.values())


async def _wait_jutsu(duel: Duel, round_num: int) -> None:
    duel.round_jutsu.clear()
    duel.waiting_jutsu_round = round_num
    duel.jutsu_event = asyncio.Event()
    try:
        await asyncio.wait_for(duel.jutsu_event.wait(), timeout=CHOICE_TIMEOUT)
    except asyncio.TimeoutError:
        pass
    if _duel_aborted(duel):
        duel.jutsu_event = None
        duel.waiting_jutsu_round = 0
        return
    for user_id in _player_ids(duel):
        if user_id not in duel.round_jutsu:
            slot = duel.teams[user_id][round_num - 1]
            idx = _auto_jutsu_index(duel, user_id, slot)
            j = slot["jutsu"][idx]
            duel.commander_chakra[user_id] = max(
                0, duel.commander_chakra[user_id] - j["chakra"],
            )
            duel.round_jutsu[user_id] = idx
    duel.jutsu_event = None
    duel.waiting_jutsu_round = 0


def _signal_jutsu(duel: Duel, round_num: int) -> None:
    if duel.waiting_jutsu_round != round_num:
        return
    if len(duel.round_jutsu) >= 2 and duel.jutsu_event:
        duel.jutsu_event.set()


def _user_name(user: types.User | None) -> str:
    if not user:
        return "Ниндзя"
    return user.first_name or user.username or f"ID{user.id}"


def _role_key(role_index: int) -> str:
    role_key, _ = POSITIONS[role_index]
    return ROLE_KEYS[role_key]


def _role_label(role_index: int) -> str:
    _, label = POSITIONS[role_index]
    return label


def _char_rating(char: dict, role_index: int) -> int:
    base = char["ratings"][_role_key(role_index)]
    return max(1, min(100, base + random.randint(-8, 8)))


def _pick_options(exclude: set[str], count: int = 3, banned: set[str] | None = None) -> list[dict]:
    banned = banned or set()
    pool = [
        c for c in NARUTO_CHARACTERS
        if c["name"] not in exclude and c["name"] not in banned
    ]
    if len(pool) < count:
        pool = [c for c in NARUTO_CHARACTERS if c["name"] not in banned]
    if len(pool) < count:
        pool = list(NARUTO_CHARACTERS)
    return random.sample(pool, min(count, len(pool)))


def _ban_options() -> list[dict]:
    return random.sample(NARUTO_CHARACTERS, min(5, len(NARUTO_CHARACTERS)))


def _build_slot(char: dict, role_index: int) -> dict[str, Any]:
    role_key, role_label = POSITIONS[role_index]
    rating = _char_rating(char, role_index)
    return {
        "role_key": role_key,
        "role_label": role_label,
        "character": char,
        "rating": rating,
        "jutsu": get_jutsu_kit(char, rating),
    }


def _hp_bar(hp: int) -> str:
    filled = max(0, min(10, hp // 10))
    return "❤️" + "█" * filled + "░" * (10 - filled) + f" {hp}"


def _team_title(avg: float) -> str:
    for threshold, title in TEAM_TITLES:
        if avg >= threshold:
            return title
    return TEAM_TITLES[-1][1]


def _rivalry_line(c1: dict, c2: dict) -> str | None:
    pair = frozenset({c1["name"], c2["name"]})
    return RIVALRIES.get(pair)


def _format_team(name: str, team: list[dict[str, Any]]) -> str:
    lines = [f"🍥 <b>Команда {name}</b>\n"]
    for slot in team:
        char = slot["character"]
        lines.append(
            f"{slot['role_label']}: <b>{char['name']}</b> ({char['village']}) — {slot['rating']}/100"
        )
    avg = round(sum(s["rating"] for s in team) / len(team), 1)
    lines.append(f"\n📊 Сила: {avg}/100 {_rating_bar(int(avg))}")
    lines.append(f"🎖 {_team_title(avg)}")
    chem = get_team_chemistry(team)
    chem_line = format_chemistry_block(chem)
    if chem_line:
        lines.append(chem_line)
    return "\n".join(lines)


def _strategy_bonus(strategy: str) -> int:
    if strategy == "aggr":
        return 6
    if strategy == "bal":
        return 2
    return 0


def _auto_jutsu_index(duel: Duel, user_id: int, slot: dict) -> int:
    chakra = duel.commander_chakra.get(user_id, 0)
    affordable = [
        i for i, j in enumerate(slot["jutsu"]) if j["chakra"] <= chakra
    ]
    if affordable:
        return random.choice(affordable)
    return min(range(len(slot["jutsu"])), key=lambda i: slot["jutsu"][i]["chakra"])


def _jutsu_keyboard(
    duel: Duel,
    user_id: int,
    round_num: int,
    slot: dict,
) -> InlineKeyboardMarkup:
    rows = []
    for i, j in enumerate(slot["jutsu"]):
        affordable = duel.commander_chakra.get(user_id, 0) >= j["chakra"]
        label = jutsu_button_text(j)
        if not affordable:
            label = f"🔒 {label}"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"djt:{duel.id}:{user_id}:{round_num}:{i}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _jutsu_picker_text(duel: Duel, user_id: int, name: str, slot: dict, round_num: int) -> str:
    role = slot["role_label"]
    char = slot["character"]["name"]
    chakra = duel.commander_chakra.get(user_id, 0)
    lines = [
        f"🎮 <b>Раунд {round_num}</b> — {role}",
        f"<b>{name}</b> — бойец: <b>{char}</b> | 💠 {chakra}",
        "Выбери джутсу:",
    ]
    for j in slot["jutsu"]:
        lines.append(f"• {jutsu_button_text(j)} — <i>{j['desc']}</i>")
    lines.append(f"⏱ {CHOICE_TIMEOUT} сек")
    return "\n".join(lines)


def _execute_jutsu_round(
    duel: Duel,
    slot1: dict,
    slot2: dict,
    hp1: int,
    hp2: int,
    name1: str,
    name2: str,
    round_num: int,
    jidx1: int,
    jidx2: int,
) -> tuple[int, int, str]:
    uid1, uid2 = duel.challenger_id, duel.opponent_id
    j1 = slot1["jutsu"][jidx1]
    j2 = slot2["jutsu"][jidx2]
    extra: list[str] = [random.choice(ROUND_HYPE)]

    if round_num == 3:
        if duel.items.get(uid1) == "scroll" and not duel.scroll_used.get(uid1):
            heal = min(15, 100 - hp1)
            hp1 += heal
            duel.scroll_used[uid1] = True
            extra.append(f"📜 Свиток <b>{name1}</b>: +{heal} HP")
        if duel.items.get(uid2) == "scroll" and not duel.scroll_used.get(uid2):
            heal = min(15, 100 - hp2)
            hp2 += heal
            duel.scroll_used[uid2] = True
            extra.append(f"📜 Свиток <b>{name2}</b>: +{heal} HP")

    chem1 = duel.team_chemistry.get(uid1)
    chem2 = duel.team_chemistry.get(uid2)
    buff1 = duel.jutsu_buff.get(uid1, 0) + _strategy_bonus(duel.strategies[uid1])
    buff2 = duel.jutsu_buff.get(uid2, 0) + _strategy_bonus(duel.strategies[uid2])
    if chem1:
        buff1 += chem1.jutsu_power
    if chem2:
        buff2 += chem2.jutsu_power
    if duel.items.get(uid1) == "pill":
        buff1 += 6
    if duel.items.get(uid2) == "pill":
        buff2 += 6

    role_idx = round_num - 1
    if duel.ace_slot.get(uid1) == role_idx:
        buff1 += 12
        extra.append(f"🃏 <b>{name1}</b> раскрывает туз!")
    if duel.ace_slot.get(uid2) == role_idx:
        buff2 += 12
        extra.append(f"🃏 <b>{name2}</b> раскрывает туз!")

    rivalry = _rivalry_line(slot1["character"], slot2["character"])
    if rivalry:
        extra.append(rivalry)

    if duel.battlefield == "sand" and slot1["role_key"] == "tank":
        buff1 += 10
    if duel.battlefield == "sand" and slot2["role_key"] == "tank":
        buff2 += 10
    if duel.battlefield == "forest":
        if j1["type"] == "buff":
            buff1 += 4
        if j2["type"] == "buff":
            buff2 += 4
    if duel.battlefield == "moon":
        if j1["type"] == "genjutsu":
            buff1 += 6
        if j2["type"] == "genjutsu":
            buff2 += 6
    if duel.battlefield == "rain":
        if j1["type"] == "ninjutsu":
            buff1 += 6
        elif j1["type"] == "taijutsu":
            buff1 -= 4
        if j2["type"] == "ninjutsu":
            buff2 += 6
        elif j2["type"] == "taijutsu":
            buff2 -= 4

    hp1, hp2, nb1, nb2, ng1, ng2, log = resolve_jutsu_clash(
        j1, j2, slot1, slot2, hp1, hp2, name1, name2,
        buff1, buff2,
        duel.guard_buff.get(uid1, False),
        duel.guard_buff.get(uid2, False),
        slot1["role_label"], round_num,
        heal_mult1=chemistry_heal_multiplier(chem1),
        heal_mult2=chemistry_heal_multiplier(chem2),
        dmg_reduce1=chem1.damage_reduce_pct if chem1 else 0,
        dmg_reduce2=chem2.damage_reduce_pct if chem2 else 0,
    )
    duel.jutsu_buff[uid1] = nb1
    duel.jutsu_buff[uid2] = nb2
    duel.guard_buff[uid1] = ng1
    duel.guard_buff[uid2] = ng2
    return hp1, hp2, "\n".join(extra) + "\n\n" + log


def _strategy_keyboard(duel_id: str, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for key, (label, _) in STRATEGIES.items():
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"dpr:{duel_id}:{user_id}:strategy:{key}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ban_keyboard(duel_id: str, user_id: int, options: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, char in enumerate(options):
        rows.append([
            InlineKeyboardButton(
                text=f"🚫 {char['name']}",
                callback_data=f"dbn:{duel_id}:{user_id}:{i}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ace_keyboard(duel_id: str, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for i, (_, label) in enumerate(POSITIONS):
        rows.append([
            InlineKeyboardButton(
                text=f"🃏 {label}",
                callback_data=f"dpr:{duel_id}:{user_id}:ace:{i}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _item_keyboard(duel_id: str, user_id: int) -> InlineKeyboardMarkup:
    rows = []
    for key, (label, _) in ITEMS.items():
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"dpr:{duel_id}:{user_id}:item:{key}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pick_keyboard(
    duel: Duel, user_id: int, role_index: int, options: list[dict],
) -> InlineKeyboardMarkup:
    rows = []
    for i, char in enumerate(options):
        rows.append([
            InlineKeyboardButton(
                text=char["name"],
                callback_data=f"dpl:{duel.id}:{user_id}:{role_index}:{i}",
            )
        ])
    if not duel.rerolls_used.get(user_id):
        rows.append([
            InlineKeyboardButton(
                text="🔄 Переролл (1 раз за duel)",
                callback_data=f"drr:{duel.id}:{user_id}:{role_index}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _accept_keyboard(duel_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⚔️ Принять вызов", callback_data=f"dac:{duel_id}")]]
    )


def _read_instructions_keyboard(duel_id: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Прочитал, готов!",
                callback_data=f"dir:{duel_id}:{user_id}",
            )
        ]]
    )


async def _send_instructions(bot: Bot, duel: Duel) -> None:
    await _safe_send(bot, duel.chat_id, INSTRUCTIONS_TEXT)

    for user_id, name in (
        (duel.challenger_id, duel.challenger_name),
        (duel.opponent_id, duel.opponent_name),
    ):
        await _safe_send(
            bot,
            duel.chat_id,
            f"📋 <b>{name}</b>, подтверди, что прочитал правила:",
            reply_markup=_read_instructions_keyboard(duel.id, user_id),
        )


async def _cleanup_duel(duel: Duel) -> None:
    task = duel.inactivity_task
    if task and not task.done():
        task.cancel()
    duel.inactivity_task = None
    async with _lock:
        _duels.pop(duel.id, None)
        if _chat_duel.get(duel.chat_id) == duel.id:
            _chat_duel.pop(duel.chat_id, None)


async def _send_ban_phase(bot: Bot, duel: Duel) -> None:
    duel.phase = "ban"
    await _safe_send(
        bot,
        duel.chat_id,
        f"🚫 <b>Фаза бана!</b>\n"
        f"Каждый банит 1 персонажа — он недоступен обоим.\n"
        f"⏱ {BAN_TIMEOUT} сек на выбор.",
    )
    await asyncio.sleep(PICK_DELAY)

    ban_task = asyncio.create_task(_wait_bans(duel))
    for user_id, name in (
        (duel.challenger_id, duel.challenger_name),
        (duel.opponent_id, duel.opponent_name),
    ):
        options = _ban_options()
        duel.ban_options[user_id] = options
        await _safe_send(
            bot,
            duel.chat_id,
            f"🚫 <b>{name}</b>, кого баним?",
            reply_markup=_ban_keyboard(duel.id, user_id, options),
        )

    await ban_task
    if _duel_aborted(duel):
        return
    banned = _global_bans(duel)
    ban_lines = ["🔒 <b>Баны зафиксированы:</b>"]
    for user_id, name in (
        (duel.challenger_id, duel.challenger_name),
        (duel.opponent_id, duel.opponent_name),
    ):
        ban_lines.append(f"• <b>{name}</b> → <b>{duel.bans.get(user_id, '?')}</b>")
    ban_lines.append(f"\n🚫 Всего недоступно: {', '.join(sorted(banned))}")
    await _safe_send(bot, duel.chat_id, "\n".join(ban_lines))
    await asyncio.sleep(PICK_DELAY)

    duel.phase = "draft"
    await _safe_send(
        bot,
        duel.chat_id,
        f"🍥 Баны учтены! Начинаем драфт!\n"
        f"<b>{duel.challenger_name}</b> 🆚 <b>{duel.opponent_name}</b>",
    )
    await asyncio.sleep(PICK_DELAY)
    await _send_draft_round(bot, duel)


async def _send_draft_round(bot: Bot, duel: Duel) -> None:
    if _duel_aborted(duel):
        return
    role_index = duel.role_index
    role_label = _role_label(role_index)
    banned = _global_bans(duel)
    option_count = 3 if role_index < 3 else 2

    for user_id, name in (
        (duel.challenger_id, duel.challenger_name),
        (duel.opponent_id, duel.opponent_name),
    ):
        if user_id is None:
            continue
        exclude = duel.used_names.setdefault(user_id, set())
        options = _pick_options(exclude, count=option_count, banned=banned)
        duel.options.setdefault(user_id, {})[role_index] = options
        duel.picks_done.setdefault(user_id, set())

        round_no = role_index + 1
        hint = random.choice([
            "Думай с головой — соперник читает чат 👀",
            "Пикни кого-то, кого соперник точно не ждёт",
            "Легенда или мем — решать тебе",
        ])
        opts_note = f"{option_count} варианта" if option_count == 2 else "3 варианта"
        await _safe_send(
            bot,
            duel.chat_id,
            f"🎯 <b>Раунд {round_no}/{len(POSITIONS)}</b> — {role_label}\n"
            f"<b>{name}</b>, твой ход! ({opts_note})\n"
            f"<i>{hint}</i>",
            reply_markup=_pick_keyboard(duel, user_id, role_index, options),
        )


async def _run_prep(bot: Bot, duel: Duel) -> None:
    duel.phase = "prep"
    await _safe_send(
        bot,
        duel.chat_id,
        "🧠 <b>Фаза подготовки!</b>\n"
        "Каждый игрок выбирает стратегию и предмет.\n"
        f"⏱ У вас {CHOICE_TIMEOUT} сек на решения.",
    )
    await asyncio.sleep(PICK_DELAY)

    prep_task = asyncio.create_task(_wait_prep(duel))
    for user_id, name in (
        (duel.challenger_id, duel.challenger_name),
        (duel.opponent_id, duel.opponent_name),
    ):
        await _safe_send(
            bot,
            duel.chat_id,
            f"🎯 <b>{name}</b>, выбери стратегию на весь бой:",
            reply_markup=_strategy_keyboard(duel.id, user_id),
        )
        await _safe_send(
            bot,
            duel.chat_id,
            f"🎒 <b>{name}</b>, выбери предмет (1 раз за duel):",
            reply_markup=_item_keyboard(duel.id, user_id),
        )
        await _safe_send(
            bot,
            duel.chat_id,
            f"🃏 <b>{name}</b>, выбери секретную роль-туз (+12 в её раунде):",
            reply_markup=_ace_keyboard(duel.id, user_id),
        )

    await prep_task
    if _duel_aborted(duel):
        return

    lines = ["📋 <b>Подготовка завершена!</b>\n"]
    for user_id, name in (
        (duel.challenger_id, duel.challenger_name),
        (duel.opponent_id, duel.opponent_name),
    ):
        strat = STRATEGIES[duel.strategies[user_id]]
        item = ITEMS[duel.items[user_id]]
        lines.append(
            f"<b>{name}</b>: {strat[0]} + {item[0]} | 💠 {COMMANDER_CHAKRA_START} чакры\n"
            f"<i>{strat[1]} | {item[1]}</i>\n"
            f"🃏 Туз: <i>скрыт до раунда</i>"
        )
    lines.append(
        f"\n⚔️ В бою выбирай <b>1 из 3 джутсу</b> своего бойца каждый раунд!\n"
        f"Реген чакры: +{CHAKRA_REGEN}/раунд (макс {CHAKRA_MAX})"
    )
    await _safe_send(bot, duel.chat_id, "\n".join(lines))
    await asyncio.sleep(PICK_DELAY)


async def _finish_draft(bot: Bot, duel: Duel) -> None:
    try:
        if _duel_aborted(duel):
            return
        await _safe_send(
            bot,
            duel.chat_id,
            "🔒 <b>Драфт завершён!</b>\n"
            "Команды раскрыты. Арена готовится...\n"
            f"{random.choice(['🥁', '⚡', '🔥', '🍥'])} {random.choice(ROUND_HYPE)}",
        )
        await asyncio.sleep(PICK_DELAY)
        if _duel_aborted(duel):
            return

        team1 = duel.teams[duel.challenger_id]
        team2 = duel.teams[duel.opponent_id]
        duel.team_chemistry[duel.challenger_id] = get_team_chemistry(team1)
        duel.team_chemistry[duel.opponent_id] = get_team_chemistry(team2)

        await _safe_send(
            bot,
            duel.chat_id,
            _format_team(duel.challenger_name, team1)
            + f"\n\n👀 Это команда соперника для <b>{duel.opponent_name}</b>\n\n"
            + _format_team(duel.opponent_name, team2)
            + f"\n\n👀 Это команда соперника для <b>{duel.challenger_name}</b>",
        )
        await asyncio.sleep(PICK_DELAY)
        if _duel_aborted(duel):
            return
        await _run_prep(bot, duel)
        if _duel_aborted(duel):
            return
        await _run_battle(bot, duel)
    except Exception:
        if duel.id in _duels:
            duel.phase = "done"
            await _cleanup_duel(duel)
        raise


async def _run_battle(bot: Bot, duel: Duel) -> None:
    try:
        duel.phase = "battle"
        team1 = duel.teams[duel.challenger_id]
        team2 = duel.teams[duel.opponent_id]
        hp1, hp2 = 100, 100
        uid1, uid2 = duel.challenger_id, duel.opponent_id
        damage_stats: dict[int, list[int]] = {
            uid1: [0, 0],
            uid2: [0, 0],
        }
        duel.battlefield = random.choice(list(BATTLEFIELDS))
        chem1 = duel.team_chemistry.get(uid1)
        chem2 = duel.team_chemistry.get(uid2)
        duel.commander_chakra = {
            uid1: COMMANDER_CHAKRA_START + (chem1.chakra_bonus if chem1 else 0),
            uid2: COMMANDER_CHAKRA_START + (chem2.chakra_bonus if chem2 else 0),
        }
        duel.jutsu_buff = {uid1: 0, uid2: 0}
        duel.guard_buff = {uid1: False, uid2: False}

        if duel.items.get(uid1) == "cursed":
            hp1 = max(1, hp1 - 8)
        if duel.items.get(uid2) == "cursed":
            hp2 = max(1, hp2 - 8)

        field_name, field_desc = BATTLEFIELDS[duel.battlefield]
        cursed_note = ""
        if duel.items.get(uid1) == "cursed" or duel.items.get(uid2) == "cursed":
            cursed_note = "\n☠️ Проклятые печати снимают 8 HP в начале!"

        chem_notes: list[str] = []
        for uid, pname in ((uid1, duel.challenger_name), (uid2, duel.opponent_name)):
            chem = duel.team_chemistry.get(uid)
            if chem:
                chem_notes.append(
                    f"🏘️ <b>{pname}</b>: {chem.tier_name} ({chem.village} ×{chem.count}) — {chem.perks_short}"
                )
        chem_block = ("\n" + "\n".join(chem_notes)) if chem_notes else ""

        avg1 = sum(s["rating"] for s in team1) / len(team1)
        avg2 = sum(s["rating"] for s in team2) / len(team2)
        fav = duel.challenger_name if avg1 >= avg2 else duel.opponent_name
        underdog = duel.opponent_name if fav == duel.challenger_name else duel.challenger_name

        await _safe_send(
            bot,
            duel.chat_id,
            f"⚔️ <b>БОЙ НАЧИНАЕТСЯ!</b>\n"
            f"<b>{duel.challenger_name}</b> 🆚 <b>{duel.opponent_name}</b>\n\n"
            f"📊 Фаворит: <b>{fav}</b> | Аутсайдер: <b>{underdog}</b>\n"
            f"🌍 Поле: <b>{field_name}</b> — <i>{field_desc}</i>{cursed_note}{chem_block}\n"
            f"{_hp_bar(hp1)} vs {_hp_bar(hp2)}",
        )
        await asyncio.sleep(BATTLE_DELAY)

        for round_num, (slot1, slot2) in enumerate(zip(team1, team2), start=1):
            if _duel_aborted(duel):
                return
            for uid in (uid1, uid2):
                duel.commander_chakra[uid] = min(
                    CHAKRA_MAX,
                    duel.commander_chakra[uid] + CHAKRA_REGEN,
                )

            jutsu_task = asyncio.create_task(_wait_jutsu(duel, round_num))

            for user_id, name, slot in (
                (uid1, duel.challenger_name, slot1),
                (uid2, duel.opponent_name, slot2),
            ):
                await _safe_send(
                    bot,
                    duel.chat_id,
                    _jutsu_picker_text(duel, user_id, name, slot, round_num),
                    reply_markup=_jutsu_keyboard(duel, user_id, round_num, slot),
                )

            await jutsu_task

            prev_hp1, prev_hp2 = hp1, hp2
            hp1, hp2, text = _execute_jutsu_round(
                duel,
                slot1,
                slot2,
                hp1,
                hp2,
                duel.challenger_name,
                duel.opponent_name,
                round_num,
                duel.round_jutsu[uid1],
                duel.round_jutsu[uid2],
            )
            if hp2 < prev_hp2:
                dealt = prev_hp2 - hp2
                damage_stats[uid1][0] += dealt
                damage_stats[uid2][1] += dealt
            if hp1 < prev_hp1:
                dealt = prev_hp1 - hp1
                damage_stats[uid2][0] += dealt
                damage_stats[uid1][1] += dealt

            await _safe_send(bot, duel.chat_id, text)
            await asyncio.sleep(BATTLE_DELAY)

            if hp1 <= 0 or hp2 <= 0:
                break

        if hp1 > hp2:
            winner, loser = duel.challenger_name, duel.opponent_name
            winner_id = uid1
            score = f"{hp1} — {hp2}"
        elif hp2 > hp1:
            winner, loser = duel.opponent_name, duel.challenger_name
            winner_id = uid2
            score = f"{hp2} — {hp1}"
        else:
            winner = None
            winner_id = None
            score = f"{hp1} — {hp2}"

        if winner:
            margin = abs(hp1 - hp2)
            if margin >= 40:
                flair = "Разгромная победа — соперник в астрале."
            elif margin >= 20:
                flair = "Уверенная победа, но соперник сопротивлялся."
            else:
                flair = "Победа в последний момент — драма до конца!"
            final = random.choice(WIN_LINES).format(
                winner=winner, loser=loser, score=score
            ) + f"\n\n<i>{flair}</i>"
        else:
            final = random.choice(DRAW_LINES).format(score=score)

        h2h = record_naruto_duel_result(
            uid1,
            duel.challenger_name,
            uid2,
            duel.opponent_name or "Ниндзя",
            winner_id,
            {
                uid1: (damage_stats[uid1][0], damage_stats[uid1][1]),
                uid2: (damage_stats[uid2][0], damage_stats[uid2][1]),
            },
        )
        w1, w2, draws = h2h
        h2h_line = (
            f"\n\n📊 <b>Личный счёт:</b> "
            f"<b>{duel.challenger_name}</b> {w1} — {w2} "
            f"<b>{duel.opponent_name}</b>"
        )
        if draws:
            h2h_line += f" (ничьих: {draws})"

        final += h2h_line
        await _safe_send(bot, duel.chat_id, final)
    finally:
        if duel.id in _duels:
            duel.phase = "done"
            await _cleanup_duel(duel)


class DuelBlockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not isinstance(event, types.Message):
            return await handler(event, data)

        text = (event.text or "").strip()
        if not text.startswith("/"):
            return await handler(event, data)

        if not is_duel_active(event.chat.id):
            return await handler(event, data)

        cmd = text.split()[0].split("@")[0].lower()
        if cmd in ("/otboi",):
            return await handler(event, data)
        if cmd in DUEL_COMMANDS:
            await event.reply("⏳ Duel уже идёт в этом чате!")
            return

        await event.reply("⏳ Сейчас идёт Naruto duel. Другие команды заблокированы.")
        return


def _format_naruto_ratings() -> str:
    rows = get_naruto_duel_ratings(20)
    if not rows:
        return "🍥 Пока никто не дрался в Naruto duel. Жми /duel!"

    lines = ["🍥 <b>Naruto Duel — рейтинг</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, wins, draws, losses, points, dmg_dealt, dmg_taken) in enumerate(rows, start=1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(
            f"{medal} <b>{name}</b> — <b>{points}</b> очков\n"
            f"   W/D/L: {wins}/{draws}/{losses} | "
            f"⚔️ {dmg_dealt} урона | 💔 {dmg_taken} потеряно HP"
        )
    lines.append("\n<i>Очки: 3 за победу, 1 за ничью</i>")
    return "\n".join(lines)


def register_naruto_duel(dp: Dispatcher) -> None:
    dp.message.middleware(DuelBlockMiddleware())

    @dp.message(Command("naruto_ratings"))
    async def naruto_ratings(message: types.Message):
        await message.reply(_format_naruto_ratings())

    @dp.message(Command("duel"))
    async def duel_challenge(message: types.Message):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("Дuel работает только в группе!")
            return

        user = message.from_user
        if not user:
            return

        chat_id = message.chat.id

        if is_chat_busy(chat_id):
            await message.reply("⏳ Сейчас формируется команда Naruto — duel подождёт.")
            return

        async with _lock:
            if chat_id in _chat_duel:
                await message.reply("⏳ В этом чате уже идёт duel или ждёт принятия!")
                return

            duel = Duel(
                id=uuid.uuid4().hex[:8],
                chat_id=chat_id,
                challenger_id=user.id,
                challenger_name=_user_name(user),
            )
            _duels[duel.id] = duel
            _chat_duel[chat_id] = duel.id
            _touch_duel_activity(duel, user.id)

        _ensure_inactivity_watch(message.bot, duel)

        sent = await message.reply(
            f"⚔️ <b>{duel.challenger_name}</b> вызывает на Naruto duel!\n"
            f"{random.choice(CHALLENGE_LINES)}\n"
            f"Кто первый нажмёт — тот и сражается!",
            reply_markup=_accept_keyboard(duel.id),
        )
        duel.challenge_msg_id = sent.message_id

    @dp.message(Command("otboi"))
    async def duel_cancel(message: types.Message):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("Duel работает только в группе!")
            return

        user = message.from_user
        if not user:
            return

        duel = _get_duel_in_chat(message.chat.id)
        if not duel:
            await message.reply("🍥 В этом чате нет активного duel.")
            return

        if user.id != duel.challenger_id:
            await message.reply(
                "🚫 Отменить duel может только тот, кто вызвал /duel."
            )
            return

        await _cancel_duel(message.bot, duel, _user_name(user))

    @dp.callback_query(F.data.startswith("dac:"))
    async def duel_accept(callback: types.CallbackQuery):
        duel_id = callback.data.split(":", 1)[1]
        duel = _duels.get(duel_id)

        if not duel or duel.phase != "waiting":
            await callback.answer("Вызов уже неактуален", show_alert=True)
            return

        user = callback.from_user
        if user.id == duel.challenger_id:
            await callback.answer("Сам с собой не подерёшься 😂", show_alert=True)
            return

        async with _lock:
            if duel.opponent_id is not None:
                await callback.answer("Кто-то уже принял!", show_alert=True)
                return
            duel.opponent_id = user.id
            duel.opponent_name = _user_name(user)
            duel.phase = "instructions"
            duel.teams[duel.challenger_id] = []
            duel.teams[duel.opponent_id] = []
            _touch_duel_activity(duel, duel.challenger_id)
            _touch_duel_activity(duel, user.id)

        await callback.answer("Ты в duel! Прочитай правила ⚔️")

        if duel.challenge_msg_id and callback.message:
            try:
                await callback.message.edit_text(
                    f"⚔️ Duel начался!\n"
                    f"<b>{duel.challenger_name}</b> 🆚 <b>{duel.opponent_name}</b>\n"
                    f"Оба игрока должны подтвердить правила 👇",
                )
            except Exception:
                pass

        await _safe_send(
            callback.bot,
            duel.chat_id,
            f"🔥 <b>{duel.opponent_name}</b> принял вызов!\n"
            f"<b>{duel.challenger_name}</b> 🆚 <b>{duel.opponent_name}</b>\n"
            f"Сначала прочитайте правила и подтвердите готовность.",
        )
        await _send_instructions(callback.bot, duel)

    @dp.callback_query(F.data.startswith("dir:"))
    async def duel_read_instructions(callback: types.CallbackQuery):
        try:
            _, duel_id, user_id_str = callback.data.split(":")
            user_id = int(user_id_str)
        except ValueError:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        duel = _duels.get(duel_id)
        if not duel or duel.phase != "instructions":
            await callback.answer("Подтверждение уже неактуально", show_alert=True)
            return

        if callback.from_user.id != user_id:
            await callback.answer("Это не твоё подтверждение!", show_alert=True)
            return

        if user_id not in (duel.challenger_id, duel.opponent_id):
            await callback.answer("Ты не участник duel!", show_alert=True)
            return

        if user_id in duel.instructions_read:
            await callback.answer("Ты уже подтвердил!", show_alert=True)
            return

        _touch_duel_activity(duel, user_id)
        duel.instructions_read.add(user_id)
        name = _user_name(callback.from_user)
        await callback.answer("Готов! Ждём соперника...")

        if callback.message:
            try:
                await callback.message.edit_text(
                    f"✅ <b>{name}</b> прочитал правила и готов!",
                )
            except Exception:
                pass

        needed = {duel.challenger_id, duel.opponent_id}
        if not needed.issubset(duel.instructions_read):
            return

        async with _lock:
            if duel.phase != "instructions":
                return

        await _safe_send(
            callback.bot,
            duel.chat_id,
            f"🍥 Оба готовы! Переходим к банам.\n"
            f"<b>{duel.challenger_name}</b> 🆚 <b>{duel.opponent_name}</b>",
        )
        await asyncio.sleep(PICK_DELAY)
        if _duel_aborted(duel):
            return
        await _send_ban_phase(callback.bot, duel)

    @dp.callback_query(F.data.startswith("dpl:"))
    async def duel_pick(callback: types.CallbackQuery):
        try:
            _, duel_id, user_id_str, role_str, opt_str = callback.data.split(":")
            user_id = int(user_id_str)
            role_index = int(role_str)
            opt_index = int(opt_str)
        except ValueError:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        duel = _duels.get(duel_id)
        if not duel or duel.phase != "draft":
            await callback.answer("Дuel уже завершён", show_alert=True)
            return

        if callback.from_user.id != user_id:
            await callback.answer("Это не твой выбор!", show_alert=True)
            return

        if role_index != duel.role_index:
            await callback.answer("Этот раунд уже прошёл", show_alert=True)
            return

        if role_index in duel.picks_done.get(user_id, set()):
            await callback.answer("Ты уже выбрал для этой роли", show_alert=True)
            return

        options = duel.options.get(user_id, {}).get(role_index)
        if not options or opt_index >= len(options):
            await callback.answer("Неверный выбор", show_alert=True)
            return

        _touch_duel_activity(duel, user_id)
        char = options[opt_index]
        slot = _build_slot(char, role_index)
        duel.teams[user_id].append(slot)
        duel.used_names.setdefault(user_id, set()).add(char["name"])
        duel.picks_done.setdefault(user_id, set()).add(role_index)

        reaction = PICK_REACTIONS.get(char["name"], f"Пик: {char['name']}!")
        await callback.answer(reaction, show_alert=len(reaction) > 60)
        if callback.message:
            try:
                await callback.message.edit_text(
                    f"🔒 <b>{_user_name(callback.from_user)}</b> выбрал "
                    f"{_role_label(role_index)} — персонаж скрыт до конца драфта"
                )
            except Exception:
                pass

        if role_index not in duel.picks_done.get(duel.opponent_id, set()):
            return
        if role_index not in duel.picks_done.get(duel.challenger_id, set()):
            return

        async with _lock:
            if duel.phase != "draft" or duel.role_index != role_index:
                return
            duel.role_index += 1
            next_role = duel.role_index

        if next_role >= len(POSITIONS):
            asyncio.create_task(_finish_draft(callback.bot, duel))
        else:
            await asyncio.sleep(PICK_DELAY)
            await _send_draft_round(callback.bot, duel)

    @dp.callback_query(F.data.startswith("drr:"))
    async def duel_reroll(callback: types.CallbackQuery):
        try:
            _, duel_id, user_id_str, role_str = callback.data.split(":")
            user_id = int(user_id_str)
            role_index = int(role_str)
        except ValueError:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        duel = _duels.get(duel_id)
        if not duel or duel.phase != "draft":
            await callback.answer("Драфт уже завершён", show_alert=True)
            return

        if callback.from_user.id != user_id:
            await callback.answer("Это не твой переролл!", show_alert=True)
            return

        if role_index != duel.role_index:
            await callback.answer("Этот раунд уже прошёл", show_alert=True)
            return

        if role_index in duel.picks_done.get(user_id, set()):
            await callback.answer("Ты уже выбрал — поздно рероллить", show_alert=True)
            return

        if duel.rerolls_used.get(user_id):
            await callback.answer("Переролл уже использован!", show_alert=True)
            return

        exclude = duel.used_names.setdefault(user_id, set())
        option_count = 3 if role_index < 3 else 2
        options = _pick_options(
            exclude,
            count=option_count,
            banned=_global_bans(duel),
        )
        duel.options.setdefault(user_id, {})[role_index] = options
        duel.rerolls_used[user_id] = True
        _touch_duel_activity(duel, user_id)

        await callback.answer("🔄 Новые варианты!")
        if callback.message:
            try:
                await callback.message.edit_reply_markup(
                    reply_markup=_pick_keyboard(duel, user_id, role_index, options),
                )
            except Exception:
                pass

    @dp.callback_query(F.data.startswith("dpr:"))
    async def duel_prep_pick(callback: types.CallbackQuery):
        try:
            _, duel_id, user_id_str, kind, value = callback.data.split(":")
            user_id = int(user_id_str)
        except ValueError:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        if kind == "strategy":
            valid = value in STRATEGIES
        elif kind == "item":
            valid = value in ITEMS
        elif kind == "ace":
            valid = value.isdigit() and 0 <= int(value) < len(POSITIONS)
        else:
            valid = False

        if not valid:
            await callback.answer("Неверный выбор", show_alert=True)
            return

        duel = _duels.get(duel_id)
        if not duel or duel.phase != "prep":
            await callback.answer("Фаза подготовки уже прошла", show_alert=True)
            return

        if callback.from_user.id != user_id:
            await callback.answer("Это не твой выбор!", show_alert=True)
            return

        key = _prep_key(user_id, kind)
        if key in duel.prep_choices:
            await callback.answer("Уже выбрано!", show_alert=True)
            return

        if kind == "strategy":
            label = STRATEGIES[value][0]
            done_text = f"✅ <b>{_user_name(callback.from_user)}</b> выбрал: {label}"
        elif kind == "item":
            label = ITEMS[value][0]
            done_text = f"✅ <b>{_user_name(callback.from_user)}</b> выбрал: {label}"
        else:
            label = POSITIONS[int(value)][1]
            done_text = f"🃏 <b>{_user_name(callback.from_user)}</b> — туз выбран (скрыто)"

        _touch_duel_activity(duel, user_id)
        duel.prep_choices[key] = value
        _signal_prep(duel)

        await callback.answer(f"Выбрано: {label}", show_alert=kind == "ace")
        if callback.message:
            try:
                await callback.message.edit_text(done_text)
            except Exception:
                pass

    @dp.callback_query(F.data.startswith("dbn:"))
    async def duel_ban(callback: types.CallbackQuery):
        try:
            _, duel_id, user_id_str, opt_str = callback.data.split(":")
            user_id = int(user_id_str)
            opt_index = int(opt_str)
        except ValueError:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        duel = _duels.get(duel_id)
        if not duel or duel.phase != "ban":
            await callback.answer("Бан уже неактуален", show_alert=True)
            return

        if callback.from_user.id != user_id:
            await callback.answer("Это не твой бан!", show_alert=True)
            return

        if user_id in duel.bans:
            await callback.answer("Ты уже забанил!", show_alert=True)
            return

        options = duel.ban_options.get(user_id)
        if not options or opt_index >= len(options):
            await callback.answer("Неверный выбор", show_alert=True)
            return

        _touch_duel_activity(duel, user_id)
        char = options[opt_index]
        duel.bans[user_id] = char["name"]
        _signal_ban(duel)

        await callback.answer(f"Забанен: {char['name']}")
        if callback.message:
            try:
                await callback.message.edit_text(
                    f"🚫 <b>{_user_name(callback.from_user)}</b> банит <b>{char['name']}</b>",
                )
            except Exception:
                pass

    @dp.callback_query(F.data.startswith("djt:"))
    async def duel_jutsu(callback: types.CallbackQuery):
        try:
            _, duel_id, user_id_str, round_str, jutsu_str = callback.data.split(":")
            user_id = int(user_id_str)
            round_num = int(round_str)
            jutsu_idx = int(jutsu_str)
        except ValueError:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        duel = _duels.get(duel_id)
        if not duel or duel.phase != "battle":
            await callback.answer("Сейчас не время для джутсу", show_alert=True)
            return

        if callback.from_user.id != user_id:
            await callback.answer("Это не твой ход!", show_alert=True)
            return

        if duel.waiting_jutsu_round != round_num:
            await callback.answer("Этот раунд уже сыгран", show_alert=True)
            return

        if user_id in duel.round_jutsu:
            await callback.answer("Ты уже выбрал джутсу!", show_alert=True)
            return

        slot = duel.teams[user_id][round_num - 1]
        if jutsu_idx < 0 or jutsu_idx >= len(slot["jutsu"]):
            await callback.answer("Неверное джутсу", show_alert=True)
            return

        jutsu = slot["jutsu"][jutsu_idx]
        if duel.commander_chakra.get(user_id, 0) < jutsu["chakra"]:
            await callback.answer("Недостаточно чакры!", show_alert=True)
            return

        _touch_duel_activity(duel, user_id)
        duel.commander_chakra[user_id] -= jutsu["chakra"]
        duel.round_jutsu[user_id] = jutsu_idx
        _signal_jutsu(duel, round_num)

        await callback.answer(
            f"Выбрано: {jutsu['name']} (−{jutsu['chakra']}💠)",
            show_alert=True,
        )
        if callback.message:
            try:
                await callback.message.edit_text(
                    f"🔒 <b>{_user_name(callback.from_user)}</b> подготовил джутсу",
                )
            except Exception:
                pass
