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
from steal import _resolve_target

ACCEPT_TIMEOUT = 60
MIN_STAKE = 10
MAX_DUELS_PER_DAY = 5
HOUSE_FEE = 0.05

ROLL_LINES = [
    "🍺 Бутылки стукнулись — кто крепче залпнул?",
    "⚔️ Сила перегара решает всё!",
    "🎲 Судьба крутит барабан печени...",
    "💀 Проигравший завтра на работу с похмельем.",
]


@dataclass
class DuelAlkChallenge:
    challenge_id: str
    chat_id: int
    challenger_id: int
    challenger_name: str
    opponent_id: int
    opponent_name: str
    stake: int
    message_id: int = 0
    started_at: int = 0
    resolved: bool = False


_challenges: dict[str, DuelAlkChallenge] = {}
_user_challenge: dict[int, str] = {}
_tasks: dict[str, asyncio.Task] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _active_for(user_id: int) -> DuelAlkChallenge | None:
    cid = _user_challenge.get(user_id)
    if not cid:
        return None
    ch = _challenges.get(cid)
    if not ch or ch.resolved:
        return None
    if time.time() - ch.started_at > ACCEPT_TIMEOUT:
        return None
    return ch


def _cleanup(ch: DuelAlkChallenge) -> None:
    ch.resolved = True
    _challenges.pop(ch.challenge_id, None)
    _user_challenge.pop(ch.challenger_id, None)
    _user_challenge.pop(ch.opponent_id, None)
    task = _tasks.pop(ch.challenge_id, None)
    if task and not task.done():
        task.cancel()


def _keyboard(challenge_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"dalk:yes:{challenge_id}"),
                InlineKeyboardButton(text="❌ Отказ", callback_data=f"dalk:no:{challenge_id}"),
            ]
        ]
    )


def _pending_text(ch: DuelAlkChallenge) -> str:
    remaining = max(0, ACCEPT_TIMEOUT - (int(time.time()) - ch.started_at))
    return (
        f"⚔️ <b>ДУЭЛЬ АЛКАШЕЙ</b>\n\n"
        f"<b>{ch.challenger_name}</b> вызывает <b>{ch.opponent_name}</b>!\n"
        f"💰 Ставка: <b>{ch.stake}</b> баллов (с каждого)\n"
        f"🏆 Победитель забирает <b>{int(ch.stake * 2 * (1 - HOUSE_FEE))}</b> "
        f"(комиссия бара {int(HOUSE_FEE * 100)}%)\n\n"
        f"<b>{ch.opponent_name}</b>, принимай или отказывайся!\n"
        f"⏳ Осталось: <b>{remaining}</b> сек."
    )


async def _edit(bot: Bot, ch: DuelAlkChallenge, text: str, markup=None) -> None:
    if not ch.chat_id or not ch.message_id:
        return
    try:
        await bot.edit_message_text(text, chat_id=ch.chat_id, message_id=ch.message_id, reply_markup=markup)
    except Exception:
        pass


def _parse_stake(args_text: str, score: int) -> int | None:
    tokens = args_text.split()
    numbers = [int(t) for t in tokens if re.fullmatch(r"\d+", t)]
    if not numbers:
        return min(score, 500) if score >= MIN_STAKE else None
    stake = numbers[-1]
    if stake < MIN_STAKE or stake > score:
        return None
    return stake


async def _resolve_fight(bot: Bot, ch: DuelAlkChallenge) -> None:
    if ch.resolved:
        return

    c_score = get_score(ch.challenger_id)
    o_score = get_score(ch.opponent_id)
    if c_score < ch.stake or o_score < ch.stake:
        _cleanup(ch)
        await _edit(
            bot,
            ch,
            "⚔️ <b>Дуэль отменена</b>\n\nУ кого-то не хватает баллов на ставку.",
            None,
        )
        return

    add_score(ch.challenger_id, -ch.stake)
    add_score(ch.opponent_id, -ch.stake)

    roll_c = random.randint(1, 100)
    roll_o = random.randint(1, 100)
    pot = int(ch.stake * 2 * (1 - HOUSE_FEE))

    if roll_c == roll_o:
        roll_c = random.randint(1, 100)
        roll_o = random.randint(1, 100)

    if roll_c == roll_o:
        add_score(ch.challenger_id, ch.stake)
        add_score(ch.opponent_id, ch.stake)
        text = (
            f"🤝 <b>НИЧЬЯ!</b>\n\n"
            f"{random.choice(ROLL_LINES)}\n\n"
            f"🎲 {ch.challenger_name}: <b>{roll_c}</b> | {ch.opponent_name}: <b>{roll_o}</b>\n\n"
            f"Ставки возвращены."
        )
    elif roll_c > roll_o:
        add_score(ch.challenger_id, pot)
        winner, loser = ch.challenger_name, ch.opponent_name
        w_roll, l_roll = roll_c, roll_o
        winner_total = get_score(ch.challenger_id)
    else:
        add_score(ch.opponent_id, pot)
        winner, loser = ch.opponent_name, ch.challenger_name
        w_roll, l_roll = roll_o, roll_c
        winner_total = get_score(ch.opponent_id)

    _cleanup(ch)

    if roll_c != roll_o:
        text = (
            f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА!</b>\n\n"
            f"{random.choice(ROLL_LINES)}\n\n"
            f"🎲 {ch.challenger_name}: <b>{roll_c}</b>\n"
            f"🎲 {ch.opponent_name}: <b>{roll_o}</b>\n\n"
            f"🏆 <b>{winner}</b> победил <b>{loser}</b>!\n"
            f"➕ Выигрыш: <b>{pot}</b> баллов\n"
            f"💰 Баланс победителя: <b>{winner_total}</b>"
        )

    await _edit(bot, ch, text, None)


