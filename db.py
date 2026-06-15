import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator

DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = os.getenv("SQLITE_PATH", "alkashi.db")

if os.getenv("RAILWAY_ENVIRONMENT") and not DATABASE_URL:
    raise RuntimeError(
        "На Railway нужен DATABASE_URL (Reference из Postgres). "
        "Без него бот не должен стартовать."
    )

_use_pg = bool(DATABASE_URL)


def _pg_dsn(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


@contextmanager
def _connection() -> Iterator[Any]:
    if _use_pg:
        import psycopg2

        conn = psycopg2.connect(_pg_dsn(DATABASE_URL))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _execute(conn: Any, sql: str, params: tuple = ()) -> Any:
    cur = conn.cursor()
    if _use_pg:
        sql = sql.replace("?", "%s")
    cur.execute(sql, params)
    return cur


def _init_db() -> None:
    with _connection() as conn:
        if _use_pg:
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS alkashi (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    score INTEGER DEFAULT 0,
                    last_drink BIGINT DEFAULT 0
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS stickers (
                    file_id TEXT PRIMARY KEY,
                    added_by BIGINT,
                    added_at BIGINT
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS naruto_duel_stats (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT '',
                    wins INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    points INTEGER NOT NULL DEFAULT 0,
                    damage_dealt INTEGER NOT NULL DEFAULT 0,
                    damage_taken INTEGER NOT NULL DEFAULT 0
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS naruto_duel_h2h (
                    user_a BIGINT NOT NULL,
                    user_b BIGINT NOT NULL,
                    wins_a INTEGER NOT NULL DEFAULT 0,
                    wins_b INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_a, user_b)
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS debts (
                    debt_id TEXT PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    borrower_id BIGINT NOT NULL,
                    borrower_name TEXT NOT NULL,
                    lender_id BIGINT NOT NULL,
                    lender_name TEXT NOT NULL,
                    principal INTEGER NOT NULL,
                    accrued_interest INTEGER NOT NULL DEFAULT 0,
                    repaid INTEGER NOT NULL DEFAULT 0,
                    interest_rate REAL NOT NULL,
                    terms_label TEXT NOT NULL DEFAULT '',
                    due_at BIGINT NOT NULL,
                    created_at BIGINT NOT NULL,
                    last_interest_at BIGINT NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    offer_msg_id BIGINT DEFAULT 0
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS steal_daily (
                    user_id BIGINT NOT NULL,
                    steal_date TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, steal_date)
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS command_bans (
                    chat_id BIGINT NOT NULL,
                    command TEXT NOT NULL,
                    banned_at BIGINT NOT NULL,
                    banned_by TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (chat_id, command)
                )
                """,
            )
        else:
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS alkashi (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    score INTEGER DEFAULT 0,
                    last_drink INTEGER DEFAULT 0
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS stickers (
                    file_id TEXT PRIMARY KEY,
                    added_by INTEGER,
                    added_at INTEGER
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS naruto_duel_stats (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT '',
                    wins INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    points INTEGER NOT NULL DEFAULT 0,
                    damage_dealt INTEGER NOT NULL DEFAULT 0,
                    damage_taken INTEGER NOT NULL DEFAULT 0
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS naruto_duel_h2h (
                    user_a INTEGER NOT NULL,
                    user_b INTEGER NOT NULL,
                    wins_a INTEGER NOT NULL DEFAULT 0,
                    wins_b INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_a, user_b)
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS debts (
                    debt_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    borrower_id INTEGER NOT NULL,
                    borrower_name TEXT NOT NULL,
                    lender_id INTEGER NOT NULL,
                    lender_name TEXT NOT NULL,
                    principal INTEGER NOT NULL,
                    accrued_interest INTEGER NOT NULL DEFAULT 0,
                    repaid INTEGER NOT NULL DEFAULT 0,
                    interest_rate REAL NOT NULL,
                    terms_label TEXT NOT NULL DEFAULT '',
                    due_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_interest_at INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    offer_msg_id INTEGER DEFAULT 0
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS steal_daily (
                    user_id INTEGER NOT NULL,
                    steal_date TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, steal_date)
                )
                """,
            )
            _execute(
                conn,
                """
                CREATE TABLE IF NOT EXISTS command_bans (
                    chat_id INTEGER NOT NULL,
                    command TEXT NOT NULL,
                    banned_at INTEGER NOT NULL,
                    banned_by TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (chat_id, command)
                )
                """,
            )


_init_db()


def _insert_ignore(conn: Any, table: str, columns: list[str], values: tuple) -> None:
    cols = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    if _use_pg:
        _execute(
            conn,
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            values,
        )
    else:
        _execute(
            conn,
            f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})",
            values,
        )


def add_sticker(file_id: str, user_id: int) -> None:
    with _connection() as conn:
        _insert_ignore(
            conn,
            "stickers",
            ["file_id", "added_by", "added_at"],
            (file_id, user_id, int(time.time())),
        )


def sticker_exists(file_id: str) -> bool:
    with _connection() as conn:
        cur = _execute(conn, "SELECT 1 FROM stickers WHERE file_id = ?", (file_id,))
        return cur.fetchone() is not None


def get_random_sticker() -> str | None:
    with _connection() as conn:
        cur = _execute(conn, "SELECT file_id FROM stickers ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def ensure_user(user_id: int, username: str) -> None:
    with _connection() as conn:
        _insert_ignore(conn, "alkashi", ["user_id", "username", "score"], (user_id, username, 0))


def add_score(user_id: int, points: int) -> None:
    with _connection() as conn:
        _execute(
            conn,
            "UPDATE alkashi SET score = score + ? WHERE user_id = ?",
            (points, user_id),
        )


def set_score(user_id: int, score: int) -> None:
    with _connection() as conn:
        _execute(
            conn,
            "UPDATE alkashi SET score = ? WHERE user_id = ?",
            (score, user_id),
        )


def top_users(limit: int = 10):
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT username, score FROM alkashi ORDER BY score DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()


def get_last_drink(user_id: int) -> int:
    with _connection() as conn:
        cur = _execute(conn, "SELECT last_drink FROM alkashi WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def update_last_drink(user_id: int) -> None:
    with _connection() as conn:
        _execute(
            conn,
            "UPDATE alkashi SET last_drink = ? WHERE user_id = ?",
            (int(time.time()), user_id),
        )


def get_score(user_id: int) -> int:
    with _connection() as conn:
        cur = _execute(conn, "SELECT score FROM alkashi WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else 0


def find_user_id_by_username(username: str) -> int | None:
    name = username.lstrip("@").strip()
    if not name:
        return None
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT user_id FROM alkashi WHERE LOWER(username) = LOWER(?)",
            (name,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def transfer_score(from_id: int, to_id: int, amount: int) -> int:
    with _connection() as conn:
        cur = _execute(conn, "SELECT score FROM alkashi WHERE user_id = ?", (from_id,))
        row = cur.fetchone()
        available = row[0] if row else 0
        actual = min(max(amount, 0), available)
        if actual <= 0:
            return 0
        _execute(
            conn,
            "UPDATE alkashi SET score = score - ? WHERE user_id = ?",
            (actual, from_id),
        )
        _execute(
            conn,
            "UPDATE alkashi SET score = score + ? WHERE user_id = ?",
            (actual, to_id),
        )
        return actual


def get_steal_count_today(user_id: int, day: str | None = None) -> int:
    from datetime import date

    steal_date = day or date.today().isoformat()
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT count FROM steal_daily WHERE user_id = ? AND steal_date = ?",
            (user_id, steal_date),
        )
        row = cur.fetchone()
    return row[0] if row else 0


def increment_steal_count(user_id: int) -> int:
    from datetime import date

    steal_date = date.today().isoformat()
    with _connection() as conn:
        if _use_pg:
            _execute(
                conn,
                """
                INSERT INTO steal_daily (user_id, steal_date, count)
                VALUES (?, ?, 1)
                ON CONFLICT (user_id, steal_date)
                DO UPDATE SET count = steal_daily.count + 1
                """,
                (user_id, steal_date),
            )
        else:
            _execute(
                conn,
                """
                INSERT INTO steal_daily (user_id, steal_date, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, steal_date)
                DO UPDATE SET count = count + 1
                """,
                (user_id, steal_date),
            )
    return get_steal_count_today(user_id, steal_date)


def get_players_with_scores():
    with _connection() as conn:
        cur = _execute(
            conn,
            """
            SELECT user_id, username, score
            FROM alkashi
            WHERE score != 0
            ORDER BY score DESC
            """,
        )
        return cur.fetchall()


def reset_all_scores() -> None:
    with _connection() as conn:
        _execute(conn, "UPDATE alkashi SET score = 0")


def _h2h_key(user1_id: int, user2_id: int) -> tuple[int, int]:
    if user1_id < user2_id:
        return user1_id, user2_id
    return user2_id, user1_id


def ensure_naruto_duel_user(user_id: int, username: str) -> None:
    with _connection() as conn:
        _insert_ignore(
            conn,
            "naruto_duel_stats",
            ["user_id", "username"],
            (user_id, username),
        )
        _execute(
            conn,
            "UPDATE naruto_duel_stats SET username = ? WHERE user_id = ?",
            (username, user_id),
        )


def record_naruto_duel_result(
    user1_id: int,
    user1_name: str,
    user2_id: int,
    user2_name: str,
    winner_id: int | None,
    damage: dict[int, tuple[int, int]],
) -> tuple[int, int, int]:
    ensure_naruto_duel_user(user1_id, user1_name)
    ensure_naruto_duel_user(user2_id, user2_name)

    with _connection() as conn:
        for uid, (dealt, taken) in damage.items():
            _execute(
                conn,
                """
                UPDATE naruto_duel_stats
                SET damage_dealt = damage_dealt + ?,
                    damage_taken = damage_taken + ?
                WHERE user_id = ?
                """,
                (dealt, taken, uid),
            )

        if winner_id is None:
            _execute(
                conn,
                """
                UPDATE naruto_duel_stats
                SET draws = draws + 1, points = points + 1
                WHERE user_id IN (?, ?)
                """,
                (user1_id, user2_id),
            )
        elif winner_id == user1_id:
            _execute(
                conn,
                "UPDATE naruto_duel_stats SET wins = wins + 1, points = points + 3 WHERE user_id = ?",
                (user1_id,),
            )
            _execute(
                conn,
                "UPDATE naruto_duel_stats SET losses = losses + 1 WHERE user_id = ?",
                (user2_id,),
            )
        else:
            _execute(
                conn,
                "UPDATE naruto_duel_stats SET wins = wins + 1, points = points + 3 WHERE user_id = ?",
                (user2_id,),
            )
            _execute(
                conn,
                "UPDATE naruto_duel_stats SET losses = losses + 1 WHERE user_id = ?",
                (user1_id,),
            )

        a_id, b_id = _h2h_key(user1_id, user2_id)
        _insert_ignore(conn, "naruto_duel_h2h", ["user_a", "user_b"], (a_id, b_id))

        if winner_id is None:
            _execute(
                conn,
                "UPDATE naruto_duel_h2h SET draws = draws + 1 WHERE user_a = ? AND user_b = ?",
                (a_id, b_id),
            )
        elif winner_id == a_id:
            _execute(
                conn,
                "UPDATE naruto_duel_h2h SET wins_a = wins_a + 1 WHERE user_a = ? AND user_b = ?",
                (a_id, b_id),
            )
        else:
            _execute(
                conn,
                "UPDATE naruto_duel_h2h SET wins_b = wins_b + 1 WHERE user_a = ? AND user_b = ?",
                (a_id, b_id),
            )

    return get_naruto_duel_h2h(user1_id, user2_id)


def get_naruto_duel_h2h(user1_id: int, user2_id: int) -> tuple[int, int, int]:
    a_id, b_id = _h2h_key(user1_id, user2_id)
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT wins_a, wins_b, draws FROM naruto_duel_h2h WHERE user_a = ? AND user_b = ?",
            (a_id, b_id),
        )
        row = cur.fetchone()
    if not row:
        return 0, 0, 0
    wins_a, wins_b, draws = row
    if user1_id == a_id:
        return wins_a, wins_b, draws
    return wins_b, wins_a, draws


def get_naruto_duel_ratings(limit: int = 20):
    with _connection() as conn:
        cur = _execute(
            conn,
            """
            SELECT username, wins, draws, losses, points, damage_dealt, damage_taken
            FROM naruto_duel_stats
            WHERE wins + draws + losses > 0
            ORDER BY points DESC, wins DESC, damage_dealt DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def _debt_row_to_dict(row) -> dict:
    keys = [
        "debt_id", "chat_id", "borrower_id", "borrower_name", "lender_id", "lender_name",
        "principal", "accrued_interest", "repaid", "interest_rate", "terms_label",
        "due_at", "created_at", "last_interest_at", "status", "offer_msg_id",
    ]
    return dict(zip(keys, row))


def debt_total_owed(debt: dict) -> int:
    return max(0, debt["principal"] + debt["accrued_interest"] - debt["repaid"])


def create_debt_pending(
    debt_id: str,
    chat_id: int,
    borrower_id: int,
    borrower_name: str,
    lender_id: int,
    lender_name: str,
    principal: int,
    offer_msg_id: int = 0,
) -> None:
    now = int(time.time())
    due_at = now + 2 * 3600
    with _connection() as conn:
        _execute(
            conn,
            """
            INSERT INTO debts (
                debt_id, chat_id, borrower_id, borrower_name, lender_id, lender_name,
                principal, interest_rate, terms_label, due_at, created_at, status, offer_msg_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, 'pending', ?)
            """,
            (
                debt_id, chat_id, borrower_id, borrower_name, lender_id, lender_name,
                principal, due_at, now, offer_msg_id,
            ),
        )


def get_debt(debt_id: str) -> dict | None:
    with _connection() as conn:
        cur = _execute(conn, "SELECT * FROM debts WHERE debt_id = ?", (debt_id,))
        row = cur.fetchone()
    return _debt_row_to_dict(row) if row else None


def update_debt_offer_msg(debt_id: str, message_id: int) -> None:
    with _connection() as conn:
        _execute(
            conn,
            "UPDATE debts SET offer_msg_id = ? WHERE debt_id = ?",
            (message_id, debt_id),
        )


def set_debt_status(debt_id: str, status: str) -> None:
    with _connection() as conn:
        _execute(conn, "UPDATE debts SET status = ? WHERE debt_id = ?", (status, debt_id))


def activate_debt(debt_id: str, interest_rate: float, terms_label: str) -> bool:
    debt = get_debt(debt_id)
    if not debt or debt["status"] != "pending":
        return False
    lender_score = get_score(debt["lender_id"])
    if lender_score < debt["principal"]:
        return False
    transferred = transfer_score(debt["lender_id"], debt["borrower_id"], debt["principal"])
    if transferred < debt["principal"]:
        return False
    now = int(time.time())
    due_at = now + 2 * 3600
    with _connection() as conn:
        _execute(
            conn,
            """
            UPDATE debts
            SET status = 'active', interest_rate = ?, terms_label = ?,
                due_at = ?, last_interest_at = ?, created_at = ?
            WHERE debt_id = ?
            """,
            (interest_rate, terms_label, due_at, due_at, now, debt_id),
        )
    return True


def borrower_has_active_debt(borrower_id: int) -> bool:
    with _connection() as conn:
        cur = _execute(
            conn,
            """
            SELECT 1 FROM debts
            WHERE borrower_id = ? AND status IN ('pending', 'active')
            LIMIT 1
            """,
            (borrower_id,),
        )
        return cur.fetchone() is not None


def lender_has_pending_from_borrower(lender_id: int, borrower_id: int) -> bool:
    with _connection() as conn:
        cur = _execute(
            conn,
            """
            SELECT 1 FROM debts
            WHERE lender_id = ? AND borrower_id = ? AND status = 'pending'
            LIMIT 1
            """,
            (lender_id, borrower_id),
        )
        return cur.fetchone() is not None


def get_active_debts_for_user(user_id: int) -> list[dict]:
    with _connection() as conn:
        cur = _execute(
            conn,
            """
            SELECT * FROM debts
            WHERE status = 'active' AND (borrower_id = ? OR lender_id = ?)
            ORDER BY due_at ASC
            """,
            (user_id, user_id),
        )
        return [_debt_row_to_dict(row) for row in cur.fetchall()]


def get_all_active_debts() -> list[dict]:
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT * FROM debts WHERE status = 'active' ORDER BY due_at ASC",
        )
        return [_debt_row_to_dict(row) for row in cur.fetchall()]


_MAX_ACCRUED_INTEREST = 2_147_483_647  # PostgreSQL INTEGER max


def accrue_debt_interest(debt_id: str) -> dict | None:
    debt = get_debt(debt_id)
    if not debt or debt["status"] != "active":
        return debt

    now = int(time.time())
    if now <= debt["due_at"]:
        return debt

    owed = debt_total_owed(debt)
    if owed <= 0:
        set_debt_status(debt_id, "repaid")
        return get_debt(debt_id)

    last = debt["last_interest_at"] or debt["due_at"]
    hours = min((now - last) // 3600, 168)
    if hours < 1:
        return debt

    accrued = min(debt["accrued_interest"], _MAX_ACCRUED_INTEREST)
    remaining = owed
    rate = debt["interest_rate"]
    for _ in range(hours):
        if accrued >= _MAX_ACCRUED_INTEREST:
            break
        add = max(1, int(remaining * rate)) if rate > 0 else 0
        accrued = min(_MAX_ACCRUED_INTEREST, accrued + add)
        remaining = debt["principal"] + accrued - debt["repaid"]

    new_last = last + hours * 3600
    with _connection() as conn:
        _execute(
            conn,
            "UPDATE debts SET accrued_interest = ?, last_interest_at = ? WHERE debt_id = ?",
            (accrued, new_last, debt_id),
        )
    return get_debt(debt_id)


def accrue_all_active_debts() -> list[dict]:
    updated = []
    for debt in get_all_active_debts():
        updated.append(accrue_debt_interest(debt["debt_id"]))
    return [d for d in updated if d]


def expire_pending_debts(max_age: int) -> list[str]:
    now = int(time.time())
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT debt_id FROM debts WHERE status = 'pending' AND created_at < ?",
            (now - max_age,),
        )
        ids = [row[0] for row in cur.fetchall()]
        if ids:
            _execute(
                conn,
                "UPDATE debts SET status = 'cancelled' WHERE status = 'pending' AND created_at < ?",
                (now - max_age,),
            )
    return ids


def repay_debt_amount(borrower_id: int, amount: int | None = None) -> tuple[int, list[dict]]:
    accrue_all_active_debts()
    debts = [
        d for d in get_active_debts_for_user(borrower_id)
        if d["borrower_id"] == borrower_id and debt_total_owed(d) > 0
    ]
    if not debts:
        return 0, []

    balance = get_score(borrower_id)
    budget = balance if amount is None else min(amount, balance)
    if budget <= 0:
        return 0, debts

    total_paid = 0
    settled = []
    for debt in debts:
        if budget <= 0:
            break
        owed = debt_total_owed(debt)
        if owed <= 0:
            continue
        pay = min(budget, owed)
        transferred = transfer_score(borrower_id, debt["lender_id"], pay)
        if transferred <= 0:
            break
        budget -= transferred
        total_paid += transferred
        new_repaid = debt["repaid"] + transferred
        new_status = "repaid" if new_repaid >= debt["principal"] + debt["accrued_interest"] else "active"
        with _connection() as conn:
            _execute(
                conn,
                "UPDATE debts SET repaid = ?, status = ? WHERE debt_id = ?",
                (new_repaid, new_status, debt["debt_id"]),
            )
        settled.append(get_debt(debt["debt_id"]))

    return total_paid, settled


def is_command_banned(chat_id: int, command: str) -> bool:
    cmd = command.lstrip("/").lower()
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT 1 FROM command_bans WHERE chat_id = ? AND command = ?",
            (chat_id, cmd),
        )
        return cur.fetchone() is not None


def ban_command(chat_id: int, command: str, banned_by: str = "") -> None:
    cmd = command.lstrip("/").lower()
    with _connection() as conn:
        if _use_pg:
            _execute(
                conn,
                """
                INSERT INTO command_bans (chat_id, command, banned_at, banned_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (chat_id, command) DO UPDATE
                SET banned_at = EXCLUDED.banned_at, banned_by = EXCLUDED.banned_by
                """,
                (chat_id, cmd, int(time.time()), banned_by),
            )
        else:
            _execute(
                conn,
                """
                INSERT OR REPLACE INTO command_bans (chat_id, command, banned_at, banned_by)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, cmd, int(time.time()), banned_by),
            )


def unban_command(chat_id: int, command: str) -> bool:
    cmd = command.lstrip("/").lower()
    with _connection() as conn:
        cur = _execute(
            conn,
            "DELETE FROM command_bans WHERE chat_id = ? AND command = ?",
            (chat_id, cmd),
        )
        return cur.rowcount > 0


def list_banned_commands(chat_id: int) -> list[tuple[str, str]]:
    with _connection() as conn:
        cur = _execute(
            conn,
            "SELECT command, banned_by FROM command_bans WHERE chat_id = ? ORDER BY command",
            (chat_id,),
        )
        return cur.fetchall()
