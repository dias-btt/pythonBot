import asyncio
import random
import time
import uuid
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import add_score, ensure_user, get_game_count_today, get_score, increment_game_count
from naruto_characters import NARUTO_CHARACTERS

GUESS_TIMEOUT = 20
MAX_ROUNDS_PER_DAY = 5
MAX_ATTEMPTS = 3

POINTS_BY_ATTEMPT = {1: 40, 2: 25, 3: 10}
ROLE_LABELS = {
    "captain": "капитан",
    "vice": "вице",
    "support": "саппорт",
    "healer": "хилер",
    "tank": "танк",
}


@dataclass
class GuessSession:
    session_id: str
    user_id: int
    user_name: str
    chat_id: int
    char_index: int
    hints_shown: int = 0
    attempt: int = 0
    message_id: int = 0
    started_at: int = 0
    resolved: bool = False

    @property
    def character(self) -> dict:
        return NARUTO_CHARACTERS[self.char_index]


_sessions: dict[str, GuessSession] = {}
_user_session: dict[int, str] = {}
_tasks: dict[str, asyncio.Task] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _best_role(char: dict) -> tuple[str, int]:
    ratings = char["ratings"]
    role = max(ratings, key=ratings.get)
    return role, ratings[role]


def _hint_text(session: GuessSession) -> str:
    char = session.character
    hints = []
    if session.hints_shown >= 1:
        hints.append(f"🏘️ Деревня: <b>{char['village']}</b>")
    if session.hints_shown >= 2:
        role, val = _best_role(char)
        hints.append(f"⚔️ Сильнейшая роль: <b>{ROLE_LABELS.get(role, role)}</b> ({val}/100)")
    if session.hints_shown >= 3:
        role, val = _best_role(char)
        low = max(1, val - 15)
        high = min(100, val + 5)
        hints.append(f"📊 Рейтинг роли: <b>{low}–{high}</b>")

    remaining = max(0, GUESS_TIMEOUT - (int(time.time()) - session.started_at))
    hint_block = "\n".join(hints) if hints else "🔮 Первая подсказка скоро..."
    return (
        f"🍥 <b>УГАДАЙ НИНДЗЯ</b>\n\n"
        f"Попытка: <b>{session.attempt + 1}</b>/{MAX_ATTEMPTS}\n"
        f"{hint_block}\n\n"
        f"💡 Подсказок: <b>{session.hints_shown}</b>/3\n"
        f"⏳ Осталось: <b>{remaining}</b> сек."
    )


def _options_keyboard(session: GuessSession) -> InlineKeyboardMarkup:
    correct_idx = session.char_index
    others = [i for i in range(len(NARUTO_CHARACTERS)) if i != correct_idx]
    wrong = random.sample(others, 3)
    options = wrong + [correct_idx]
    random.shuffle(options)
    buttons = []
    for idx in options:
        name = NARUTO_CHARACTERS[idx]["name"]
        short = name if len(name) <= 30 else name[:27] + "..."
        buttons.append(
            [
                InlineKeyboardButton(
                    text=short,
                    callback_data=f"gnja:pick:{session.session_id}:{idx}",
                )
            ]
        )
    if session.hints_shown < 3 and session.attempt < MAX_ATTEMPTS:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="💡 Ещё подсказку",
                    callback_data=f"gnja:hint:{session.session_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _active(user_id: int) -> GuessSession | None:
    sid = _user_session.get(user_id)
    if not sid:
        return None
    s = _sessions.get(sid)
    if not s or s.resolved:
        return None
    return s


def _cleanup(session: GuessSession) -> None:
    session.resolved = True
    _sessions.pop(session.session_id, None)
    _user_session.pop(session.user_id, None)
    task = _tasks.pop(session.session_id, None)
    if task and not task.done():
        task.cancel()


async def _edit(bot: Bot, session: GuessSession, text: str, markup=None) -> None:
    if not session.chat_id or not session.message_id:
        return
    try:
        await bot.edit_message_text(
            text, chat_id=session.chat_id, message_id=session.message_id, reply_markup=markup
        )
    except Exception:
        pass


async def _finish(bot: Bot, session: GuessSession, won: bool, points: int, reason: str) -> None:
    if session.resolved:
        return
    if won and points > 0:
        add_score(session.user_id, points)
    total = get_score(session.user_id)
    _cleanup(session)
    sign = f"➕ <b>+{points}</b>" if won else "➕ <b>0</b>"
    await _edit(
        bot,
        session,
        f"🍥 <b>РАУНД ОКОНЧЕН</b>\n\n"
        f"{reason}\n\n"
        f"Ниндзя: <b>{session.character['name']}</b>\n"
        f"{sign} баллов\n"
        f"🏦 Баланс: <b>{total}</b>",
        None,
    )


