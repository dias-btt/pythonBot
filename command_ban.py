import time
import uuid
from dataclasses import dataclass, field

from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, TelegramObject

from db import (
    ban_command,
    ensure_user,
    get_all_alkashi_users,
    is_chat_suicided,
    is_command_banned,
    list_banned_commands,
    set_chat_suicide,
    unban_command,
)

VOTE_TTL = 30 * 60
SUICIDE_VOTE_TTL = 60 * 60
MIN_YES_VOTES = 3

PROTECTED_COMMANDS = {"info", "start"}

BANNABLE_COMMANDS = {
    "steal": "🦹 Кража баллов",
    "dolg": "💸 Долги",
    "sorry": "🙏 Прощение долга",
    "roulette": "🔫 Русская рулетка",
    "duel": "⚔️ Naruto duel",
    "otboi": "🛑 Отмена duel",
    "naruto": "🍥 Команда Naruto",
    "naruto_team": "🍥 Команда Naruto",
    "naruto_ratings": "📊 Рейтинг duel",
    "alyp_koyaik": "🍻 Алып қояйық",
    "duel_alk": "⚔️ Дуэль алкашей",
    "dice": "🎲 Кости",
    "quiz": "🧠 Викторина",
    "guess_ninja": "🍥 Угадай ниндзя",
    "naruto_bet": "🎰 Ставки на duel",
    "alkashi": "🏆 Рейтинг алкашей",
    "alkashi_reset": "🔄 Сброс баллов",
    "poebat": "🔥 Poebat",
    "che_malik": "💬 Че Малик",
    "kto_segodnya": "👑 Малик/Гей дня",
    "malik": "🎲 Тип Малика",
    "do_malika": "📅 До приезда Малика",
    "vaxta": "🛢️ Вахта Малика",
    "malik_let": "🎂 Возраст Малика",
}


@dataclass
class CommandBanVote:
    vote_id: str
    chat_id: int
    command: str
    action: str  # ban | unban
    initiator_id: int
    initiator_name: str
    yes: set[int] = field(default_factory=set)
    no: set[int] = field(default_factory=set)
    names: dict[int, str] = field(default_factory=dict)
    message_id: int = 0
    created_at: int = 0


_votes: dict[str, CommandBanVote] = {}
_chat_vote: dict[int, str] = {}


@dataclass
class SuicideVote:
    vote_id: str
    chat_id: int
    initiator_id: int
    initiator_name: str
    required: dict[int, str] = field(default_factory=dict)
    agreed: set[int] = field(default_factory=set)
    declined: set[int] = field(default_factory=set)
    names: dict[int, str] = field(default_factory=dict)
    message_id: int = 0
    created_at: int = 0


_suicide_votes: dict[str, SuicideVote] = {}
_chat_suicide_vote: dict[int, str] = {}


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _parse_command_name(text: str) -> str | None:
    if not text.startswith("/"):
        return None
    return text.split()[0].split("@")[0][1:].lower()


def _normalize_cmd(name: str) -> str | None:
    cmd = name.lstrip("/").lower().strip()
    if cmd in BANNABLE_COMMANDS:
        return cmd
    return None


def _active_vote(chat_id: int) -> CommandBanVote | None:
    vote_id = _chat_vote.get(chat_id)
    if not vote_id:
        return None
    vote = _votes.get(vote_id)
    if not vote:
        return None
    if time.time() - vote.created_at > VOTE_TTL:
        _cleanup_vote(vote)
        return None
    return vote


def _cleanup_vote(vote: CommandBanVote) -> None:
    _votes.pop(vote.vote_id, None)
    if _chat_vote.get(vote.chat_id) == vote.vote_id:
        _chat_vote.pop(vote.chat_id, None)


def _vote_keyboard(vote_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ За", callback_data=f"cbv:yes:{vote_id}"),
                InlineKeyboardButton(text="❌ Против", callback_data=f"cbv:no:{vote_id}"),
            ]
        ]
    )


def _vote_passed(vote: CommandBanVote) -> bool:
    return len(vote.yes) >= MIN_YES_VOTES and len(vote.yes) > len(vote.no)


def _vote_failed(vote: CommandBanVote) -> bool:
    return len(vote.no) >= MIN_YES_VOTES and len(vote.no) >= len(vote.yes)


