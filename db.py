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
