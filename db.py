import sqlite3
import time

conn = sqlite3.connect("alkashi.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS alkashi (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    score INTEGER DEFAULT 0,
    last_drink INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS stickers (
    file_id TEXT PRIMARY KEY,
    added_by INTEGER,
    added_at INTEGER
)
""")

cursor.execute("""
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
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS naruto_duel_h2h (
    user_a INTEGER NOT NULL,
    user_b INTEGER NOT NULL,
    wins_a INTEGER NOT NULL DEFAULT 0,
    wins_b INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_a, user_b)
)
""")

conn.commit()

def add_sticker(file_id: str, user_id: int):
    cursor.execute(
        """
        INSERT OR IGNORE INTO stickers(file_id, added_by, added_at)
        VALUES (?, ?, ?)
        """,
        (file_id, user_id, int(time.time())),
    )
    conn.commit()


def sticker_exists(file_id: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM stickers WHERE file_id = ?",
        (file_id,),
    )
    return cursor.fetchone() is not None


def get_random_sticker():
    cursor.execute(
        "SELECT file_id FROM stickers ORDER BY RANDOM() LIMIT 1"
    )
    row = cursor.fetchone()
    return row[0] if row else None

def ensure_user(user_id: int, username: str):
    cursor.execute(
        """
        INSERT OR IGNORE INTO alkashi(user_id, username, score)
        VALUES (?, ?, 0)
        """,
        (user_id, username),
    )
    conn.commit()


def add_score(user_id: int, points: int):
    cursor.execute(
        """
        UPDATE alkashi
        SET score = score + ?
        WHERE user_id = ?
        """,
        (points, user_id),
    )
    conn.commit()


def top_users(limit=10):
    cursor.execute(
        """
        SELECT username, score
        FROM alkashi
        ORDER BY score DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()

def get_last_drink(user_id: int):
    cursor.execute(
        "SELECT last_drink FROM alkashi WHERE user_id = ?",
        (user_id,)
    )

    row = cursor.fetchone()
    return row[0] if row else 0


def update_last_drink(user_id: int):
    cursor.execute(
        """
        UPDATE alkashi
        SET last_drink = ?
        WHERE user_id = ?
        """,
        (int(time.time()), user_id),
    )
    conn.commit()


def get_score(user_id: int):
    cursor.execute(
        """
        SELECT score
        FROM alkashi
        WHERE user_id = ?
        """,
        (user_id,),
    )

    row = cursor.fetchone()
    return row[0] if row else 0


def get_players_with_scores():
    cursor.execute(
        """
        SELECT user_id, username, score
        FROM alkashi
        WHERE score != 0
        ORDER BY score DESC
        """
    )
    return cursor.fetchall()


def reset_all_scores():
    cursor.execute("UPDATE alkashi SET score = 0")
    conn.commit()


def _h2h_key(user1_id: int, user2_id: int) -> tuple[int, int]:
    if user1_id < user2_id:
        return user1_id, user2_id
    return user2_id, user1_id


def ensure_naruto_duel_user(user_id: int, username: str) -> None:
    cursor.execute(
        """
        INSERT OR IGNORE INTO naruto_duel_stats(user_id, username)
        VALUES (?, ?)
        """,
        (user_id, username),
    )
    cursor.execute(
        """
        UPDATE naruto_duel_stats
        SET username = ?
        WHERE user_id = ?
        """,
        (username, user_id),
    )
    conn.commit()


def record_naruto_duel_result(
    user1_id: int,
    user1_name: str,
    user2_id: int,
    user2_name: str,
    winner_id: int | None,
    damage: dict[int, tuple[int, int]],
) -> tuple[int, int, int]:
    """Returns head-to-head (user1 wins, user2 wins, draws) after recording."""
    ensure_naruto_duel_user(user1_id, user1_name)
    ensure_naruto_duel_user(user2_id, user2_name)

    for uid, (dealt, taken) in damage.items():
        cursor.execute(
            """
            UPDATE naruto_duel_stats
            SET damage_dealt = damage_dealt + ?,
                damage_taken = damage_taken + ?
            WHERE user_id = ?
            """,
            (dealt, taken, uid),
        )

    if winner_id is None:
        cursor.execute(
            """
            UPDATE naruto_duel_stats
            SET draws = draws + 1, points = points + 1
            WHERE user_id IN (?, ?)
            """,
            (user1_id, user2_id),
        )
    elif winner_id == user1_id:
        cursor.execute(
            """
            UPDATE naruto_duel_stats
            SET wins = wins + 1, points = points + 3
            WHERE user_id = ?
            """,
            (user1_id,),
        )
        cursor.execute(
            """
            UPDATE naruto_duel_stats
            SET losses = losses + 1
            WHERE user_id = ?
            """,
            (user2_id,),
        )
    else:
        cursor.execute(
            """
            UPDATE naruto_duel_stats
            SET wins = wins + 1, points = points + 3
            WHERE user_id = ?
            """,
            (user2_id,),
        )
        cursor.execute(
            """
            UPDATE naruto_duel_stats
            SET losses = losses + 1
            WHERE user_id = ?
            """,
            (user1_id,),
        )

    a_id, b_id = _h2h_key(user1_id, user2_id)
    cursor.execute(
        """
        INSERT OR IGNORE INTO naruto_duel_h2h(user_a, user_b)
        VALUES (?, ?)
        """,
        (a_id, b_id),
    )

    if winner_id is None:
        cursor.execute(
            """
            UPDATE naruto_duel_h2h
            SET draws = draws + 1
            WHERE user_a = ? AND user_b = ?
            """,
            (a_id, b_id),
        )
    elif winner_id == a_id:
        cursor.execute(
            """
            UPDATE naruto_duel_h2h
            SET wins_a = wins_a + 1
            WHERE user_a = ? AND user_b = ?
            """,
            (a_id, b_id),
        )
    else:
        cursor.execute(
            """
            UPDATE naruto_duel_h2h
            SET wins_b = wins_b + 1
            WHERE user_a = ? AND user_b = ?
            """,
            (a_id, b_id),
        )

    conn.commit()
    return get_naruto_duel_h2h(user1_id, user2_id)


def get_naruto_duel_h2h(user1_id: int, user2_id: int) -> tuple[int, int, int]:
    a_id, b_id = _h2h_key(user1_id, user2_id)
    cursor.execute(
        """
        SELECT wins_a, wins_b, draws
        FROM naruto_duel_h2h
        WHERE user_a = ? AND user_b = ?
        """,
        (a_id, b_id),
    )
    row = cursor.fetchone()
    if not row:
        return 0, 0, 0
    wins_a, wins_b, draws = row
    if user1_id == a_id:
        return wins_a, wins_b, draws
    return wins_b, wins_a, draws


def get_naruto_duel_ratings(limit: int = 20):
    cursor.execute(
        """
        SELECT username, wins, draws, losses, points, damage_dealt, damage_taken
        FROM naruto_duel_stats
        WHERE wins + draws + losses > 0
        ORDER BY points DESC, wins DESC, damage_dealt DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()