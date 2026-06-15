import re
import uuid
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import add_score, ensure_user, get_game_count_today, get_score, increment_game_count
from naruto_duel import get_bettable_duel

MIN_STAKE = 10
MAX_STAKE = 200
MAX_BETS_PER_DAY = 3
WIN_MULTIPLIER = 1.8


@dataclass
class NarutoBet:
    bet_id: str
    duel_id: str
    user_id: int
    user_name: str
    picked_user_id: int
    picked_name: str
    stake: int


@dataclass
class BetPool:
    duel_id: str
    chat_id: int
    challenger_id: int
    challenger_name: str
    opponent_id: int | None = None
    opponent_name: str | None = None
    bets: list[NarutoBet] = field(default_factory=list)
    closed: bool = False


_pools: dict[str, BetPool] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _pool_for_duel(duel) -> BetPool:
    pool = _pools.get(duel.id)
    if pool:
        pool.opponent_id = duel.opponent_id
        pool.opponent_name = duel.opponent_name
        return pool
    pool = BetPool(
        duel_id=duel.id,
        chat_id=duel.chat_id,
        challenger_id=duel.challenger_id,
        challenger_name=duel.challenger_name,
        opponent_id=duel.opponent_id,
        opponent_name=duel.opponent_name,
    )
    _pools[duel.id] = pool
    return pool


def _user_bet_on_duel(user_id: int, duel_id: str) -> NarutoBet | None:
    pool = _pools.get(duel_id)
    if not pool:
        return None
    for bet in pool.bets:
        if bet.user_id == user_id:
            return bet
    return None


def _side_keyboard(duel_id: str, stake: int, pool: BetPool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🅰️ {pool.challenger_name}",
                callback_data=f"nbet:side:{duel_id}:{pool.challenger_id}:{stake}",
            )
        ]
    ]
    if pool.opponent_id and pool.opponent_name:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🅱️ {pool.opponent_name}",
                    callback_data=f"nbet:side:{duel_id}:{pool.opponent_id}:{stake}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def on_duel_accepted(bot: Bot, duel) -> None:
    pool = _pool_for_duel(duel)
    total = sum(b.stake for b in pool.bets)
    await bot.send_message(
        duel.chat_id,
        f"🎰 <b>Ставки открыты!</b>\n"
        f"<b>{duel.challenger_name}</b> 🆚 <b>{duel.opponent_name}</b>\n"
        f"Котёл: <b>{total}</b> | <code>/naruto_bet 50</code>\n"
        f"Закроется перед фазой бана.",
    )


async def close_betting(bot: Bot, duel) -> None:
    pool = _pools.get(duel.id)
    if not pool or pool.closed:
        return
    pool.closed = True
    if not pool.bets:
        return
    total = sum(b.stake for b in pool.bets)
    lines = [f"🔒 <b>Ставки закрыты!</b> Котёл: <b>{total}</b> баллов\n"]
    for bet in pool.bets:
        lines.append(f"  • {bet.user_name} → <b>{bet.picked_name}</b> ({bet.stake})")
    await bot.send_message(duel.chat_id, "\n".join(lines))


async def resolve_bets(bot: Bot, duel, winner_id: int | None) -> None:
    pool = _pools.pop(duel.id, None)
    if not pool or not pool.bets:
        return

    if winner_id is None:
        for bet in pool.bets:
            add_score(bet.user_id, bet.stake)
        names = ", ".join(b.user_name for b in pool.bets)
        await bot.send_message(
            duel.chat_id,
            f"🎰 <b>Ставки возвращены</b> — duel отменён или ничья.\n"
            f"Игроки: {names}",
        )
        return

    winners: list[str] = []
    for bet in pool.bets:
        if bet.picked_user_id == winner_id:
            payout = int(bet.stake * WIN_MULTIPLIER)
            add_score(bet.user_id, payout)
            winners.append(f"{bet.user_name} (+{payout - bet.stake})")

    if winners:
        winner_name = duel.challenger_name if winner_id == duel.challenger_id else duel.opponent_name
        await bot.send_message(
            duel.chat_id,
            f"🎰 <b>Ставки разыграны!</b> Победил <b>{winner_name}</b>\n"
            + "\n".join(f"  ✅ {w}" for w in winners),
        )


