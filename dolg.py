import asyncio
import random
import re
import time
import uuid

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    accrue_all_active_debts,
    activate_debt,
    borrower_has_active_debt,
    create_debt_pending,
    debt_total_owed,
    ensure_user,
    expire_pending_debts,
    forgive_debt,
    get_active_debts_for_user,
    get_all_active_debts,
    get_borrower_active_debt,
    get_debt,
    get_score,
    lender_has_pending_from_borrower,
    repay_debt_amount,
    set_debt_status,
    update_debt_offer_msg,
)
from steal import _resolve_target

LOAN_GRACE_SECONDS = 2 * 3600
REQUEST_TTL = 10 * 60

LOAN_TERMS = {
    "soft": {
        "label": "🤝 По-дружески",
        "rate": 0.05,
        "desc": "5% в час после просрочки",
    },
    "fair": {
        "label": "📋 Банк чата",
        "rate": 0.10,
        "desc": "10% в час — стандарт",
    },
    "hard": {
        "label": "🔥 Коллектор",
        "rate": 0.25,
        "desc": "25% в час — больно",
    },
    "shark": {
        "label": "🦈 Ростовщик",
        "rate": 0.50,
        "desc": "50% в час — кровь из носа",
    },
    "malik": {
        "label": "👑 Малик-банк",
        "rate": 1.00,
        "desc": "100% в час. Ты уверен?",
    },
}

OFFER_LINES = [
    "💸 Кто-то просит баллы в долг. Решай, банкир.",
    "🏦 Заявка на кредит. Условия — твои.",
    "📜 «Верну через 2 часа» — классика. Веришь?",
    "🍺 Денег нет, но очень надо залпнуть. Знакомо?",
]

ACCEPT_LINES = [
    "🤝 Сделка заключена. Часы пошли.",
    "💰 Баллы ушли в долг. Возврат через 2 часа — или проценты.",
    "📈 Кредит одобрен. Не облажайся с возвратом.",
]

SORRY_LINES = [
    "🙏 Прости, банкир... больше не буду.",
    "😭 Не тяну проценты. Может, простишь?",
    "🧎 В долгах как в грехах — прошу отпущения.",
    "💔 Баллов нет, совесть есть. Прости долг?",
]

WARN_LINES = {
    "30m": "⚠️ Через 30 минут долг просрочится — проценты полезут!",
    "10m": "🔥 10 минут до дедлайна! /dolg pay — верни сейчас!",
    "1m": "💀 МИНУТА! Потом начнут капать проценты!",
    "overdue": "📈 ПРОСРОЧКА! Проценты капают каждый час. /dolg pay",
}

_watch_started = False
_notified: dict[str, set[str]] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _fmt_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0 сек."
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if secs or not parts:
        parts.append(f"{secs} сек")
    return " ".join(parts)


def _offer_text(debt: dict) -> str:
    remaining = max(0, REQUEST_TTL - (int(time.time()) - debt["created_at"]))
    return (
        f"💸 <b>ЗАЯВКА НА ДОЛГ</b>\n\n"
        f"{random.choice(OFFER_LINES)}\n\n"
        f"🙋 Должник: <b>{debt['borrower_name']}</b>\n"
        f"🏦 Кредитор: <b>{debt['lender_name']}</b>\n"
        f"💰 Сумма: <b>{debt['principal']}</b> баллов\n"
        f"⏳ Срок после выдачи: <b>2 часа</b>\n\n"
        f"<b>{debt['lender_name']}</b>, выбери условия или откажи.\n"
        f"⌛ На ответ: <b>{_fmt_duration(remaining)}</b>"
    )


