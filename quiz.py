import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import add_score, ensure_user, get_game_count_today, get_score, increment_game_count
from naruto_characters import NARUTO_CHARACTERS

QUESTION_TIMEOUT = 20
QUESTIONS_PER_QUIZ = 5
MAX_QUIZZES_PER_DAY = 1

POINTS_BY_INDEX = [10, 15, 20, 25, 30]

QUIZ_POOL = [
    {
        "q": "Какой напиток в боте даёт штрафные баллы?",
        "options": ["Пиво", "Коньяк", "Шампанское", "Соджу"],
        "answer": 1,
        "hint": "Дорогое — не всегда выгодно",
    },
    {
        "q": "Сколько секунд кулдаун у /alyp_koyaik?",
        "options": ["30 мин", "1 час", "2 часа", "15 мин"],
        "answer": 1,
        "hint": "Терпение, алкаш...",
    },
    {
        "q": "Какой персонаж в базе из деревни Кайнар?",
        "options": ["Наруто Узумаки", "Малик Жалмурзин", "Гаара", "Джирайя"],
        "answer": 1,
        "hint": "Легенда чата",
    },
    {
        "q": "Сколько игроков максимум в русской рулетке?",
        "options": ["4", "5", "6", "8"],
        "answer": 2,
        "hint": "Шесть камор револьвера",
    },
    {
        "q": "Какой режим питья — только крепкое?",
        "options": ["legko", "zal", "tyazhelo", "ruletka"],
        "answer": 1,
        "hint": "Залп!",
    },
    {
        "q": "У кого из героев лучший рейтинг healer?",
        "options": ["Сакура Харуно", "Цунаде", "Кабуто", "Карин"],
        "answer": 1,
        "hint": "Пятая Хокаге",
    },
    {
        "q": "Сколько краж /steal можно в день?",
        "options": ["1", "2", "3", "5"],
        "answer": 1,
        "hint": "Вор не жадничай",
    },
    {
        "q": "Какая деревня у Мадара Учиха?",
        "options": ["Суна", "Коноха", "Кири", "Кумо"],
        "answer": 1,
        "hint": "Листовая деревня",
    },
    {
        "q": "Что делает /alyp_koyaik vabank при проигрыше?",
        "options": ["−50% баллов", "Обнуляет баллы", "−100 баллов", "Ничего"],
        "answer": 1,
        "hint": "Всё или ничего",
    },
    {
        "q": "Сколько ролей в драфте Naruto duel?",
        "options": ["4", "5", "6", "7"],
        "answer": 2,
        "hint": "Полная команда",
    },
    {
        "q": "Какой коктейль даёт +15 mult в питье?",
        "options": ["Алматы Ночь", "Малик Special", "За дружбу", "Квас"],
        "answer": 1,
        "hint": "Именной",
    },
    {
        "q": "Кто из Акацуки — танк с рейтингом 88?",
        "options": ["Дейдара", "Кисаме", "Сасори", "Хидан"],
        "answer": 1,
        "hint": "Акула",
    },
]


def _build_pool() -> list[dict]:
    pool = list(QUIZ_POOL)
    chars = random.sample(NARUTO_CHARACTERS, min(5, len(NARUTO_CHARACTERS)))
    for ch in chars:
        village = ch["village"]
        wrong = random.sample(
            [c["village"] for c in NARUTO_CHARACTERS if c["village"] != village],
            3,
        )
        options = wrong + [village]
        random.shuffle(options)
        pool.append(
            {
                "q": f"Из какой деревни <b>{ch['name']}</b>?",
                "options": options,
                "answer": options.index(village),
                "hint": "Смотри внимательно на лор",
            }
        )
    return pool


@dataclass
class QuizSession:
    session_id: str
    user_id: int
    user_name: str
    chat_id: int
    questions: list[dict] = field(default_factory=list)
    index: int = 0
    correct_count: int = 0
    score_earned: int = 0
    message_id: int = 0
    question_started_at: int = 0
    resolved: bool = False


_sessions: dict[str, QuizSession] = {}
_user_session: dict[int, str] = {}
_tasks: dict[str, asyncio.Task] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _active(user_id: int) -> QuizSession | None:
    sid = _user_session.get(user_id)
    if not sid:
        return None
    s = _sessions.get(sid)
    if not s or s.resolved:
        return None
    return s


def _cleanup(session: QuizSession) -> None:
    session.resolved = True
    _sessions.pop(session.session_id, None)
    _user_session.pop(session.user_id, None)
    task = _tasks.pop(session.session_id, None)
    if task and not task.done():
        task.cancel()


def _keyboard(session: QuizSession) -> InlineKeyboardMarkup:
    q = session.questions[session.index]
    buttons = []
    for i, opt in enumerate(q["options"]):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=opt,
                    callback_data=f"quiz:ans:{session.session_id}:{i}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _question_text(session: QuizSession) -> str:
    q = session.questions[session.index]
    remaining = max(0, QUESTION_TIMEOUT - (int(time.time()) - session.question_started_at))
    return (
        f"🧠 <b>ВИКТОРИНА</b> — вопрос {session.index + 1}/{QUESTIONS_PER_QUIZ}\n\n"
        f"{q['q']}\n\n"
        f"🏆 За этот: <b>+{POINTS_BY_INDEX[session.index]}</b> баллов\n"
        f"💰 Набрано: <b>{session.score_earned}</b>\n"
        f"⏳ Осталось: <b>{remaining}</b> сек."
    )