def register_naruto_bet(dp: Dispatcher) -> None:
    @dp.message(Command("naruto_bet"))
    async def naruto_bet_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("🎰 Ставки работают только в группе!")
            return

        user = message.from_user
        if not user:
            return

        args = (command.args or "").strip()
        if args.lower() in ("help", "?", "помощь"):
            await message.reply(
                "🎰 <b>СТАВКИ НА DUEL</b>\n\n"
                "<code>/naruto_bet 50</code> — ставка 50 на победителя\n"
                "<code>/naruto_bet</code> — статус текущего duel\n\n"
                f"• Ставка: <b>{MIN_STAKE}–{MAX_STAKE}</b> баллов\n"
                f"• Лимит: <b>{MAX_BETS_PER_DAY}</b> ставки в день\n"
                f"• Одна ставка на один duel\n"
                f"• Выигрыш: ×{WIN_MULTIPLIER} (нетто)\n"
                "• Нельзя ставить, если ты в duel\n"
                "• Ставки до фазы бана"
            )
            return

        duel = get_bettable_duel(message.chat.id)
        if not duel:
            await message.reply(
                "🍥 Сейчас нет duel для ставок.\n"
                "Жди <code>/duel</code> — ставки открываются до фазы бана."
            )
            return

        pool = _pool_for_duel(duel)
        if pool.closed:
            await message.reply("🔒 Ставки на этот duel уже закрыты.")
            return

        if user.id in (duel.challenger_id, duel.opponent_id or -1):
            await message.reply("🚫 Участники duel не могут ставить на себя.")
            return

        if not args:
            total = sum(b.stake for b in pool.bets)
            opp = f" 🆚 <b>{duel.opponent_name}</b>" if duel.opponent_name else " (ждёт соперника)"
            lines = [
                f"🎰 <b>Ставки на duel</b>\n",
                f"<b>{duel.challenger_name}</b>{opp}",
                f"Котёл: <b>{total}</b> | Ставок: <b>{len(pool.bets)}</b>\n",
            ]
            if pool.bets:
                lines.append("<b>Кто на кого:</b>")
                for bet in pool.bets:
                    lines.append(f"  • {bet.user_name} → {bet.picked_name} ({bet.stake})")
            else:
                lines.append("Пока никто не поставил.")
            lines.append(f"\n<code>/naruto_bet 50</code> — поставить")
            await message.reply("\n".join(lines))
            return

        match = re.search(r"\d+", args)
        if not match:
            await message.reply(f"💰 Укажи сумму: <code>/naruto_bet 50</code>")
            return

        stake = int(match.group())
        ensure_user(user.id, _user_name(user))
        balance = get_score(user.id)

        if stake < MIN_STAKE or stake > MAX_STAKE:
            await message.reply(f"🚫 Ставка от <b>{MIN_STAKE}</b> до <b>{MAX_STAKE}</b>.")
            return
        if stake > balance:
            await message.reply(f"🚫 Не хватает баллов. У тебя <b>{balance}</b>.")
            return

        if get_game_count_today(user.id, "naruto_bet") >= MAX_BETS_PER_DAY:
            await message.reply(
                f"🚫 Лимит ставок на сегодня: <b>{MAX_BETS_PER_DAY}/{MAX_BETS_PER_DAY}</b>"
            )
            return

        if _user_bet_on_duel(user.id, duel.id):
            await message.reply("🚫 Ты уже поставил на этот duel.")
            return

        tokens = args.lower().split()
        if "challenger" in tokens or "вызов" in tokens or "а" in tokens:
            picked_id = duel.challenger_id
            picked_name = duel.challenger_name
            await _place_bet(message, user, duel, pool, stake, picked_id, picked_name)
            return
        if duel.opponent_id and (
            "opponent" in tokens or "соперник" in tokens or "б" in tokens
        ):
            picked_id = duel.opponent_id
            picked_name = duel.opponent_name or "Соперник"
            await _place_bet(message, user, duel, pool, stake, picked_id, picked_name)
            return

        if duel.opponent_id is None:
            await message.reply(
                f"⏳ Соперник ещё не принял вызов.\n"
                f"Можно ставить только на <b>{duel.challenger_name}</b>:\n"
                f"<code>/naruto_bet {stake} challenger</code>",
                reply_markup=_side_keyboard(duel.id, stake, pool),
            )
            return

        await message.reply(
            f"🎰 На кого ставишь <b>{stake}</b> баллов?",
            reply_markup=_side_keyboard(duel.id, stake, pool),
        )

    @dp.callback_query(F.data.startswith("nbet:side:"))
    async def naruto_bet_side(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) != 5:
            await callback.answer("Ошибка", show_alert=True)
            return

        _, _, duel_id, picked_id_str, stake_str = parts
        try:
            picked_id = int(picked_id_str)
            stake = int(stake_str)
        except ValueError:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        duel = get_bettable_duel(callback.message.chat.id if callback.message else 0)
        if not duel or duel.id != duel_id:
            await callback.answer("Duel уже не принимает ставки", show_alert=True)
            return

        pool = _pools.get(duel_id)
        if not pool or pool.closed:
            await callback.answer("Ставки закрыты", show_alert=True)
            return

        user = callback.from_user
        if user.id in (duel.challenger_id, duel.opponent_id or -1):
            await callback.answer("Участник duel не может ставить", show_alert=True)
            return

        if _user_bet_on_duel(user.id, duel_id):
            await callback.answer("Ты уже поставил", show_alert=True)
            return

        if get_game_count_today(user.id, "naruto_bet") >= MAX_BETS_PER_DAY:
            await callback.answer(f"Лимит {MAX_BETS_PER_DAY} ставок в день", show_alert=True)
            return

        if picked_id == duel.challenger_id:
            picked_name = duel.challenger_name
        elif duel.opponent_id and picked_id == duel.opponent_id:
            picked_name = duel.opponent_name or "Соперник"
        else:
            await callback.answer("Неверная сторона", show_alert=True)
            return

        balance = get_score(user.id)
        if stake < MIN_STAKE or stake > MAX_STAKE or stake > balance:
            await callback.answer("Неверная ставка или баланс", show_alert=True)
            return

        add_score(user.id, -stake)
        increment_game_count(user.id, "naruto_bet")
        ensure_user(user.id, _user_name(user))

        bet = NarutoBet(
            bet_id=uuid.uuid4().hex[:8],
            duel_id=duel_id,
            user_id=user.id,
            user_name=_user_name(user),
            picked_user_id=picked_id,
            picked_name=picked_name,
            stake=stake,
        )
        pool.bets.append(bet)

        total = sum(b.stake for b in pool.bets)
        await callback.answer(f"Ставка {stake} на {picked_name}!")
        if callback.message:
            await callback.message.edit_text(
                f"🎰 <b>Ставка принята!</b>\n\n"
                f"👤 {_user_name(user)} → <b>{picked_name}</b>\n"
                f"💰 <b>{stake}</b> баллов\n"
                f"🏆 Котёл: <b>{total}</b>\n"
                f"Выигрыш при победе: <b>{int(stake * WIN_MULTIPLIER)}</b> (×{WIN_MULTIPLIER})",
                reply_markup=None,
            )