async def _countdown(bot: Bot, session: GuessSession) -> None:
    try:
        while not session.resolved:
            if int(time.time()) - session.started_at >= GUESS_TIMEOUT:
                await _finish(
                    bot,
                    session,
                    False,
                    0,
                    "⏰ <b>Время вышло!</b> Ниндзя ушёл в дымовую завесу.",
                )
                return
            if session.hints_shown < 1:
                session.hints_shown = 1
            await _edit(bot, session, _hint_text(session), _options_keyboard(session))
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


def register_guess_ninja(dp: Dispatcher) -> None:
    @dp.message(Command("guess_ninja"))
    async def guess_cmd(message: types.Message):
        user = message.from_user
        if not user:
            return

        args = (message.text or "").split(maxsplit=1)
        if len(args) > 1 and args[1].lower() in ("help", "?", "помощь"):
            await message.reply(
                "🍥 <b>УГАДАЙ НИНДЗЯ</b>\n\n"
                "<code>/guess_ninja</code> — новый раунд\n\n"
                f"• <b>{MAX_ROUNDS_PER_DAY}</b> раундов в день\n"
                f"• <b>{MAX_ATTEMPTS}</b> попытки, <b>{GUESS_TIMEOUT} сек</b> на раунд\n"
                f"• 1-я попытка: +40 | 2-я: +25 | 3-я: +10\n"
                "• Кнопка «Ещё подсказку» — до 3 подсказок"
            )
            return

        if _active(user.id):
            await message.reply("⏳ Раунд уже идёт — жми кнопки выше.")
            return

        if get_game_count_today(user.id, "guess_ninja") >= MAX_ROUNDS_PER_DAY:
            await message.reply(
                f"🚫 Лимит раундов на сегодня: <b>{MAX_ROUNDS_PER_DAY}/{MAX_ROUNDS_PER_DAY}</b>"
            )
            return

        ensure_user(user.id, _user_name(user))
        increment_game_count(user.id, "guess_ninja")

        session_id = uuid.uuid4().hex[:8]
        char_index = random.randrange(len(NARUTO_CHARACTERS))
        session = GuessSession(
            session_id=session_id,
            user_id=user.id,
            user_name=_user_name(user),
            chat_id=message.chat.id,
            char_index=char_index,
            started_at=int(time.time()),
        )
        _sessions[session_id] = session
        _user_session[user.id] = session_id

        sent = await message.reply(_hint_text(session), reply_markup=_options_keyboard(session))
        session.message_id = sent.message_id
        _tasks[session_id] = asyncio.create_task(_countdown(message.bot, session))

    @dp.callback_query(F.data.startswith("gnja:"))
    async def guess_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":", 3)
        if len(parts) < 3:
            await callback.answer("Ошибка", show_alert=True)
            return

        action = parts[1]
        session_id = parts[2]
        session = _sessions.get(session_id)
        if not session or session.resolved:
            await callback.answer("Раунд завершён", show_alert=True)
            return

        if callback.from_user.id != session.user_id:
            await callback.answer("Это не твоя игра!", show_alert=True)
            return

        if action == "hint":
            if session.hints_shown >= 3:
                await callback.answer("Подсказок больше нет")
                return
            session.hints_shown += 1
            await callback.answer("Подсказка!")
            await _edit(callback.bot, session, _hint_text(session), _options_keyboard(session))
            return

        if action == "pick" and len(parts) == 4:
            try:
                picked_idx = int(parts[3])
            except ValueError:
                await callback.answer("Ошибка", show_alert=True)
                return
            if picked_idx < 0 or picked_idx >= len(NARUTO_CHARACTERS):
                await callback.answer("Ошибка", show_alert=True)
                return

            correct_idx = session.char_index
            picked = NARUTO_CHARACTERS[picked_idx]["name"]
            correct = session.character["name"]
            session.attempt += 1

            if picked_idx == correct_idx:
                points = POINTS_BY_ATTEMPT.get(session.attempt, 10)
                task = _tasks.pop(session_id, None)
                if task and not task.done():
                    task.cancel()
                await callback.answer(f"✅ Верно! +{points}")
                await _finish(
                    callback.bot,
                    session,
                    True,
                    points,
                    f"✅ <b>Угадал с {session.attempt}-й попытки!</b>",
                )
                return

            if session.attempt >= MAX_ATTEMPTS:
                task = _tasks.pop(session_id, None)
                if task and not task.done():
                    task.cancel()
                await callback.answer("❌ Попытки кончились")
                await _finish(
                    callback.bot,
                    session,
                    False,
                    0,
                    f"❌ <b>Три промаха.</b> Ты выбрал: <b>{picked}</b>",
                )
                return

            await callback.answer("❌ Неверно, ещё попытка")
            session.started_at = int(time.time())
            await _edit(
                callback.bot,
                session,
                f"❌ <b>Не то!</b> Осталось попыток: <b>{MAX_ATTEMPTS - session.attempt}</b>\n\n"
                + _hint_text(session),
                _options_keyboard(session),
            )
            return

        await callback.answer("Неизвестное действие", show_alert=True)
