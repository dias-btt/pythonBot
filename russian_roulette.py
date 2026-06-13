import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db import add_score, ensure_user, get_score

LOBBY_TTL = 15 * 60
TURN_TIMEOUT = 25
MAX_PLAYERS = 6
CHAMBERS = 6

LOBBY_LINES = [
    "В комнате пахнет перегаром и страхом.",
    "Кто-то уже шепчет «я передумал».",
    "Малик бы не одобрил. Но вы же не Малик.",
    "Ставки сделаны. Назад дороги почти нет.",
]

SPIN_LINES = [
    "🎲 Барабан визжит как душа на исповеди...",
    "🎲 Щёлк-щёлк-щёлк... револьвер не прощает слабых.",
    "🎲 Палец судьбы крутит цилиндр. Куда встанет пуля?",
]

PULL_BUILDUP = [
    "🔫 Палец ложится на спуск...",
    "😰 В чате тишина. Даже мемы замолкли.",
    "💀 Сердце бьётся в такт секундомеру...",
    "🥶 Кто-то вспомнил, что завтра на работу.",
]

CLICK_LINES = [
    "💨 <b>Щёлк.</b> Пусто. Ты жив. Пока.",
    "😮‍💨 Холостой. Барабан проехал мимо черепа.",
    "🫠 Выдохнули все. Ты — ещё в игре.",
    "🍀 Сегодня не твой день умирать. Следующий — волнуйся.",
]

BANG_LINES = [
    "💥 <b>БАХ!</b> Мозги на аватарку, душа в /dev/null.",
    "☠️ <b>Выстрел!</b> Чат ставит реакцию 💀 и идёт дальше.",
    "🩸 <b>Попало.</b> Револьвер не шутит — баллы уже не вернуть.",
    "⚰️ <b>Конец.</b> Ты герой... но только на 3 секунды.",
]

WIN_LINES = [
    "👑 Последний выживший забирает весь котёл!",
    "🏆 Ты пережил всех — теперь пей за их счёт!",
    "💰 Фортуна любит безумцев. Кошелёк полон.",
    "🍾 Победитель! Остальные уже в больнице баллов.",
]

TIMEOUT_LINES = [
    "⏰ Трусишь? Спуск нажали за тебя автоматически!",
    "⌛ Время вышло — револьвер не ждёт нерешительных.",
]


@dataclass
class RouletteGame:
    game_id: str
    chat_id: int
    host_id: int
    host_name: str
    stake: int
    phase: str = "lobby"
    players: dict[int, str] = field(default_factory=dict)
    alive: list[int] = field(default_factory=list)
    turn_index: int = 0
    bullet_pos: int = 1
    current_chamber: int = 1
    spun_this_turn: bool = False
    pot: int = 0
    lobby_msg_id: int = 0
    game_msg_id: int = 0
    created_at: int = 0
    turn_started_at: int = 0
    finished: bool = False


_games: dict[str, RouletteGame] = {}
_chat_game: dict[int, str] = {}
_turn_tasks: dict[str, asyncio.Task] = {}
_lobby_tasks: dict[str, asyncio.Task] = {}
_lock = asyncio.Lock()


def _user_name(user: types.User) -> str:
    return user.username or user.first_name or "Анон"


def _game_by_chat(chat_id: int) -> RouletteGame | None:
    game_id = _chat_game.get(chat_id)
    if not game_id:
        return None
    game = _games.get(game_id)
    if not game or game.finished:
        return None
    return game


def _cancel_task(tasks: dict[str, asyncio.Task], key: str) -> None:
    task = tasks.pop(key, None)
    if task and not task.done():
        task.cancel()


def _cleanup_game(game: RouletteGame) -> None:
    game.finished = True
    _chat_game.pop(game.chat_id, None)
    _games.pop(game.game_id, None)
    _cancel_task(_turn_tasks, game.game_id)
    _cancel_task(_lobby_tasks, game.game_id)


async def _edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    if not chat_id or not message_id:
        return
    try:
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup,
        )
    except Exception:
        pass


