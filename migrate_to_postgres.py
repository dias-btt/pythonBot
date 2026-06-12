#!/usr/bin/env python3
"""Один раз перенести данные из локального alkashi.db в PostgreSQL на Railway."""

import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = os.getenv("SQLITE_PATH", "alkashi.db")


def _normalize_dsn(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _pick_database_url() -> str | None:
    # С Mac нужен публичный URL — внутренний *.railway.internal работает только на Railway.
    public = os.getenv("DATABASE_PUBLIC_URL", "").strip()
    private = os.getenv("DATABASE_URL", "").strip()

    if public:
        return public
    if private and "railway.internal" not in private:
        return private
    if private and "railway.internal" in private:
        print("❌ В .env указан внутренний DATABASE_URL (postgres.railway.internal).")
        print("   С Mac он не открывается — нужен публичный URL.\n")
        print("   Railway → сервис PostgreSQL → вкладка Connect (или Variables):")
        print("   1. Включи Public Network / TCP Proxy, если выключено")
        print("   2. Скопируй строку «Public URL» / DATABASE_PUBLIC_URL")
        print("   3. В .env добавь:")
        print("      DATABASE_PUBLIC_URL=postgresql://postgres:...@...railway.app:.../railway\n")
        return None
    return None


database_url = _pick_database_url()
if not database_url:
    if not os.getenv("DATABASE_URL") and not os.getenv("DATABASE_PUBLIC_URL"):
        print("❌ Нужен DATABASE_PUBLIC_URL или DATABASE_URL в .env")
    sys.exit(1)

if not os.path.isfile(SQLITE_PATH):
    print(f"❌ Файл {SQLITE_PATH} не найден.")
    sys.exit(1)

os.environ["DATABASE_URL"] = database_url

import psycopg2

import db  # noqa: E402 — создаёт таблицы в Postgres

dsn = _normalize_dsn(database_url)
print(f"🔌 Подключаюсь к Postgres ({dsn.split('@')[-1]})...")

try:
    pg = psycopg2.connect(dsn)
except psycopg2.OperationalError as e:
    print(f"❌ Не удалось подключиться: {e}\n")
    if "railway.internal" in str(e):
        print("   Используй DATABASE_PUBLIC_URL — см. инструкцию выше.")
    sys.exit(1)

src = sqlite3.connect(SQLITE_PATH)
src_cur = src.cursor()
pg_cur = pg.cursor()

TABLES = [
    ("alkashi", ["user_id", "username", "score", "last_drink"]),
    ("stickers", ["file_id", "added_by", "added_at"]),
    (
        "naruto_duel_stats",
        ["user_id", "username", "wins", "draws", "losses", "points", "damage_dealt", "damage_taken"],
    ),
    ("naruto_duel_h2h", ["user_a", "user_b", "wins_a", "wins_b", "draws"]),
]

for table, columns in TABLES:
    src_cur.execute(f"SELECT {', '.join(columns)} FROM {table}")
    rows = src_cur.fetchall()
    if not rows:
        print(f"⏭  {table}: пусто")
        continue

    cols = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    pg_cur.execute(f"DELETE FROM {table}")
    pg_cur.executemany(
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
        rows,
    )
    print(f"✅ {table}: {len(rows)} строк")

pg.commit()
src.close()
pg.close()
print("\n🎉 Готово! На Railway у бота оставь DATABASE_URL (внутренний) — он для деплоя.")