async def _place_bet(
    message: types.Message,
    user: types.User,
    duel,
    pool: BetPool,
    stake: int,
    picked_id: int,
    picked_name: str,
) -> None:
    if _user_bet_on_duel(user.id, duel.id):
        await message.reply("🚫 Ты уже поставил на этот duel.")
        return

    if get_game_count_today(user.id, "naruto_bet") >= MAX_BETS_PER_DAY:
        await message.reply(f"🚫 Лимит ставок на сегодня: <b>{MAX_BETS_PER_DAY}</b>")
        return

    add_score(user.id, -stake)
    increment_game_count(user.id, "naruto_bet")

    bet = NarutoBet(
        bet_id=uuid.uuid4().hex[:8],
        duel_id=duel.id,
        user_id=user.id,
        user_name=_user_name(user),
        picked_user_id=picked_id,
        picked_name=picked_name,
        stake=stake,
    )
    pool.bets.append(bet)
    total = sum(b.stake for b in pool.bets)
    await message.reply(
        f"🎰 <b>Ставка принята!</b>\n\n"
        f"→ <b>{picked_name}</b> на <b>{stake}</b> баллов\n"
        f"🏆 Котёл: <b>{total}</b>\n"
        f"Выигрыш: <b>{int(stake * WIN_MULTIPLIER)}</b>"
    )