def _offer_keyboard(debt_id: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=LOAN_TERMS["soft"]["label"],
                callback_data=f"dlg:ok:{debt_id}:soft",
            ),
            InlineKeyboardButton(
                text=LOAN_TERMS["fair"]["label"],
                callback_data=f"dlg:ok:{debt_id}:fair",
            ),
        ],
        [
            InlineKeyboardButton(
                text=LOAN_TERMS["hard"]["label"],
                callback_data=f"dlg:ok:{debt_id}:hard",
            ),
            InlineKeyboardButton(
                text=LOAN_TERMS["shark"]["label"],
                callback_data=f"dlg:ok:{debt_id}:shark",
            ),
        ],
        [
            InlineKeyboardButton(
                text=LOAN_TERMS["malik"]["label"],
                callback_data=f"dlg:ok:{debt_id}:malik",
            ),
        ],
        [
            InlineKeyboardButton(
                text="❌ Отказать",
                callback_data=f"dlg:no:{debt_id}",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sorry_text(debt: dict) -> str:
    owed = debt_total_owed(debt)
    interest_part = ""
    if debt["accrued_interest"] > 0:
        interest_part = f" ({debt['principal']} + {debt['accrued_interest']} процентов)"
    return (
        f"🙏 <b>ПРОСЬБА О ПРОЩЕНИИ</b>\n\n"
        f"{random.choice(SORRY_LINES)}\n\n"
        f"🙋 <b>{debt['borrower_name']}</b> просит простить долг\n"
        f"🏦 Кредитор: <b>{debt['lender_name']}</b>\n"
        f"💰 К выплате: <b>{owed}</b> баллов{interest_part}\n\n"
        f"<b>{debt['lender_name']}</b>, простить и обнулить?"
    )


def _sorry_keyboard(debt_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤝 Простить",
                    callback_data=f"srry:yes:{debt_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data=f"srry:no:{debt_id}",
                ),
            ],
        ]
    )


def _debt_status_text(debt: dict) -> str:
    accrue_all_active_debts()
    debt = get_debt(debt["debt_id"]) or debt
    owed = debt_total_owed(debt)
    now = int(time.time())
    if debt["status"] == "repaid" or owed <= 0:
        state = "✅ Закрыт"
        timer = ""
    elif now < debt["due_at"]:
        left = debt["due_at"] - now
        state = f"⏳ До дедлайна: <b>{_fmt_duration(left)}</b>"
        timer = ""
    else:
        state = "📈 <b>ПРОСРОЧЕН</b> — капают проценты"
        overdue = now - debt["due_at"]
        timer = f"\n⌛ Просрочка: <b>{_fmt_duration(overdue)}</b>"

    interest_part = ""
    if debt["accrued_interest"] > 0:
        interest_part = f"\n📈 Проценты: <b>+{debt['accrued_interest']}</b>"

    return (
        f"• <b>{debt['borrower_name']}</b> → <b>{debt['lender_name']}</b>\n"
        f"  💰 Долг: <b>{owed}</b> / {debt['principal']}{interest_part}\n"
        f"  📜 {debt['terms_label']} ({int(debt['interest_rate'] * 100)}%/час)\n"
        f"  {state}{timer}"
    )


async def _edit_offer(bot: Bot, debt: dict, text: str, markup=None) -> None:
    if not debt.get("chat_id") or not debt.get("offer_msg_id"):
        return
    try:
        await bot.edit_message_text(
            text,
            chat_id=debt["chat_id"],
            message_id=debt["offer_msg_id"],
            reply_markup=markup,
        )
    except Exception:
        pass


def _parse_loan_amount(args_text: str) -> int | None:
    for token in args_text.split():
        if token.startswith("@"):
            continue
        if re.fullmatch(r"\d+", token):
            return int(token)
    return None


def _expire_stale_pending() -> None:
    expire_pending_debts(REQUEST_TTL)


async def _notify_debt_milestones(bot: Bot) -> None:
    accrue_all_active_debts()
    now = int(time.time())

    for debt in get_all_active_debts():
        debt_id = debt["debt_id"]
        flags = _notified.setdefault(debt_id, set())
        left = debt["due_at"] - now
        chat_id = debt["chat_id"]
        owed = debt_total_owed(debt)
        if owed <= 0:
            continue

        msg = None
        key = None
        if 25 * 60 < left <= 30 * 60 and "30m" not in flags:
            key, msg = "30m", (
                f"⏳ <b>Напоминание должнику</b>\n\n"
                f"<b>{debt['borrower_name']}</b>, через 30 мин вернуть "
                f"<b>{owed}</b> баллов <b>{debt['lender_name']}</b>.\n"
                f"{WARN_LINES['30m']}\n"
                f"💡 <code>/dolg pay</code>"
            )
        elif 5 * 60 < left <= 10 * 60 and "10m" not in flags:
            key, msg = "10m", (
                f"🔥 <b>Долг горит!</b>\n\n"
                f"<b>{debt['borrower_name']}</b> → <b>{debt['lender_name']}</b>: "
                f"<b>{owed}</b> баллов\n"
                f"{WARN_LINES['10m']}"
            )
        elif 0 < left <= 60 and "1m" not in flags:
            key, msg = "1m", (
                f"💀 <b>ПОСЛЕДНЯЯ МИНУТА</b>\n\n"
                f"<b>{debt['borrower_name']}</b>, верни <b>{owed}</b> СЕЙЧАС!\n"
                f"{WARN_LINES['1m']}"
            )
        elif left <= 0 and "overdue" not in flags:
            key, msg = "overdue", (
                f"📈 <b>ДОЛГ ПРОСРОЧЕН</b>\n\n"
                f"<b>{debt['borrower_name']}</b> должен <b>{debt['lender_name']}</b>: "
                f"<b>{owed}</b> баллов\n"
                f"Условия: {debt['terms_label']} — <b>{int(debt['interest_rate'] * 100)}%/час</b>\n"
                f"{WARN_LINES['overdue']}"
            )

        if msg and key:
            flags.add(key)
            try:
                await bot.send_message(chat_id, msg)
            except Exception:
                pass