def _vote_text(vote: CommandBanVote) -> str:
    cmd_label = BANNABLE_COMMANDS.get(vote.command, vote.command)
    action = "ЗАКРЫТЬ" if vote.action == "ban" else "ОТКРЫТЬ"
    yes_names = [vote.names[uid] for uid in vote.yes if uid in vote.names]
    no_names = [vote.names[uid] for uid in vote.no if uid in vote.names]
    remaining = max(0, VOTE_TTL - (int(time.time()) - vote.created_at))

    lines = [
        f"🗳️ <b>Голосование: {action} /{vote.command}</b>",
        f"{cmd_label}",
        "",
        f"Инициатор: <b>{vote.initiator_name}</b>",
        f"✅ За: <b>{len(vote.yes)}</b> | ❌ Против: <b>{len(vote.no)}</b>",
        f"Нужно: <b>{MIN_YES_VOTES}+</b> голосов «За» и больше чем «Против»",
        "",
    ]
    if yes_names:
        lines.append("✅ За:")
        lines.extend(f"  • {n}" for n in yes_names)
        lines.append("")
    if no_names:
        lines.append("❌ Против:")
        lines.extend(f"  • {n}" for n in no_names)
        lines.append("")
    lines.append(f"⏳ Осталось: <b>{remaining // 60} мин</b>")
    return "\n".join(lines)


async def _finish_vote(bot: Bot, vote: CommandBanVote, success: bool, reason: str) -> None:
    text = _vote_text(vote) + f"\n\n{reason}"
    try:
        await bot.edit_message_text(
            text,
            chat_id=vote.chat_id,
            message_id=vote.message_id,
            reply_markup=None,
        )
    except Exception:
        pass
    _cleanup_vote(vote)


def _active_suicide_vote(chat_id: int) -> SuicideVote | None:
    vote_id = _chat_suicide_vote.get(chat_id)
    if not vote_id:
        return None
    vote = _suicide_votes.get(vote_id)
    if not vote:
        return None
    if time.time() - vote.created_at > SUICIDE_VOTE_TTL:
        _cleanup_suicide_vote(vote)
        return None
    return vote


def _cleanup_suicide_vote(vote: SuicideVote) -> None:
    _suicide_votes.pop(vote.vote_id, None)
    if _chat_suicide_vote.get(vote.chat_id) == vote.vote_id:
        _chat_suicide_vote.pop(vote.chat_id, None)


def _suicide_required_yes(vote: SuicideVote) -> int:
    total = len(vote.required)
    return total // 2 + 1


def _suicide_passed(vote: SuicideVote) -> bool:
    return len(vote.agreed) >= _suicide_required_yes(vote)


def _suicide_failed(vote: SuicideVote) -> bool:
    total = len(vote.required)
    need_yes = _suicide_required_yes(vote)
    return len(vote.declined) > total - need_yes


async def _is_chat_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False


async def _suicide_required_voters(bot: Bot, chat_id: int) -> dict[int, str]:
    required: dict[int, str] = {}
    for user_id, username in get_all_alkashi_users():
        if not await _is_chat_member(bot, chat_id, user_id):
            continue
        required[user_id] = username or "Анон"
    return required


def _suicide_vote_keyboard(vote_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Согласен", callback_data=f"sui:yes:{vote_id}"),
                InlineKeyboardButton(text="❌ Против", callback_data=f"sui:no:{vote_id}"),
            ]
        ]
    )


def _suicide_vote_text(vote: SuicideVote) -> str:
    total = len(vote.required)
    need_yes = _suicide_required_yes(vote)
    agreed_names = [vote.required[uid] for uid in vote.agreed if uid in vote.required]
    declined_names = [vote.required[uid] for uid in vote.declined if uid in vote.required]
    pending = [
        name for uid, name in vote.required.items()
        if uid not in vote.agreed and uid not in vote.declined
    ]
    lines = [
        "💀 <b>Голосование: /suicide</b>",
        "",
        "Если <b>большинство</b> активных игроков бота согласится — "
        "бот отключит <b>все команды навсегда</b>. Восстановить нельзя.",
        "",
        f"Инициатор: <b>{vote.initiator_name}</b>",
        f"✅ За: <b>{len(vote.agreed)}</b> | ❌ Против: <b>{len(vote.declined)}</b>",
        f"Нужно: <b>{need_yes}</b> из <b>{total}</b> голосов «За»",
        "",
    ]
    if agreed_names:
        lines.append("✅ За:")
        lines.extend(f"  • {name}" for name in agreed_names)
        lines.append("")
    if declined_names:
        lines.append("❌ Против:")
        lines.extend(f"  • {name}" for name in declined_names)
        lines.append("")
    if pending:
        lines.append("⏳ Ждём:")
        lines.extend(f"  • {name}" for name in pending)
        lines.append("")
    return "\n".join(lines)