def _lobby_text(game: RouletteGame) -> str:
    player_lines = [
        f"  {'👑' if uid == game.host_id else '🔫'} {name}"
        + (f" — {get_score(uid)} б." if game.phase == "lobby" else "")
        for uid, name in game.players.items()
    ]
    can_start = len(game.players) >= 2
    start_hint = (
        "✅ Можно начинать — жми <b>СТАРТ</b>!"
        if can_start
        else "⏳ Нужно минимум <b>2</b> игрока для старта."
    )
    return (
        f"🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n"
        f"{random.choice(LOBBY_LINES)}\n\n"
        f"👑 Хост: <b>{game.host_name}</b>\n"
        f"💰 Ставка: <b>{game.stake}</b> баллов алкаша\n"
        f"🏆 Котёл: <b>{game.stake * len(game.players)}</b> (если старт сейчас)\n"
        f"👥 Игроки: <b>{len(game.players)}/{MAX_PLAYERS}</b>\n\n"
        + "\n".join(player_lines)
        + f"\n\n{start_hint}"
    )


def _lobby_keyboard(game: RouletteGame) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🔫 Войти", callback_data=f"rtr:join:{game.game_id}"),
            InlineKeyboardButton(text="🚪 Выйти", callback_data=f"rtr:leave:{game.game_id}"),
        ]
    ]
    if game.host_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="▶️ СТАРТ",
                    callback_data=f"rtr:start:{game.game_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"rtr:cancel:{game.game_id}",
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _turn_text(game: RouletteGame) -> str:
    current_id = game.alive[game.turn_index]
    current_name = game.players[current_id]
    remaining = max(0, TURN_TIMEOUT - (int(time.time()) - game.turn_started_at))
    alive_lines = " → ".join(
        f"<b>{game.players[uid]}</b>" if uid == current_id else game.players[uid]
        for uid in game.alive
    )
    pressure = ""
    if remaining <= 5:
        pressure = "\n🔥 <b>ЖМИ СПУСК ИЛИ КРУТИ БАРАБАН — ВРЕМЯ УХОДИТ!</b>"
    elif remaining <= 12:
        pressure = "\n⚡ Револьвер холодеет. Не тяни."
    spin_hint = "🎲 Перекрутить можно 1 раз за ход." if not game.spun_this_turn else "🎲 Барабан уже крутили в этом ходу."
    return (
        f"🔫 <b>РУССКАЯ РУЛЕТКА — ИГРА</b>\n\n"
        f"💰 Котёл: <b>{game.pot}</b> баллов\n"
        f"🎯 Ход: <b>{current_name}</b>\n"
        f"👥 Живы: {alive_lines}\n"
        f"🧨 Позиция барабана: <b>{game.current_chamber}/{CHAMBERS}</b>\n"
        f"{spin_hint}\n\n"
        f"⏳ На ход: <b>{remaining}</b> сек.{pressure}"
    )


def _turn_keyboard(game: RouletteGame) -> InlineKeyboardMarkup:
    current_id = game.alive[game.turn_index]
    rows = [
        [
            InlineKeyboardButton(
                text="🔫 СПУСК",
                callback_data=f"rtr:pull:{game.game_id}:{current_id}",
            )
        ]
    ]
    if not game.spun_this_turn:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎲 КРУТИТЬ БАРАБАН",
                    callback_data=f"rtr:spin:{game.game_id}:{current_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _update_lobby(bot: Bot, game: RouletteGame) -> None:
    await _edit_message(
        bot,
        game.chat_id,
        game.lobby_msg_id,
        _lobby_text(game),
        _lobby_keyboard(game),
    )


async def _update_turn(bot: Bot, game: RouletteGame) -> None:
    await _edit_message(
        bot,
        game.chat_id,
        game.game_msg_id,
        _turn_text(game),
        _turn_keyboard(game),
    )


async def _lobby_watch(bot: Bot, game: RouletteGame) -> None:
    try:
        while not game.finished and game.phase == "lobby":
            if time.time() - game.created_at >= LOBBY_TTL:
                await _edit_message(
                    bot,
                    game.chat_id,
                    game.lobby_msg_id,
                    "🔫 <b>РУССКАЯ РУЛЕТКА отменена</b>\n\n⏰ Лобби простояло слишком долго.",
                )
                _cleanup_game(game)
                return
            await _update_lobby(bot, game)
            await asyncio.sleep(5)
    except asyncio.CancelledError:
        return


async def _turn_watch(bot: Bot, game: RouletteGame) -> None:
    try:
        while not game.finished and game.phase == "playing":
            elapsed = int(time.time()) - game.turn_started_at
            if elapsed >= TURN_TIMEOUT:
                current_id = game.alive[game.turn_index]
                await _edit_message(
                    bot,
                    game.chat_id,
                    game.game_msg_id,
                    _turn_text(game) + f"\n\n{random.choice(TIMEOUT_LINES)}",
                    None,
                )
                await asyncio.sleep(0.8)
                await _process_pull(bot, game, current_id, auto=True)
                return
            await _update_turn(bot, game)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