async def _debt_watch_loop(bot: Bot) -> None:
    try:
        while True:
            try:
                _expire_stale_pending()
                accrue_all_active_debts()
                await _notify_debt_milestones(bot)
            except Exception:
                pass
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        return


def _ensure_watch(bot: Bot) -> None:
    global _watch_started
    if not _watch_started:
        _watch_started = True
        asyncio.create_task(_debt_watch_loop(bot))


async def _show_status(message: types.Message, user: types.User) -> None:
    accrue_all_active_debts()
    debts = get_active_debts_for_user(user.id)
    borrowing = [d for d in debts if d["borrower_id"] == user.id]
    lending = [d for d in debts if d["lender_id"] == user.id]

    if not borrowing and not lending:
        await message.reply(
            "📭 Активных долгов нет.\n"
            "Взять: <code>/dolg @user 5000</code>\n"
            "Вернуть: <code>/dolg pay</code>"
        )
        return

    lines = ["💸 <b>ТВОИ ДОЛГИ</b>\n"]
    if borrowing:
        lines.append("<b>Ты должен:</b>")
        for debt in borrowing:
            lines.append(_debt_status_text(debt))
        lines.append(f"\n🏦 Баланс: <b>{get_score(user.id)}</b>")
        lines.append("💡 Вернуть: <code>/dolg pay</code> или <code>/dolg pay 1000</code>")
    if lending:
        lines.append("\n<b>Тебе должны:</b>")
        for debt in lending:
            lines.append(_debt_status_text(debt))

    await message.reply("\n".join(lines))