async def _edit(bot: Bot, session: QuizSession, text: str, markup=None) -> None:
    if not session.chat_id or not session.message_id:
        return
    try:
        await bot.edit_message_text(
            text, chat_id=session.chat_id, message_id=session.message_id, reply_markup=markup
        )
    except Exception:
        pass


async def _finish(bot: Bot, session: QuizSession, reason: str = "") -> None:
    if session.resolved:
        return
    if session.score_earned > 0:
        add_score(session.user_id, session.score_earned)
    total = get_score(session.user_id)
    _cleanup(session)
    extra = f"\n\n<i>{reason}</i>" if reason else ""
    await _edit(
        bot,
        session,
        f"🧠 <b>ВИКТОРИНА ЗАВЕРШЕНА!</b>\n\n"
        f"Правильных: <b>{session.correct_count}</b> из {QUESTIONS_PER_QUIZ}\n"
        f"➕ Заработано: <b>{session.score_earned}</b> баллов\n"
        f"🏦 Баланс: <b>{total}</b>{extra}",
        None,
    )


async def _next_or_finish(bot: Bot, session: QuizSession) -> None:
    session.index += 1
    if session.index >= QUESTIONS_PER_QUIZ:
        await _finish(bot, session)
        return
    session.question_started_at = int(time.time())
    await _edit(bot, session, _question_text(session), _keyboard(session))


async def _timeout_watch(bot: Bot, session: QuizSession) -> None:
    try:
        while not session.resolved and session.index < QUESTIONS_PER_QUIZ:
            if int(time.time()) - session.question_started_at >= QUESTION_TIMEOUT:
                q = session.questions[session.index]
                correct = q["options"][q["answer"]]
                await _edit(
                    bot,
                    session,
                    f"⏰ <b>Время вышло!</b>\n\n"
                    f"Правильно: <b>{correct}</b>\n"
                    f"<i>{q.get('hint', '')}</i>",
                    None,
                )
                await asyncio.sleep(2)
                await _next_or_finish(bot, session)
                if session.resolved:
                    return
                continue
            await _edit(bot, session, _question_text(session), _keyboard(session))
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


def register_quiz(dp: Dispatcher) -> None:
    @dp.message(Command("quiz"))
    async def quiz_cmd(message: types.Message):
        user = message.from_user
        if not user:
            return

        args = (message.text or "").split(maxsplit=1)
        if len(args) > 1 and args[1].lower() in ("help", "?", "помощь"):
            await message.reply(
                "🧠 <b>ВИКТОРИНА</b>\n\n"
                "<code>/quiz</code> — начать викторину\n\n"
                f"• <b>{QUESTIONS_PER_QUIZ}</b> вопросов за сессию\n"
                f"• <b>{MAX_QUIZZES_PER_DAY}</b> раз в день\n"
                f"• <b>{QUESTION_TIMEOUT} сек</b> на ответ\n"
                f"• Баллы: +10, +15, +20, +25, +30 за вопросы"
            )
            return

        if _active(user.id):
            await message.reply("⏳ Викторина уже идёт — жми кнопки выше.")
            return

        if get_game_count_today(user.id, "quiz") >= MAX_QUIZZES_PER_DAY:
            await message.reply(
                f"🚫 Викторина уже пройдена сегодня ({MAX_QUIZZES_PER_DAY}/день).\n"
                "Завтра новые вопросы!"
            )
            return

        ensure_user(user.id, _user_name(user))
        increment_game_count(user.id, "quiz")

        pool = _build_pool()
        questions = random.sample(pool, QUESTIONS_PER_QUIZ)

        session_id = uuid.uuid4().hex[:8]
        session = QuizSession(
            session_id=session_id,
            user_id=user.id,
            user_name=_user_name(user),
            chat_id=message.chat.id,
            questions=questions,
            question_started_at=int(time.time()),
        )
        _sessions[session_id] = session
        _user_session[user.id] = session_id

        sent = await message.reply(_question_text(session), reply_markup=_keyboard(session))
        session.message_id = sent.message_id
        _tasks[session_id] = asyncio.create_task(_timeout_watch(message.bot, session))

    @dp.callback_query(F.data.startswith("quiz:ans:"))
    async def quiz_answer(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) != 4:
            await callback.answer("Ошибка", show_alert=True)
            return

        session_id = parts[2]
        try:
            choice = int(parts[3])
        except ValueError:
            await callback.answer("Ошибка", show_alert=True)
            return

        session = _sessions.get(session_id)
        if not session or session.resolved:
            await callback.answer("Викторина завершена", show_alert=True)
            return

        if callback.from_user.id != session.user_id:
            await callback.answer("Это не твоя викторина!", show_alert=True)
            return

        if int(time.time()) - session.question_started_at > QUESTION_TIMEOUT:
            await callback.answer("Время вышло", show_alert=True)
            return

        q = session.questions[session.index]
        correct_idx = q["answer"]
        points = POINTS_BY_INDEX[session.index]

        if choice == correct_idx:
            session.correct_count += 1
            session.score_earned += points
            await callback.answer(f"✅ Верно! +{points}")
            await _edit(
                callback.bot,
                session,
                f"✅ <b>Правильно!</b> +{points} баллов\n\n"
                f"Ответ: <b>{q['options'][correct_idx]}</b>",
                None,
            )
        else:
            await callback.answer("❌ Неверно")
            await _edit(
                callback.bot,
                session,
                f"❌ <b>Неверно!</b>\n\n"
                f"Ты: <b>{q['options'][choice]}</b>\n"
                f"Верно: <b>{q['options'][correct_idx]}</b>\n"
                f"<i>{q.get('hint', '')}</i>",
                None,
            )

        await asyncio.sleep(1.5)
        await _next_or_finish(callback.bot, session)
