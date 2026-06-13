import asyncio
import random
import re
import time
import uuid
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import MessageEntityType
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import ensure_user, find_user_id_by_username, get_score, get_steal_count_today, increment_steal_count, transfer_score

STEAL_TIMEOUT = 30
MAX_STEALS_PER_DAY = 2

STEAL_START_LINES = [
    "🦹 Кто-то полез в карман за баллами...",
    "👀 Тихо... в чате завелся ворюга.",
    "🎭 Кража века начинается. Жертва спит?",
    "🐀 Баллы алкаша никто не дрался — пока.",
]

STEAL_SUCCESS_LINES = [
    "💰 Слил тихо, как профи. Жертва даже не моргнула.",
    "🦹 Кража удалась — телефон молчал, баллы ушли.",
    "😈 Пока он AFK, ты уже в плюсе.",
    "🍺 Украденное пойдёт на залп. Классика.",
]

STEAL_FAIL_LINES = [
    "🛡️ Поймали за руку! Штраф переведён жертве.",
    "👊 Жертва была начеку — ты сам отдал баллы.",
    "🚨 Тревога! Вор вернул всё с процентами болью.",
    "🤡 Попытался стырить — остался без штанов.",
]

PRESSURE_LINES = {
    20: "⚡ Жертва, ты там жив?",
    12: "🔥 Скоро уведут баллы — жми кнопку!",
    6: "💀 ПОСЛЕДНИЕ СЕКУНДЫ! ЖМИ 🛡️!",
}


@dataclass
class StealAttempt:
    steal_id: str
    chat_id: int
    attacker_id: int
    attacker_name: str
    victim_id: int
    victim_name: str
    amount: int
    message_id: int = 0
    started_at: int = 0
    resolved: bool = False


_steals: dict[str, StealAttempt] = {}
_user_steal: dict[int, str] = {}
_tasks: dict[str, asyncio.Task] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _active_steal_for(user_id: int) -> StealAttempt | None:
    steal_id = _user_steal.get(user_id)
    if not steal_id:
        return None
    attempt = _steals.get(steal_id)
    if not attempt or attempt.resolved:
        return None
    if time.time() - attempt.started_at > STEAL_TIMEOUT:
        return None
    return attempt


def _cleanup(attempt: StealAttempt) -> None:
    attempt.resolved = True
    _steals.pop(attempt.steal_id, None)
    _user_steal.pop(attempt.attacker_id, None)
    _user_steal.pop(attempt.victim_id, None)
    task = _tasks.pop(attempt.steal_id, None)
    if task and not task.done():
        task.cancel()


def _defend_keyboard(steal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛡️ ПОЙМАЛ!",
                    callback_data=f"stl:defend:{steal_id}",
                )
            ]
        ]
    )


def _steal_text(attempt: StealAttempt) -> str:
    remaining = max(0, STEAL_TIMEOUT - (int(time.time()) - attempt.started_at))
    pressure = ""
    for threshold, line in sorted(PRESSURE_LINES.items(), reverse=True):
        if remaining <= threshold:
            pressure = f"\n{line}"
            break
    return (
        f"🦹 <b>КРАЖА БАЛЛОВ</b>\n\n"
        f"{random.choice(STEAL_START_LINES)}\n\n"
        f"👤 Вор: <b>{attempt.attacker_name}</b>\n"
        f"🎯 Жертва: <b>{attempt.victim_name}</b>\n"
        f"💰 Сумма: <b>{attempt.amount}</b> баллов\n\n"
        f"<b>{attempt.victim_name}</b>, жми 🛡️ или потеряешь баллы!\n"
        f"⏳ Осталось: <b>{remaining}</b> сек.{pressure}"
    )


async def _edit_steal(bot: Bot, attempt: StealAttempt, text: str, markup=None) -> None:
    if not attempt.chat_id or not attempt.message_id:
        return
    try:
        await bot.edit_message_text(
            text,
            chat_id=attempt.chat_id,
            message_id=attempt.message_id,
            reply_markup=markup,
        )
    except Exception:
        pass


