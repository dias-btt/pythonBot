import asyncio
import random
import re
import time
import uuid
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import add_score, ensure_user, get_game_count_today, get_score, increment_game_count

CHOICE_TIMEOUT = 15
MIN_STAKE = 5
MAX_STAKE = 300
MAX_PLAYS_PER_DAY = 8

PAYOUT_HIGH_LOW = 1.6
PAYOUT_EXACT = 4.5

DICE_EMOJI = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

ROLL_LINES = [
    "🎲 Кубик катится по столу бара...",
    "🍺 Кости пьяного судьбы решают!",
    "💀 Секунда тишины — и бросок!",
]


@dataclass
class DiceSession:
    session_id: str
    user_id: int
    user_name: str
    chat_id: int
    stake: int
    message_id: int = 0
    phase: str = "mode"
    started_at: int = 0
    resolved: bool = False


_sessions: dict[str, DiceSession] = {}
_user_session: dict[int, str] = {}
_tasks: dict[str, asyncio.Task] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _active_session(user_id: int) -> DiceSession | None:
    sid = _user_session.get(user_id)
    if not sid:
        return None
    s = _sessions.get(sid)
    if not s or s.resolved:
        return None
    if time.time() - s.started_at > CHOICE_TIMEOUT:
        return None
    return s


def _cleanup(session: DiceSession) -> None:
    session.resolved = True
    _sessions.pop(session.session_id, None)
    _user_session.pop(session.user_id, None)
    task = _tasks.pop(session.session_id, None)
    if task and not task.done():
        task.cancel()


def _mode_keyboard(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬆️ Выше 3", callback_data=f"dice:hi:{session_id}"),
                InlineKeyboardButton(text="⬇️ Ниже 4", callback_data=f"dice:lo:{session_id}"),
            ],
            [
                InlineKeyboardButton(text="🎯 Точное число", callback_data=f"dice:ex:{session_id}"),
            ],
        ]
    )