async def _timeout(bot: Bot, ch: DuelAlkChallenge) -> None:
    try:
        while not ch.resolved:
            if int(time.time()) - ch.started_at >= ACCEPT_TIMEOUT:
                _cleanup(ch)
                await _edit(
                    bot,
                    ch,
                    f"⏰ <b>Время вышло!</b>\n\n"
                    f"<b>{ch.opponent_name}</b> не ответил — дуэль отменена.",
                    None,
                )
                return
            await _edit(bot, ch, _pending_text(ch), _keyboard(ch.challenge_id))
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


def register_duel_alk(dp: Dispatcher) -> None:
    @dp.message(Command("duel_alk"))
    async def duel_alk_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("⚔️ Дуэль алкашей работает только в группе!")
            return

        user = message.from_user
        if not user:
            return

        args_text = (command.args or "").strip()
        if args_text.lower() in ("help", "?", "помощь"):
            await message.reply(
                "⚔️ <b>ДУЭЛЬ АЛКАШЕЙ</b>\n\n"
                "<code>/duel_alk @user</code> — ставка до 500 (или весь баланс)\n"
                "<code>/duel_alk @user 200</code> — ставка 200 баллов\n\n"
                f"• Минимум <b>{MIN_STAKE}</b> баллов\n"
                f"• Максимум <b>{MAX_DUELS_PER_DAY}</b> дуэлей в день\n"
                f"• Соперник <b>{ACCEPT_TIMEOUT} сек</b> на ответ\n"
                f"• Победитель забирает котёл минус {int(HOUSE_FEE * 100)}% комиссии\n"
                "• Кто сильнее залпнул по кубику 1–100 — тот и взял"
            )
            return

        opponent = await _resolve_target(message, args_text)
        if not opponent:
            await message.reply(
                "🎯 Укажи соперника: <code>/duel_alk @user 100</code>\n"
                "Справка: <code>/duel_alk help</code>"
            )
            return

        if opponent.is_bot or opponent.id == user.id:
            await message.reply("🪞 С собой или ботом не подерёшься.")
            return

        ensure_user(user.id, _user_name(user))
        ensure_user(opponent.id, _user_name(opponent))

        if _active_for(user.id) or _active_for(opponent.id):
            await message.reply("⏳ У кого-то уже идёт дуэль. Дождись результата.")
            return

        if get_game_count_today(user.id, "duel_alk") >= MAX_DUELS_PER_DAY:
            await message.reply(
                f"🚫 Лимит дуэлей на сегодня: <b>{MAX_DUELS_PER_DAY}/{MAX_DUELS_PER_DAY}</b>"
            )
            return

        score = get_score(user.id)
        stake = _parse_stake(args_text, score)
        if stake is None:
            await message.reply(
                f"🚫 Ставка от <b>{MIN_STAKE}</b> до <b>{score}</b> баллов.\n"
                f"Пример: <code>/duel_alk @{opponent.username or 'user'} 100</code>"
                if opponent.username
                else f"🚫 Ставка от <b>{MIN_STAKE}</b> до <b>{score}</b> баллов."
            )
            return

        opp_score = get_score(opponent.id)
        if opp_score < stake:
            await message.reply(
                f"🚫 У <b>{_user_name(opponent)}</b> только <b>{opp_score}</b> баллов — "
                f"нужно минимум <b>{stake}</b>."
            )
            return

        increment_game_count(user.id, "duel_alk")

        challenge_id = uuid.uuid4().hex[:8]
        ch = DuelAlkChallenge(
            challenge_id=challenge_id,
            chat_id=message.chat.id,
            challenger_id=user.id,
            challenger_name=_user_name(user),
            opponent_id=opponent.id,
            opponent_name=_user_name(opponent),
            stake=stake,
            started_at=int(time.time()),
        )
        _challenges[challenge_id] = ch
        _user_challenge[user.id] = challenge_id
        _user_challenge[opponent.id] = challenge_id

        sent = await message.reply(_pending_text(ch), reply_markup=_keyboard(challenge_id))
        ch.message_id = sent.message_id
        _tasks[challenge_id] = asyncio.create_task(_timeout(message.bot, ch))

    @dp.callback_query(F.data.startswith("dalk:"))
    async def duel_alk_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Ошибка", show_alert=True)
            return

        _, action, challenge_id = parts
        ch = _challenges.get(challenge_id)
        if not ch or ch.resolved:
            await callback.answer("Вызов неактуален", show_alert=True)
            return

        user = callback.from_user
        if user.id != ch.opponent_id:
            await callback.answer("Это не твой вызов!", show_alert=True)
            return

        if time.time() - ch.started_at > ACCEPT_TIMEOUT:
            await callback.answer("Время вышло", show_alert=True)
            return

        task = _tasks.pop(challenge_id, None)
        if task and not task.done():
            task.cancel()

        if action == "no":
            _cleanup(ch)
            await callback.answer("Отказ")
            await _edit(
                callback.bot,
                ch,
                f"❌ <b>{ch.opponent_name}</b> отказался от дуэли.\n"
                f"<b>{ch.challenger_name}</b>, попробуй другого алкаша.",
                None,
            )
            return

        if get_game_count_today(user.id, "duel_alk_join") >= MAX_DUELS_PER_DAY:
            await callback.answer(
                f"Лимит дуэлей на сегодня ({MAX_DUELS_PER_DAY})",
                show_alert=True,
            )
            return

        increment_game_count(user.id, "duel_alk_join")
        await callback.answer("Принято! Бьёмся!")
        await _resolve_fight(callback.bot, ch)