async def _start_turn(bot: Bot, game: RouletteGame) -> None:
    game.spun_this_turn = False
    game.turn_started_at = int(time.time())
    _cancel_task(_turn_tasks, game.game_id)
    await _update_turn(bot, game)
    _turn_tasks[game.game_id] = asyncio.create_task(_turn_watch(bot, game))


async def _finish_winner(bot: Bot, game: RouletteGame, winner_id: int) -> None:
    winner_name = game.players[winner_id]
    add_score(winner_id, game.pot)
    total = get_score(winner_id)
    _cancel_task(_turn_tasks, game.game_id)
    await _edit_message(
        bot,
        game.chat_id,
        game.game_msg_id,
        f"🏆 <b>ПОБЕДА!</b>\n\n"
        f"{random.choice(WIN_LINES)}\n\n"
        f"👑 <b>{winner_name}</b> забирает <b>{game.pot}</b> баллов!\n"
        f"🏦 Баланс: <b>{total}</b>",
        None,
    )
    _cleanup_game(game)


async def _eliminate(bot: Bot, game: RouletteGame, user_id: int) -> None:
    game.alive = [uid for uid in game.alive if uid != user_id]
    if len(game.alive) == 1:
        await _finish_winner(bot, game, game.alive[0])
        return
    if game.turn_index >= len(game.alive):
        game.turn_index = 0
    await _start_turn(bot, game)


async def _process_pull(bot: Bot, game: RouletteGame, user_id: int, auto: bool = False) -> None:
    if game.finished or game.phase != "playing":
        return
    if game.alive[game.turn_index] != user_id:
        return

    _cancel_task(_turn_tasks, game.game_id)
    name = game.players[user_id]

    for line in PULL_BUILDUP:
        await _edit_message(
            bot,
            game.chat_id,
            game.game_msg_id,
            f"🔫 <b>{name}</b> нажимает на спуск...\n\n{line}",
            None,
        )
        await asyncio.sleep(1.2)

    hit = game.current_chamber == game.bullet_pos
    if hit:
        await _edit_message(
            bot,
            game.chat_id,
            game.game_msg_id,
            f"🔫 <b>{name}</b>\n\n{random.choice(BANG_LINES)}",
            None,
        )
        await asyncio.sleep(2)
        await _eliminate(bot, game, user_id)
        return

    game.current_chamber += 1
    if game.current_chamber > CHAMBERS:
        game.current_chamber = 1
        game.bullet_pos = random.randint(1, CHAMBERS)

    await _edit_message(
        bot,
        game.chat_id,
        game.game_msg_id,
        f"🔫 <b>{name}</b>\n\n{random.choice(CLICK_LINES)}",
        None,
    )
    await asyncio.sleep(1.5)

    game.turn_index = (game.turn_index + 1) % len(game.alive)
    await _start_turn(bot, game)


async def _process_spin(bot: Bot, game: RouletteGame, user_id: int) -> None:
    if game.finished or game.phase != "playing":
        return
    if game.alive[game.turn_index] != user_id:
        return
    if game.spun_this_turn:
        return

    _cancel_task(_turn_tasks, game.game_id)
    game.spun_this_turn = True
    name = game.players[user_id]

    await _edit_message(
        bot,
        game.chat_id,
        game.game_msg_id,
        f"🎲 <b>{name}</b> крутит барабан...\n\n{random.choice(SPIN_LINES)}",
        None,
    )
    await asyncio.sleep(2)
    game.bullet_pos = random.randint(1, CHAMBERS)
    game.current_chamber = 1

    await _edit_message(
        bot,
        game.chat_id,
        game.game_msg_id,
        f"🎲 Барабан остановился.\n<b>{name}</b>, твой ход — спуск или ещё раз не выйдет.",
        _turn_keyboard(game),
    )
    game.turn_started_at = int(time.time())
    _turn_tasks[game.game_id] = asyncio.create_task(_turn_watch(bot, game))