async def _resolve_success(bot: Bot, attempt: StealAttempt) -> None:
    if attempt.resolved:
        return
    transferred = transfer_score(attempt.victim_id, attempt.attacker_id, attempt.amount)
    _cleanup(attempt)
    if transferred <= 0:
        final = (
            f"🦹 <b>Кража провалилась</b>\n\n"
            f"У <b>{attempt.victim_name}</b> нечего забирать."
        )
    else:
        attacker_total = get_score(attempt.attacker_id)
        victim_total = get_score(attempt.victim_id)
        final = (
            f"🦹 <b>КРАЖА УДАЛАСЬ!</b>\n\n"
            f"{random.choice(STEAL_SUCCESS_LINES)}\n\n"
            f"💸 <b>{attempt.attacker_name}</b> стащил <b>{transferred}</b> баллов\n"
            f"🏦 Вор: <b>{attacker_total}</b> | Жертва: <b>{victim_total}</b>"
        )
    await _edit_steal(bot, attempt, final, None)


async def _resolve_defend(bot: Bot, attempt: StealAttempt) -> None:
    if attempt.resolved:
        return
    transferred = transfer_score(attempt.attacker_id, attempt.victim_id, attempt.amount)
    _cleanup(attempt)
    if transferred <= 0:
        final = (
            f"🛡️ <b>Жертва среагировала!</b>\n\n"
            f"Но у <b>{attempt.attacker_name}</b> нечего отдавать."
        )
    else:
        attacker_total = get_score(attempt.attacker_id)
        victim_total = get_score(attempt.victim_id)
        final = (
            f"🛡️ <b>ПОЙМАЛ!</b>\n\n"
            f"{random.choice(STEAL_FAIL_LINES)}\n\n"
            f"💸 <b>{attempt.attacker_name}</b> потерял <b>{transferred}</b> баллов\n"
            f"🏦 Вор: <b>{attacker_total}</b> | Жертва: <b>{victim_total}</b>"
        )
    await _edit_steal(bot, attempt, final, None)


async def _steal_countdown(bot: Bot, attempt: StealAttempt) -> None:
    try:
        while not attempt.resolved:
            elapsed = int(time.time()) - attempt.started_at
            if elapsed >= STEAL_TIMEOUT:
                await _resolve_success(bot, attempt)
                return
            await _edit_steal(
                bot,
                attempt,
                _steal_text(attempt),
                _defend_keyboard(attempt.steal_id),
            )
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


async def _resolve_target(
    message: types.Message,
    args_text: str,
) -> types.User | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    if message.entities:
        for entity in message.entities:
            if entity.type == MessageEntityType.TEXT_MENTION and entity.user:
                return entity.user

    tokens = args_text.split()
    for token in tokens:
        if token.startswith("@"):
            username = token[1:]
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.MENTION:
                        mention = message.text[entity.offset : entity.offset + entity.length]
                        if mention.lower() == token.lower():
                            user_id = find_user_id_by_username(username)
                            if user_id:
                                try:
                                    member = await message.bot.get_chat_member(
                                        message.chat.id, user_id
                                    )
                                    return member.user
                                except Exception:
                                    return types.User(id=user_id, is_bot=False, first_name=username)
            user_id = find_user_id_by_username(username)
            if user_id:
                try:
                    member = await message.bot.get_chat_member(message.chat.id, user_id)
                    return member.user
                except Exception:
                    return types.User(id=user_id, is_bot=False, first_name=username)

    return None


def _parse_amount(args_text: str, attacker_score: int, victim_score: int) -> int | None:
    tokens = args_text.split()
    numbers = []
    for token in tokens:
        if token.startswith("@"):
            continue
        if re.fullmatch(r"\d+", token):
            numbers.append(int(token))

    if not numbers:
        return min(attacker_score, victim_score)

    amount = numbers[-1]
    if amount < 1 or amount > attacker_score:
        return None
    return min(amount, victim_score)