def _exact_keyboard(session_id: str) -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton(text=f"{DICE_EMOJI[i]} {i}", callback_data=f"dice:n:{session_id}:{i}")
        for i in range(1, 4)
    ]
    row2 = [
        InlineKeyboardButton(text=f"{DICE_EMOJI[i]} {i}", callback_data=f"dice:n:{session_id}:{i}")
        for i in range(4, 7)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def _mode_text(session: DiceSession) -> str:
    remaining = max(0, CHOICE_TIMEOUT - (int(time.time()) - session.started_at))
    return (
        f"🎲 <b>КОСТИ</b>\n\n"
        f"Игрок: <b>{session.user_name}</b>\n"
        f"💰 Ставка: <b>{session.stake}</b> баллов\n\n"
        f"⬆️ <b>Выше 3</b> (4–6) — выигрыш ×{PAYOUT_HIGH_LOW}\n"
        f"⬇️ <b>Ниже 4</b> (1–3) — выигрыш ×{PAYOUT_HIGH_LOW}\n"
        f"🎯 <b>Точное</b> — выигрыш ×{PAYOUT_EXACT}\n\n"
        f"⏳ Осталось: <b>{remaining}</b> сек."
    )


async def _edit(bot: Bot, session: DiceSession, text: str, markup=None) -> None:
    if not session.chat_id or not session.message_id:
        return
    try:
        await bot.edit_message_text(
            text, chat_id=session.chat_id, message_id=session.message_id, reply_markup=markup
        )
    except Exception:
        pass


def _resolve_roll(session: DiceSession, mode: str, exact: int | None = None) -> tuple[bool, int, str]:
    roll = random.randint(1, 6)
    emoji = DICE_EMOJI[roll]

    if mode == "hi":
        won = roll > 3
        bet_desc = "выше 3"
    elif mode == "lo":
        won = roll < 4
        bet_desc = "ниже 4"
    else:
        won = roll == exact
        bet_desc = f"число {exact}"

    if won:
        mult = PAYOUT_EXACT if mode == "ex" else PAYOUT_HIGH_LOW
        payout = int(session.stake * mult)
        profit = payout - session.stake
        add_score(session.user_id, profit)
        total = get_score(session.user_id)
        text = (
            f"🎲 <b>ПОБЕДА!</b>\n\n"
            f"{random.choice(ROLL_LINES)}\n\n"
            f"Выпало: <b>{emoji} {roll}</b> (ставка: {bet_desc})\n"
            f"➕ <b>+{profit}</b> баллов (×{mult})\n"
            f"🏦 Баланс: <b>{total}</b>"
        )
    else:
        add_score(session.user_id, -session.stake)
        total = get_score(session.user_id)
        text = (
            f"🎲 <b>ПРОИГРЫШ</b>\n\n"
            f"{random.choice(ROLL_LINES)}\n\n"
            f"Выпало: <b>{emoji} {roll}</b> (ставка: {bet_desc})\n"
            f"➖ <b>-{session.stake}</b> баллов\n"
            f"🏦 Баланс: <b>{total}</b>"
        )

    return won, roll, text


async def _countdown(bot: Bot, session: DiceSession) -> None:
    try:
        while not session.resolved:
            if int(time.time()) - session.started_at >= CHOICE_TIMEOUT:
                _cleanup(session)
                await _edit(
                    bot,
                    session,
                    f"⏰ <b>Время вышло!</b>\n\n"
                    f"<b>{session.user_name}</b>, ты не успел — ставка не снята.",
                    None,
                )
                return
            markup = _exact_keyboard(session.session_id) if session.phase == "exact" else _mode_keyboard(session.session_id)
            await _edit(bot, session, _mode_text(session), markup)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


def register_dice(dp: Dispatcher) -> None:
    @dp.message(Command("dice"))
    async def dice_cmd(message: types.Message, command: CommandObject):
        user = message.from_user
        if not user:
            return

        args = (command.args or "").strip()
        if args.lower() in ("help", "?", "помощь"):
            await message.reply(
                "🎲 <b>КОСТИ</b>\n\n"
                f"<code>/dice 50</code> — ставка 50 баллов\n\n"
                f"• Ставка: <b>{MIN_STAKE}–{MAX_STAKE}</b>\n"
                f"• Лимит: <b>{MAX_PLAYS_PER_DAY}</b> игр в день\n"
                f"• На выбор: <b>{CHOICE_TIMEOUT} сек</b>\n"
                f"• Выше 3 / Ниже 4 — ×{PAYOUT_HIGH_LOW}\n"
                f"• Точное число — ×{PAYOUT_EXACT}"
            )
            return

        if _active_session(user.id):
            await message.reply("⏳ У тебя уже идёт бросок. Жми кнопки в сообщении выше.")
            return

        if get_game_count_today(user.id, "dice") >= MAX_PLAYS_PER_DAY:
            await message.reply(
                f"🚫 Лимит костей на сегодня: <b>{MAX_PLAYS_PER_DAY}/{MAX_PLAYS_PER_DAY}</b>"
            )
            return

        match = re.search(r"\d+", args)
        if not match:
            await message.reply(
                f"💰 Укажи ставку: <code>/dice 50</code>\n"
                f"От <b>{MIN_STAKE}</b> до <b>{MAX_STAKE}</b>. Справка: <code>/dice help</code>"
            )
            return

        stake = int(match.group())
        ensure_user(user.id, _user_name(user))
        score = get_score(user.id)

        if stake < MIN_STAKE or stake > MAX_STAKE:
            await message.reply(f"🚫 Ставка от <b>{MIN_STAKE}</b> до <b>{MAX_STAKE}</b>.")
            return
        if stake > score:
            await message.reply(f"🚫 Не хватает баллов. У тебя <b>{score}</b>.")
            return

        increment_game_count(user.id, "dice")

        session_id = uuid.uuid4().hex[:8]
        session = DiceSession(
            session_id=session_id,
            user_id=user.id,
            user_name=_user_name(user),
            chat_id=message.chat.id,
            stake=stake,
            started_at=int(time.time()),
        )
        _sessions[session_id] = session
        _user_session[user.id] = session_id

        sent = await message.reply(_mode_text(session), reply_markup=_mode_keyboard(session_id))
        session.message_id = sent.message_id
        _tasks[session_id] = asyncio.create_task(_countdown(message.bot, session))

    @dp.callback_query(F.data.startswith("dice:"))
    async def dice_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("Ошибка", show_alert=True)
            return

        action = parts[1]
        session_id = parts[2]
        session = _sessions.get(session_id)
        if not session or session.resolved:
            await callback.answer("Сессия неактуальна", show_alert=True)
            return

        if callback.from_user.id != session.user_id:
            await callback.answer("Это не твоя игра!", show_alert=True)
            return

        if time.time() - session.started_at > CHOICE_TIMEOUT:
            await callback.answer("Время вышло", show_alert=True)
            return

        task = _tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

        if action == "ex":
            session.phase = "exact"
            session.started_at = int(time.time())
            await callback.answer("Выбери число")
            await _edit(callback.bot, session, _mode_text(session), _exact_keyboard(session_id))
            _tasks[session_id] = asyncio.create_task(_countdown(callback.bot, session))
            return

        if action == "n" and len(parts) == 4:
            exact = int(parts[3])
            _, _, text = _resolve_roll(session, "ex", exact)
            _cleanup(session)
            await callback.answer("Бросок!")
            await _edit(callback.bot, session, text, None)
            return

        if action in ("hi", "lo"):
            mode = "hi" if action == "hi" else "lo"
            _, _, text = _resolve_roll(session, mode)
            _cleanup(session)
            await callback.answer("Бросок!")
            await _edit(callback.bot, session, text, None)
            return

        await callback.answer("Неизвестное действие", show_alert=True)
