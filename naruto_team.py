import asyncio
import random
from typing import Any

from aiogram import BaseMiddleware, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import TelegramObject

from naruto_characters import NARUTO_CHARACTERS

NARUTO_COMMANDS = ("/naruto_team", "/naruto")

POSITIONS = [
    ("captain", "👑 Капитан"),
    ("vice", "⚔️ Заместитель"),
    ("support", "🎯 Саппорт #1"),
    ("support2", "🎯 Саппорт #2"),
    ("healer", "💚 Хилер"),
    ("tank", "🛡️ Танк"),
]

ROLE_KEYS = {
    "captain": "captain",
    "vice": "vice",
    "support": "support",
    "support2": "support",
    "healer": "healer",
    "tank": "tank",
}

MESSAGE_DELAY = 1.5

_busy_chats: set[int] = set()
_busy_lock = asyncio.Lock()


def is_chat_busy(chat_id: int) -> bool:
    return chat_id in _busy_chats


async def _acquire_chat(chat_id: int) -> bool:
    async with _busy_lock:
        if chat_id in _busy_chats:
            return False
        _busy_chats.add(chat_id)
        return True


async def _release_chat(chat_id: int) -> None:
    async with _busy_lock:
        _busy_chats.discard(chat_id)


def _pick_team() -> list[dict[str, Any]]:
    chars = random.sample(NARUTO_CHARACTERS, 6)
    team = []
    for i, (role_key, role_label) in enumerate(POSITIONS):
        char = chars[i]
        rating_key = ROLE_KEYS[role_key]
        base = char["ratings"][rating_key]
        rating = max(1, min(100, base + random.randint(-5, 5)))
        team.append(
            {
                "role_key": role_key,
                "role_label": role_label,
                "character": char,
                "rating": rating,
            }
        )
    return team


def _rating_bar(rating: int) -> str:
    filled = rating // 10
    return "█" * filled + "░" * (10 - filled)


def _team_verdict(avg: float) -> str:
    if avg >= 90:
        return "🔥 Легендарный отряд! Уровень Kage — враги уже сдаются."
    if avg >= 80:
        return "⚡ Очень сильная команда! Jonin-squad vibes."
    if avg >= 70:
        return "✅ Достойный отряд. На миссию B-rank точно потянете."
    if avg >= 60:
        return "😐 Среднячок, но с потенциалом. Главное — не ссориться."
    if avg >= 50:
        return "😅 Chunin energy. Будет больно, но весело."
    return "💀 Genin squad. Может, лучше остаться в деревне?"


def _format_member(slot: dict[str, Any]) -> str:
    char = slot["character"]
    rating = slot["rating"]
    return (
        f"{slot['role_label']}\n"
        f"<b>{char['name']}</b> ({char['village']})\n"
        f"Рейтинг: {rating}/100 {_rating_bar(rating)}"
    )


class NarutoTeamBlockMiddleware(BaseMiddleware):
    """Блокирует другие команды пока формируется команда Naruto."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if not isinstance(event, types.Message):
            return await handler(event, data)

        text = (event.text or "").strip()
        if not text.startswith("/"):
            return await handler(event, data)

        if not is_chat_busy(event.chat.id):
            return await handler(event, data)

        cmd = text.split()[0].split("@")[0].lower()
        if cmd in NARUTO_COMMANDS:
            await event.reply("⏳ Команда уже формируется! Дождись финала.")
            return

        await event.reply(
            "⏳ Сейчас формируется команда Naruto.\n"
            "Другие команды временно заблокированы."
        )
        return


async def _run_naruto_team(message: types.Message) -> None:
    chat_id = message.chat.id

    from naruto_duel import is_duel_active
    if is_duel_active(chat_id):
        await message.reply("⏳ В этом чате идёт duel — подожди окончания!")
        return

    if not await _acquire_chat(chat_id):
        await message.reply("⏳ Команда уже формируется в этом чате!")
        return

    try:
        user = message.from_user
        user_name = (user.first_name or user.username or "Ниндзя") if user else "Ниндзя"
        team = _pick_team()

        await message.reply(
            f"🍥 <b>{user_name}</b>, начинаем формирование команды Naruto!\n"
            f"Сейчас назначим 6 бойцов..."
        )
        await asyncio.sleep(MESSAGE_DELAY)

        for slot in team:
            await message.reply(_format_member(slot))
            await asyncio.sleep(MESSAGE_DELAY)

        ratings = [s["rating"] for s in team]
        overall = round(sum(ratings) / len(ratings), 1)
        verdict = _team_verdict(overall)

        lines = ["🍥 <b>ИТОГОВАЯ КОМАНДА</b>\n"]
        for slot in team:
            char = slot["character"]
            lines.append(
                f"{slot['role_label']}: <b>{char['name']}</b> — {slot['rating']}/100"
            )

        lines.append("")
        lines.append(f"📊 <b>Общий рейтинг:</b> {overall}/100 {_rating_bar(int(overall))}")
        lines.append(f"\n{verdict}")

        await message.reply("\n".join(lines))

    except Exception as e:
        await message.reply(f"❌ Не смог собрать команду: {e}")

    finally:
        await _release_chat(chat_id)


def register_naruto_team(dp: Dispatcher) -> None:
    dp.message.middleware(NarutoTeamBlockMiddleware())

    @dp.message(Command("naruto_team", "naruto"))
    async def naruto_team(message: types.Message):
        await _run_naruto_team(message)