def register_steal(dp: Dispatcher) -> None:
    @dp.message(Command("steal"))
    async def steal_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("🦹 Кража работает только в группе!")
            return

        attacker = message.from_user
        if not attacker:
            return

        args_text = (command.args or "").strip()
        if args_text.lower() in ("help", "?", "помощь"):
            await message.reply(
                "🦹 <b>КРАЖА БАЛЛОВ</b>\n\n"
                "<code>/steal @user</code> — стырить максимум (до твоего баланса)\n"
                "<code>/steal @user 500</code> — стырить 500 баллов\n"
                "<code>/steal 500</code> — ответом на сообщение жертвы\n\n"
                "• Украсть можно от <b>1</b> до <b>твоего баланса</b>\n"
                "• Максимум <b>2 кражи в день</b>\n"
                "• Жертва <b>30 сек</b> жмёт 🛡️ — и ты теряешь сумму\n"
                "• Не ответила — она теряет, ты забираешь"
            )
            return

        victim = await _resolve_target(message, args_text)
        if not victim:
            await message.reply(
                "🎯 Укажи жертву: <code>/steal @user</code> или ответом на сообщение.\n"
                "Справка: <code>/steal help</code>"
            )
            return

        if victim.is_bot:
            await message.reply("🤖 У ботов нечего красть.")
            return

        if victim.id == attacker.id:
            await message.reply("🪞 Себя стырить? Попробуй /alyp_koyaik vabank.")
            return

        ensure_user(attacker.id, _user_name(attacker))
        ensure_user(victim.id, _user_name(victim))

        if _active_steal_for(attacker.id) or _active_steal_for(victim.id):
            await message.reply("⏳ У тебя или жертвы уже идёт кража. Дождись результата.")
            return

        steals_today = get_steal_count_today(attacker.id)
        if steals_today >= MAX_STEALS_PER_DAY:
            await message.reply(
                f"🚫 Лимит краж на сегодня исчерпан (<b>{MAX_STEALS_PER_DAY}/{MAX_STEALS_PER_DAY}</b>).\n"
                "Завтра снова можно стырить."
            )
            return

        attacker_score = get_score(attacker.id)
        victim_score = get_score(victim.id)

        if attacker_score < 1:
            await message.reply("🚫 Нечего рисковать — сначала набери баллы выпивкой.")
            return

        if victim_score < 1:
            await message.reply(
                f"🚫 У <b>{_user_name(victim)}</b> пустой карман — красть нечего."
            )
            return

        amount = _parse_amount(args_text, attacker_score, victim_score)
        if amount is None:
            await message.reply(
                f"🚫 Сумма от <b>1</b> до <b>{attacker_score}</b> баллов.\n"
                f"Пример: <code>/steal @{victim.username or 'user'} 500</code>"
                if victim.username
                else f"🚫 Сумма от <b>1</b> до <b>{attacker_score}</b> баллов."
            )
            return

        if amount < 1:
            await message.reply("🚫 У жертвы меньше баллов, чем ты хочешь стырить.")
            return

        increment_steal_count(attacker.id)

        steal_id = uuid.uuid4().hex[:8]
        attempt = StealAttempt(
            steal_id=steal_id,
            chat_id=message.chat.id,
            attacker_id=attacker.id,
            attacker_name=_user_name(attacker),
            victim_id=victim.id,
            victim_name=_user_name(victim),
            amount=amount,
            started_at=int(time.time()),
        )
        _steals[steal_id] = attempt
        _user_steal[attacker.id] = steal_id
        _user_steal[victim.id] = steal_id

        sent = await message.reply(
            _steal_text(attempt),
            reply_markup=_defend_keyboard(steal_id),
        )
        attempt.message_id = sent.message_id
        _tasks[steal_id] = asyncio.create_task(_steal_countdown(message.bot, attempt))

    @dp.callback_query(F.data.startswith("stl:defend:"))
    async def steal_defend(callback: types.CallbackQuery):
        steal_id = callback.data.split(":", 2)[2]
        attempt = _steals.get(steal_id)

        if not attempt or attempt.resolved:
            await callback.answer("Кража уже завершена", show_alert=True)
            return

        if callback.from_user.id != attempt.victim_id:
            await callback.answer("Это не тебя пытаются обокрасть!", show_alert=True)
            return

        if time.time() - attempt.started_at > STEAL_TIMEOUT:
            await callback.answer("Поздно — время вышло", show_alert=True)
            return

        task = _tasks.pop(steal_id, None)
        if task and not task.done():
            task.cancel()

        await callback.answer("🛡️ Поймал вора!")
        await _resolve_defend(callback.bot, attempt)