async def _finish_suicide_vote(bot: Bot, vote: SuicideVote, reason: str) -> None:
    text = _suicide_vote_text(vote) + f"\n\n{reason}"
    try:
        await bot.edit_message_text(
            text,
            chat_id=vote.chat_id,
            message_id=vote.message_id,
            reply_markup=None,
        )
    except Exception:
        pass
    _cleanup_suicide_vote(vote)


class CommandBanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not isinstance(event, types.Message):
            return await handler(event, data)

        text = (event.text or "").strip()
        if not text.startswith("/"):
            return await handler(event, data)

        if event.chat.type not in ("group", "supergroup"):
            return await handler(event, data)

        cmd = _parse_command_name(text)
        if not cmd or cmd in PROTECTED_COMMANDS:
            return await handler(event, data)

        if is_chat_suicided(event.chat.id):
            await event.reply(
                "💀 Бот «умер» по согласию большинства. Команды отключены навсегда."
            )
            return

        if is_command_banned(event.chat.id, cmd):
            await event.reply(
                f"🚫 Команда <code>/{cmd}</code> закрыта голосованием в этом чате.\n"
                f"Разблокировать: <code>/unban {cmd}</code>"
            )
            return

        return await handler(event, data)


def register_command_ban(dp: Dispatcher) -> None:
    dp.message.middleware(CommandBanMiddleware())

    @dp.message(Command("ban"))
    async def ban_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("🗳️ Голосование работает только в группе!")
            return

        user = message.from_user
        if not user:
            return

        args = (command.args or "").strip().lower()

        if not args or args in ("help", "?", "помощь", "list", "список"):
            banned = list_banned_commands(message.chat.id)
            lines = ["🗳️ <b>БАН КОМАНД</b>\n"]
            if is_chat_suicided(message.chat.id):
                lines.append("💀 Бот «мёртв» — команды отключены навсегда.")
            elif banned:
                lines.append("<b>Закрыто в этом чате:</b>")
                for cmd, by in banned:
                    label = BANNABLE_COMMANDS.get(cmd, cmd)
                    lines.append(f"  🚫 /{cmd} — {label}" + (f" (закрыл {by})" if by else ""))
            else:
                lines.append("Пока ничего не закрыто.")
            lines.append("\n<code>/ban steal</code> — голосование за закрытие")
            lines.append("<code>/unban steal</code> — голосование за открытие")
            lines.append("<code>/suicide</code> — отключить все команды (если большинство игроков бота согласно)")
            lines.append("\n<b>Можно закрыть:</b>")
            for cmd, label in BANNABLE_COMMANDS.items():
                if cmd != "naruto_team":
                    lines.append(f"  /{cmd} — {label}")
            await message.reply("\n".join(lines))
            return

        if is_chat_suicided(message.chat.id):
            await message.reply("💀 Бот «мёртв» — команды отключены навсегда.")
            return

        cmd = _normalize_cmd(args.split()[0])
        if not cmd:
            await message.reply(
                "❓ Неизвестная команда. Список: <code>/ban list</code>"
            )
            return

        if is_command_banned(message.chat.id, cmd):
            await message.reply(f"🚫 <code>/{cmd}</code> уже закрыта. Открыть: <code>/unban {cmd}</code>")
            return

        active = _active_vote(message.chat.id)
        if active:
            await message.reply("⏳ Уже идёт голосование в этом чате. Жми кнопки там.")
            return

        if _active_suicide_vote(message.chat.id):
            await message.reply("⏳ Уже идёт голосование за /suicide.")
            return

        vote_id = uuid.uuid4().hex[:8]
        vote = CommandBanVote(
            vote_id=vote_id,
            chat_id=message.chat.id,
            command=cmd,
            action="ban",
            initiator_id=user.id,
            initiator_name=_user_name(user),
            created_at=int(time.time()),
        )
        vote.yes.add(user.id)
        vote.names[user.id] = vote.initiator_name
        _votes[vote_id] = vote
        _chat_vote[message.chat.id] = vote_id

        sent = await message.reply(
            _vote_text(vote),
            reply_markup=_vote_keyboard(vote_id),
        )
        vote.message_id = sent.message_id

    @dp.message(Command("unban"))
    async def unban_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("🗳️ Голосование работает только в группе!")
            return

        user = message.from_user
        if not user:
            return

        args = (command.args or "").strip().lower()
        if not args:
            await message.reply("Укажи команду: <code>/unban steal</code>")
            return

        if is_chat_suicided(message.chat.id):
            await message.reply("💀 Бот «мёртв» — команды отключены навсегда.")
            return

        cmd = _normalize_cmd(args.split()[0])
        if not cmd:
            await message.reply("❓ Неизвестная команда. Список: <code>/ban list</code>")
            return

        if not is_command_banned(message.chat.id, cmd):
            await message.reply(f"✅ <code>/{cmd}</code> и так открыта.")
            return

        active = _active_vote(message.chat.id)
        if active:
            await message.reply("⏳ Уже идёт голосование в этом чате. Жми кнопки там.")
            return

        if _active_suicide_vote(message.chat.id):
            await message.reply("⏳ Уже идёт голосование за /suicide.")
            return

        vote_id = uuid.uuid4().hex[:8]
        vote = CommandBanVote(
            vote_id=vote_id,
            chat_id=message.chat.id,
            command=cmd,
            action="unban",
            initiator_id=user.id,
            initiator_name=_user_name(user),
            created_at=int(time.time()),
        )
        vote.yes.add(user.id)
        vote.names[user.id] = vote.initiator_name
        _votes[vote_id] = vote
        _chat_vote[message.chat.id] = vote_id

        sent = await message.reply(
            _vote_text(vote),
            reply_markup=_vote_keyboard(vote_id),
        )
        vote.message_id = sent.message_id

    @dp.message(Command("bans"))
    async def bans_list(message: types.Message):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("Только для групп.")
            return
        banned = list_banned_commands(message.chat.id)
        if not banned:
            await message.reply("✅ Все команды открыты.\n<code>/ban list</code> — полный список")
            return
        lines = ["🚫 <b>Закрытые команды:</b>\n"]
        for cmd, by in banned:
            label = BANNABLE_COMMANDS.get(cmd, cmd)
            lines.append(f"• /{cmd} — {label}" + (f" ({by})" if by else ""))
        lines.append("\nОткрыть: <code>/unban команда</code>")
        await message.reply("\n".join(lines))

    @dp.callback_query(F.data.startswith("cbv:"))
    async def ban_vote_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        _, action, vote_id = parts
        vote = _votes.get(vote_id)
        if not vote:
            await callback.answer("Голосование уже неактуально", show_alert=True)
            return

        if time.time() - vote.created_at > VOTE_TTL:
            await _finish_vote(callback.bot, vote, False, "⏰ Время вышло — голосование отменено.")
            await callback.answer("Время вышло", show_alert=True)
            return

        user = callback.from_user
        if not user:
            return

        if user.id in vote.yes or user.id in vote.no:
            await callback.answer("Ты уже голосовал")
            return

        name = _user_name(user)
        if action == "yes":
            vote.yes.add(user.id)
            vote.names[user.id] = name
            await callback.answer("Голос «За» учтён")
        elif action == "no":
            vote.no.add(user.id)
            vote.names[user.id] = name
            await callback.answer("Голос «Против» учтён")
        else:
            await callback.answer("Неизвестное действие", show_alert=True)
            return

        if _vote_passed(vote):
            if vote.action == "ban":
                ban_command(vote.chat_id, vote.command, vote.initiator_name)
                label = BANNABLE_COMMANDS.get(vote.command, vote.command)
                await _finish_vote(
                    callback.bot,
                    vote,
                    True,
                    f"🚫 <b>Закрыто!</b> <code>/{vote.command}</code> ({label}) больше не работает в чате.",
                )
            else:
                unban_command(vote.chat_id, vote.command)
                await _finish_vote(
                    callback.bot,
                    vote,
                    True,
                    f"✅ <b>Открыто!</b> <code>/{vote.command}</code> снова доступна.",
                )
            return

        if _vote_failed(vote):
            await _finish_vote(
                callback.bot,
                vote,
                False,
                "❌ Голосование провалено — большинство против.",
            )
            return

        if callback.message:
            try:
                await callback.message.edit_text(
                    _vote_text(vote),
                    reply_markup=_vote_keyboard(vote.vote_id),
                )
            except Exception:
                pass

    @dp.message(Command("suicide"))
    async def suicide_cmd(message: types.Message):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("🗳️ Голосование работает только в группе!")
            return

        user = message.from_user
        if not user:
            return

        chat_id = message.chat.id

        if is_chat_suicided(chat_id):
            await message.reply("💀 Бот уже «мёртв» в этом чате. Восстановить нельзя.")
            return

        if _active_suicide_vote(chat_id):
            await message.reply("⏳ Уже идёт голосование за /suicide. Жми кнопки там.")
            return

        if _active_vote(chat_id):
            await message.reply("⏳ Уже идёт другое голосование в этом чате.")
            return

        name = _user_name(user)
        ensure_user(user.id, name)
        required = await _suicide_required_voters(message.bot, chat_id)

        if not required:
            await message.reply("🍺 Нет активных игроков бота в этом чате.")
            return

        if user.id not in required:
            await message.reply("🚫 Голосовать могут только игроки бота, которые сейчас в чате.")
            return

        vote_id = uuid.uuid4().hex[:8]
        vote = SuicideVote(
            vote_id=vote_id,
            chat_id=chat_id,
            initiator_id=user.id,
            initiator_name=name,
            required=required,
            agreed={user.id},
            names={user.id: name},
            created_at=int(time.time()),
        )
        _suicide_votes[vote_id] = vote
        _chat_suicide_vote[chat_id] = vote_id

        if _suicide_passed(vote):
            set_chat_suicide(chat_id, name)
            _cleanup_suicide_vote(vote)
            await message.reply(
                "💀 Большинство уже за — бот «умер». Все команды отключены навсегда."
            )
            return

        sent = await message.reply(
            _suicide_vote_text(vote),
            reply_markup=_suicide_vote_keyboard(vote_id),
        )
        vote.message_id = sent.message_id

    @dp.callback_query(F.data.startswith("sui:"))
    async def suicide_vote_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        _, action, vote_id = parts
        vote = _suicide_votes.get(vote_id)
        if not vote:
            await callback.answer("Голосование уже неактуально", show_alert=True)
            return

        if time.time() - vote.created_at > SUICIDE_VOTE_TTL:
            await _finish_suicide_vote(
                callback.bot,
                vote,
                "⏰ Время вышло — голосование отменено.",
            )
            await callback.answer("Время вышло", show_alert=True)
            return

        user = callback.from_user
        if not user:
            return

        if not await _is_chat_member(callback.bot, vote.chat_id, user.id):
            await callback.answer("Ты не в этом чате", show_alert=True)
            return

        if user.id not in vote.required:
            await callback.answer("Ты не в списке активных игроков бота", show_alert=True)
            return

        if user.id in vote.agreed:
            await callback.answer("Ты уже согласился")
            return
        if user.id in vote.declined:
            await callback.answer("Ты уже проголосовал против")
            return

        name = _user_name(user)

        if action == "no":
            vote.declined.add(user.id)
            vote.names[user.id] = name
            await callback.answer("Ты проголосовал против")
            if _suicide_failed(vote):
                await _finish_suicide_vote(
                    callback.bot,
                    vote,
                    "❌ Голосование провалено — большинство против.",
                )
                return
        elif action == "yes":
            vote.agreed.add(user.id)
            vote.names[user.id] = name
            await callback.answer("Ты согласился")
            if _suicide_passed(vote):
                set_chat_suicide(vote.chat_id, vote.initiator_name)
                await _finish_suicide_vote(
                    callback.bot,
                    vote,
                    "💀 <b>Большинство согласно!</b> Команды бота в этом чате отключены навсегда.",
                )
                return
        else:
            await callback.answer("Неизвестное действие", show_alert=True)
            return

        if callback.message:
            try:
                await callback.message.edit_text(
                    _suicide_vote_text(vote),
                    reply_markup=_suicide_vote_keyboard(vote.vote_id),
                )
            except Exception:
                pass