def register_dolg(dp: Dispatcher) -> None:
    @dp.message(Command("dolg"))
    async def dolg_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("💸 Долги работают только в группе!")
            return

        user = message.from_user
        if not user:
            return

        _ensure_watch(message.bot)
        ensure_user(user.id, _user_name(user))

        args_text = (command.args or "").strip()
        sub = args_text.split()[0].lower() if args_text else ""

        if not args_text or sub in ("help", "?", "помощь"):
            await message.reply(
                "💸 <b>ДОЛГИ</b>\n\n"
                "<code>/dolg @user 5000</code> — попросить 5000 в долг\n"
                "<code>/dolg pay</code> — вернуть всё возможное\n"
                "<code>/dolg pay 1000</code> — частичный возврат\n"
                "<code>/dolg status</code> — мои долги\n"
                "<code>/sorry</code> — попросить кредитора простить долг\n\n"
                "<b>Как работает:</b>\n"
                "• Кредитор выбирает условия (проценты после просрочки)\n"
                "• <b>2 часа</b> на возврат без процентов\n"
                "• Не вернул вовремя — <b>% капает каждый час</b>\n"
                "• Один активный долг на человека"
            )
            return

        if sub in ("status", "stat", "мои", "debt"):
            await _show_status(message, user)
            return

        if sub in ("pay", "vernut", "вернуть", "return"):
            parts = args_text.split()
            amount = None
            if len(parts) > 1 and parts[1].isdigit():
                amount = int(parts[1])

            paid, settled = repay_debt_amount(user.id, amount)
            if paid <= 0:
                await message.reply(
                    "📭 Нечего гасить — нет активного долга или пустой баланс.\n"
                    "<code>/dolg status</code>"
                )
                return

            lines = [
                f"✅ <b>Возврат: {paid} баллов</b>\n",
                f"🏦 Остаток: <b>{get_score(user.id)}</b>\n",
            ]
            for debt in settled:
                owed = debt_total_owed(debt)
                if debt["status"] == "repaid" or owed <= 0:
                    lines.append(
                        f"🎉 Закрыт долг <b>{debt['lender_name']}</b> "
                        f"({debt['principal']} + {debt['accrued_interest']} процентов)"
                    )
                else:
                    lines.append(
                        f"📉 <b>{debt['lender_name']}</b>: осталось <b>{owed}</b>"
                    )
            await message.reply("\n".join(lines))
            return

        lender = await _resolve_target(message, args_text)
        if not lender:
            await message.reply(
                "🏦 Укажи кредитора: <code>/dolg @user 5000</code>\n"
                "Справка: <code>/dolg help</code>"
            )
            return

        if lender.is_bot:
            await message.reply("🤖 Боты не дают в долг.")
            return

        if lender.id == user.id:
            await message.reply("🪞 Себе в долг? Попробуй /alyp_koyaik.")
            return

        amount = _parse_loan_amount(args_text)
        if not amount or amount < 1:
            await message.reply("💰 Укажи сумму: <code>/dolg @user 5000</code>")
            return

        ensure_user(lender.id, _user_name(lender))

        if borrower_has_active_debt(user.id):
            await message.reply(
                "🚫 У тебя уже есть активный долг или заявка.\n"
                "Сначала верни: <code>/dolg pay</code>"
            )
            return

        if lender_has_pending_from_borrower(lender.id, user.id):
            await message.reply("⏳ Этому человеку ты уже отправил заявку. Жди ответа.")
            return

        lender_balance = get_score(lender.id)
        if lender_balance < amount:
            await message.reply(
                f"🚫 У <b>{_user_name(lender)}</b> только <b>{lender_balance}</b> баллов — "
                f"не хватит на <b>{amount}</b>."
            )
            return

        debt_id = uuid.uuid4().hex[:8]
        create_debt_pending(
            debt_id=debt_id,
            chat_id=message.chat.id,
            borrower_id=user.id,
            borrower_name=_user_name(user),
            lender_id=lender.id,
            lender_name=_user_name(lender),
            principal=amount,
        )

        debt = get_debt(debt_id)
        sent = await message.reply(
            _offer_text(debt),
            reply_markup=_offer_keyboard(debt_id),
        )
        update_debt_offer_msg(debt_id, sent.message_id)

    @dp.callback_query(F.data.startswith("dlg:"))
    async def dolg_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        action = parts[1]
        debt_id = parts[2]
        debt = get_debt(debt_id)

        if not debt or debt["status"] != "pending":
            await callback.answer("Заявка уже неактуальна", show_alert=True)
            return

        if int(time.time()) - debt["created_at"] > REQUEST_TTL:
            set_debt_status(debt_id, "cancelled")
            await _edit_offer(
                callback.bot,
                debt,
                "💸 <b>Заявка истекла</b>\n\nКредитор не ответил вовремя.",
                None,
            )
            await callback.answer("Время вышло", show_alert=True)
            return

        user = callback.from_user
        if not user:
            return

        if action == "no":
            if user.id != debt["lender_id"]:
                await callback.answer("Только кредитор может отказать", show_alert=True)
                return
            set_debt_status(debt_id, "cancelled")
            await _edit_offer(
                callback.bot,
                debt,
                f"❌ <b>Отказ</b>\n\n"
                f"<b>{debt['lender_name']}</b> не дал в долг "
                f"<b>{debt['borrower_name']}</b> ({debt['principal']} б.)",
                None,
            )
            await callback.answer("Отказано")
            return

        if action == "ok":
            if len(parts) != 4:
                await callback.answer("Ошибка данных", show_alert=True)
                return
            if user.id != debt["lender_id"]:
                await callback.answer("Только кредитор выбирает условия!", show_alert=True)
                return

            terms_key = parts[3]
            terms = LOAN_TERMS.get(terms_key)
            if not terms:
                await callback.answer("Неизвестные условия", show_alert=True)
                return

            lender_balance = get_score(debt["lender_id"])
            if lender_balance < debt["principal"]:
                await callback.answer(
                    f"Не хватает баллов ({lender_balance}/{debt['principal']})",
                    show_alert=True,
                )
                return

            if not activate_debt(debt_id, terms["rate"], terms["label"]):
                await callback.answer("Не удалось выдать долг", show_alert=True)
                return

            debt = get_debt(debt_id)
            await callback.answer(f"Выдано под {terms['label']}")
            await _edit_offer(
                callback.bot,
                debt,
                f"✅ <b>ДОЛГ ВЫДАН</b>\n\n"
                f"{random.choice(ACCEPT_LINES)}\n\n"
                f"🙋 <b>{debt['borrower_name']}</b> получил <b>{debt['principal']}</b> баллов\n"
                f"🏦 От <b>{debt['lender_name']}</b>\n"
                f"📜 Условия: <b>{terms['label']}</b> — {terms['desc']}\n"
                f"⏳ Вернуть до: <b>2 часа</b> (без процентов)\n\n"
                f"💡 Должник: <code>/dolg pay</code>",
                None,
            )
            try:
                await callback.bot.send_message(
                    debt["chat_id"],
                    f"💸 <b>{debt['borrower_name']}</b>, тебе дали <b>{debt['principal']}</b>!\n"
                    f"Верни за 2 часа, иначе <b>{int(terms['rate'] * 100)}%/час</b>.\n"
                    f"<code>/dolg pay</code> — вернуть",
                )
            except Exception:
                pass
            return

        await callback.answer("Неизвестное действие", show_alert=True)

    @dp.message(Command("sorry"))
    async def sorry_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("🙏 Просить прощения можно только в группе!")
            return

        user = message.from_user
        if not user:
            return

        _ensure_watch(message.bot)
        ensure_user(user.id, _user_name(user))

        args_text = (command.args or "").strip()
        lender = await _resolve_target(message, args_text) if args_text else None
        if lender and lender.is_bot:
            await message.reply("🤖 Боты долги не прощают.")
            return
        if lender and lender.id == user.id:
            await message.reply("🪞 Себя простить? Сначала /dolg pay.")
            return

        accrue_all_active_debts()
        debt = get_borrower_active_debt(
            user.id,
            lender.id if lender else None,
        )
        if not debt:
            if lender:
                await message.reply(
                    f"📭 У тебя нет активного долга перед <b>{_user_name(lender)}</b>.\n"
                    "<code>/dolg status</code>"
                )
            else:
                await message.reply(
                    "📭 Нет активного долга, который можно простить.\n"
                    "<code>/dolg status</code>"
                )
            return

        owed = debt_total_owed(debt)
        if owed <= 0:
            await message.reply("✅ Долг уже закрыт.")
            return

        await message.reply(
            _sorry_text(debt),
            reply_markup=_sorry_keyboard(debt["debt_id"]),
        )

    @dp.callback_query(F.data.startswith("srry:"))
    async def sorry_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        action, debt_id = parts[1], parts[2]
        debt = get_debt(debt_id)
        if not debt or debt["status"] != "active":
            await callback.answer("Долг уже неактуален", show_alert=True)
            return

        user = callback.from_user
        if not user:
            return

        if user.id != debt["lender_id"]:
            await callback.answer("Только кредитор решает!", show_alert=True)
            return

        if action == "no":
            owed = debt_total_owed(debt)
            try:
                await callback.message.edit_text(
                    f"❌ <b>Без прощения</b>\n\n"
                    f"<b>{debt['lender_name']}</b> не простил "
                    f"<b>{debt['borrower_name']}</b>.\n"
                    f"💰 Долг: <b>{owed}</b> баллов\n"
                    f"💡 Вернуть: <code>/dolg pay</code>",
                    reply_markup=None,
                )
            except Exception:
                pass
            await callback.answer("Отказано")
            return

        if action == "yes":
            forgiven = forgive_debt(debt_id)
            if not forgiven:
                await callback.answer("Не удалось простить долг", show_alert=True)
                return

            try:
                await callback.message.edit_text(
                    f"🤝 <b>ДОЛГ ПРОЩЁН</b>\n\n"
                    f"<b>{debt['lender_name']}</b> простил "
                    f"<b>{debt['borrower_name']}</b>!\n"
                    f"💸 Обнулено: <b>{debt['principal']}</b>"
                    + (
                        f" + <b>{forgiven['accrued_interest']}</b> процентов"
                        if forgiven["accrued_interest"] > 0
                        else ""
                    )
                    + " баллов\n"
                    f"🎉 Должник свободен.",
                    reply_markup=None,
                )
            except Exception:
                pass
            await callback.answer("Прощено!")
            try:
                await callback.bot.send_message(
                    debt["chat_id"],
                    f"🤝 <b>{debt['borrower_name']}</b>, "
                    f"<b>{debt['lender_name']}</b> простил твой долг!",
                )
            except Exception:
                pass
            return

        await callback.answer("Неизвестное действие", show_alert=True)