async def _start_game(bot: Bot, game: RouletteGame) -> None:
    broke = []
    for uid in list(game.players):
        if get_score(uid) < game.stake:
            broke.append(game.players[uid])
            game.players.pop(uid, None)

    if broke:
        if len(game.players) < 2:
            await _edit_message(
                bot,
                game.chat_id,
                game.lobby_msg_id,
                "🔫 <b>РУССКАЯ РУЛЕТКА отменена</b>\n\n"
                "Недостаточно игроков после проверки баланса.\n"
                "🚫 Не хватало баллов у: " + ", ".join(broke),
                None,
            )
            _cleanup_game(game)
            return
        await _edit_message(
            bot,
            game.chat_id,
            game.lobby_msg_id,
            _lobby_text(game)
            + "\n\n🚫 Выгнаны за нехватку баллов: "
            + ", ".join(broke)
            + "\n▶️ Стартуем с оставшимися...",
            None,
        )
        await asyncio.sleep(1.5)

    for uid in game.players:
        add_score(uid, -game.stake)

    game.pot = game.stake * len(game.players)
    game.alive = list(game.players.keys())
    random.shuffle(game.alive)
    game.turn_index = 0
    game.bullet_pos = random.randint(1, CHAMBERS)
    game.current_chamber = 1
    game.phase = "playing"
    _cancel_task(_lobby_tasks, game.game_id)

    order = " → ".join(game.players[uid] for uid in game.alive)
    sent = await bot.send_message(
        game.chat_id,
        f"☠️ <b>ИГРА НАЧАЛАСЬ!</b>\n\n"
        f"💰 Котёл: <b>{game.pot}</b> баллов\n"
        f"💸 С каждого снято: <b>{game.stake}</b>\n"
        f"🎯 Порядок: {order}\n\n"
        f"Один патрон в барабане. Кто последний — забирает всё.",
    )
    game.game_msg_id = sent.message_id
    await _start_turn(bot, game)


def register_russian_roulette(dp: Dispatcher) -> None:
    @dp.message(Command("roulette"))
    async def roulette_cmd(message: types.Message, command: CommandObject):
        if message.chat.type not in ("group", "supergroup"):
            await message.reply("🔫 Русская рулетка работает только в группе!")
            return

        user = message.from_user
        if not user:
            return

        arg = (command.args or "").strip().lower()
        chat_id = message.chat.id

        if arg in ("help", "?", "помощь"):
            await message.reply(
                "🔫 <b>РУССКАЯ РУЛЕТКА</b>\n\n"
                "<code>/roulette 5000</code> — создать игру со ставкой\n"
                "<code>/roulette cancel</code> — отменить лобби (только хост)\n\n"
                "• Хост задаёт ставку и может стартовать когда угодно\n"
                "• Минимум <b>2</b> игрока, максимум <b>6</b>\n"
                "• Ставка списывается при старте\n"
                "• На ходу: <b>спуск</b> или <b>крутить барабан</b> (1 раз)\n"
                "• Не успел за <b>25 сек</b> — спуск нажмут за тебя\n"
                "• Последний выживший забирает весь котёл"
            )
            return

        if arg in ("cancel", "отмена", "stop"):
            game = _game_by_chat(chat_id)
            if not game or game.phase != "lobby":
                await message.reply("🚫 Нет активного лобби для отмены.")
                return
            if user.id != game.host_id:
                await message.reply("🚫 Отменить может только хост.")
                return
            await _edit_message(
                message.bot,
                game.chat_id,
                game.lobby_msg_id,
                f"🔫 <b>РУССКАЯ РУЛЕТКА отменена</b>\n\nХост <b>{game.host_name}</b> передумал.",
                None,
            )
            _cleanup_game(game)
            await message.reply("❌ Лобби закрыто.")
            return

        if not arg or not arg.isdigit():
            active = _game_by_chat(chat_id)
            if active and active.phase == "lobby":
                await message.reply(
                    "⏳ В этом чате уже идёт набор в рулетку.\n"
                    f"Ставка: <b>{active.stake}</b>. Жми кнопки в сообщении лобби."
                )
            else:
                await message.reply(
                    "🔫 Укажи ставку: <code>/roulette 5000</code>\n"
                    "Справка: <code>/roulette help</code>"
                )
            return

        stake = int(arg)
        if stake < 1:
            await message.reply("🚫 Ставка должна быть хотя бы 1 балл.")
            return

        ensure_user(user.id, _user_name(user))
        if get_score(user.id) < stake:
            await message.reply(
                f"🚫 Не хватает баллов. У тебя <b>{get_score(user.id)}</b>, ставка <b>{stake}</b>."
            )
            return

        async with _lock:
            if _game_by_chat(chat_id):
                await message.reply("⏳ В этом чате уже есть активная рулетка!")
                return

            game_id = uuid.uuid4().hex[:8]
            game = RouletteGame(
                game_id=game_id,
                chat_id=chat_id,
                host_id=user.id,
                host_name=_user_name(user),
                stake=stake,
                created_at=int(time.time()),
            )
            game.players[user.id] = game.host_name
            _games[game_id] = game
            _chat_game[chat_id] = game_id

        sent = await message.reply(
            _lobby_text(game),
            reply_markup=_lobby_keyboard(game),
        )
        game.lobby_msg_id = sent.message_id
        _lobby_tasks[game.game_id] = asyncio.create_task(_lobby_watch(message.bot, game))

    @dp.callback_query(F.data.startswith("rtr:"))
    async def roulette_callback(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("Ошибка данных", show_alert=True)
            return

        action = parts[1]
        game_id = parts[2]
        game = _games.get(game_id)

        if not game or game.finished:
            await callback.answer("Игра уже неактуальна", show_alert=True)
            return

        user = callback.from_user
        if not user:
            return

        if action == "join":
            if game.phase != "lobby":
                await callback.answer("Набор уже закрыт", show_alert=True)
                return
            if user.id in game.players:
                await callback.answer("Ты уже в игре")
                return
            if len(game.players) >= MAX_PLAYERS:
                await callback.answer("Лобби полное (6/6)", show_alert=True)
                return

            ensure_user(user.id, _user_name(user))
            if get_score(user.id) < game.stake:
                await callback.answer(
                    f"Нужно {game.stake} баллов, у тебя {get_score(user.id)}",
                    show_alert=True,
                )
                return

            game.players[user.id] = _user_name(user)
            await callback.answer("Ты в игре! 🔫")
            await _update_lobby(callback.bot, game)
            return

        if action == "leave":
            if game.phase != "lobby":
                await callback.answer("Игра уже идёт", show_alert=True)
                return
            if user.id not in game.players:
                await callback.answer("Тебя тут и не было")
                return
            if user.id == game.host_id:
                await callback.answer("Хост не может выйти — жми Отмена", show_alert=True)
                return

            game.players.pop(user.id, None)
            await callback.answer("Ты вышел")
            await _update_lobby(callback.bot, game)
            return

        if action == "cancel":
            if game.phase != "lobby":
                await callback.answer("Уже поздно отменять", show_alert=True)
                return
            if user.id != game.host_id:
                await callback.answer("Только хост может отменить", show_alert=True)
                return

            await _edit_message(
                callback.bot,
                game.chat_id,
                game.lobby_msg_id,
                f"🔫 <b>РУССКАЯ РУЛЕТКА отменена</b>\n\nХост <b>{game.host_name}</b> передумал.",
                None,
            )
            _cleanup_game(game)
            await callback.answer("Лобби закрыто")
            return

        if action == "start":
            if game.phase != "lobby":
                await callback.answer("Игра уже началась", show_alert=True)
                return
            if user.id != game.host_id:
                await callback.answer("Стартовать может только хост", show_alert=True)
                return
            if len(game.players) < 2:
                await callback.answer("Нужно минимум 2 игрока!", show_alert=True)
                return

            await callback.answer("☠️ Поехали!")
            await _edit_message(
                callback.bot,
                game.chat_id,
                game.lobby_msg_id,
                _lobby_text(game) + "\n\n▶️ <b>Хост запускает игру...</b>",
                None,
            )
            await _start_game(callback.bot, game)
            return

        if action == "pull":
            if len(parts) != 4 or game.phase != "playing":
                await callback.answer("Сейчас не твой момент", show_alert=True)
                return
            try:
                actor_id = int(parts[3])
            except ValueError:
                await callback.answer("Ошибка данных", show_alert=True)
                return
            if user.id != actor_id:
                await callback.answer("Это не твой ход!", show_alert=True)
                return
            if game.alive[game.turn_index] != actor_id:
                await callback.answer("Уже не твой ход", show_alert=True)
                return

            await callback.answer("🔫 Спуск...")
            await _process_pull(callback.bot, game, actor_id)
            return

        if action == "spin":
            if len(parts) != 4 or game.phase != "playing":
                await callback.answer("Сейчас не твой момент", show_alert=True)
                return
            try:
                actor_id = int(parts[3])
            except ValueError:
                await callback.answer("Ошибка данных", show_alert=True)
                return
            if user.id != actor_id:
                await callback.answer("Это не твой ход!", show_alert=True)
                return
            if game.spun_this_turn:
                await callback.answer("Барабан уже крутили в этом ходу", show_alert=True)
                return

            await callback.answer("🎲 Крутим...")
            await _process_spin(callback.bot, game, actor_id)
            return

        await callback.answer("Неизвестное действие", show_alert=True)
