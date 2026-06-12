"""Тактическое разрешение джутсу в Naruto Duel."""

from __future__ import annotations

import random
from typing import Any

from naruto_jutsu import TYPE_EMOJI

def _effective_power(
    jutsu: dict[str, Any],
    slot_rating: int,
    buff: int,
    field_bonus: int = 0,
) -> int:
    p = jutsu["power"] + buff + field_bonus
    p += slot_rating // 8
    p += random.randint(-4, 4)
    return max(1, p)


def _type_modifier(atk_type: str, def_type: str) -> tuple[int, str | None]:
    if atk_type == "taijutsu" and def_type == "genjutsu":
        return 6, "👊 Тайдзюцу прорывает иллюзию!"
    if atk_type == "genjutsu" and def_type in ("taijutsu", "ninjutsu"):
        return -12, "👁 Гендзюцу дезориентирует противника!"
    if atk_type == "ninjutsu" and def_type == "buff":
        return 8, "🔥 Ниндзюцу срывает концентрацию!"
    if atk_type == "counter" and def_type == "ninjutsu":
        return 0, "🪞 Контр-джутсу отражает ниндзюцу!"
    return 0, None


def resolve_jutsu_clash(
    j1: dict[str, Any],
    j2: dict[str, Any],
    slot1: dict[str, Any],
    slot2: dict[str, Any],
    hp1: int,
    hp2: int,
    name1: str,
    name2: str,
    buff1: int,
    buff2: int,
    guard1: bool,
    guard2: bool,
    role_label: str,
    round_num: int,
    heal_mult1: float = 1.0,
    heal_mult2: float = 1.0,
    dmg_reduce1: int = 0,
    dmg_reduce2: int = 0,
) -> tuple[int, int, int, int, bool, bool, str]:
    """
    Returns: hp1, hp2, new_buff1, new_buff2, new_guard1, new_guard2, log_text
    Side effects: buffs consumed on use
    """
    c1, c2 = slot1["character"], slot2["character"]
    r1, r2 = slot1["rating"], slot2["rating"]
    lines = [
        f"⚔️ <b>Раунд {round_num}/6</b> — {role_label}",
        f"<b>{c1['name']}</b> 🆚 <b>{c2['name']}</b>",
    ]

    nb1, nb2 = 0, 0
    ng1, ng2 = False, False
    used_buff1, used_buff2 = buff1, buff2

    # --- Heals ---
    heal1 = heal2 = 0
    if j1["type"] == "heal":
        heal1 = int(min(j1["power"], 100 - hp1) * heal_mult1)
        hp1 += heal1
        used_buff1 = 0
        lines.append(f"💚 <b>{c1['name']}</b> — {j1['name']}: +{heal1} HP → {hp1}")
    if j2["type"] == "heal":
        heal2 = int(min(j2["power"], 100 - hp2) * heal_mult2)
        hp2 += heal2
        used_buff2 = 0
        lines.append(f"💚 <b>{c2['name']}</b> — {j2['name']}: +{heal2} HP → {hp2}")

    # --- Buffs ---
    if j1["type"] == "buff":
        nb1 = j1["power"]
        if j1["name"] in ("Железная кожа", "Песчаная броня"):
            ng1 = True
        lines.append(f"⬆️ <b>{c1['name']}</b> — {j1['name']}!")
    if j2["type"] == "buff":
        nb2 = j2["power"]
        if j2["name"] in ("Железная кожа", "Песчаная броня"):
            ng2 = True
        lines.append(f"⬆️ <b>{c2['name']}</b> — {j2['name']}!")

    # --- Counters vs ninjutsu ---
    counter_dmg1 = counter_dmg2 = 0
    if j1["type"] == "counter" and j2["type"] == "ninjutsu":
        counter_dmg2 = int(j2["power"] * 0.55) + j1["power"] // 3
        hp2 = max(0, hp2 - counter_dmg2)
        lines.append(
            f"🪞 <b>{c1['name']}</b> контрит {j2['name']}! "
            f"−{counter_dmg2} HP у {name2}"
        )
    if j2["type"] == "counter" and j1["type"] == "ninjutsu":
        counter_dmg1 = int(j1["power"] * 0.55) + j2["power"] // 3
        hp1 = max(0, hp1 - counter_dmg1)
        lines.append(
            f"🪞 <b>{c2['name']}</b> контрит {j1['name']}! "
            f"−{counter_dmg1} HP у {name1}"
        )

    # Skip direct clash if only heal/buff/counter resolved
    clash_types = {"ninjutsu", "taijutsu", "genjutsu"}
    if j1["type"] not in clash_types and j2["type"] not in clash_types:
        if counter_dmg1 or counter_dmg2 or heal1 or heal2:
            return hp1, hp2, nb1, nb2, ng1, ng2, "\n".join(lines)
        lines.append("🌀 Оба играют утилити — раунд без прямого урона.")
        return hp1, hp2, nb1, nb2, ng1, ng2, "\n".join(lines)

    if j1["type"] in clash_types or j2["type"] in clash_types:
        p1 = _effective_power(j1, r1, used_buff1 if j1["type"] in clash_types else 0)
        p2 = _effective_power(j2, r2, used_buff2 if j2["type"] in clash_types else 0)

        mod1, note1 = _type_modifier(j1["type"], j2["type"])
        mod2, note2 = _type_modifier(j2["type"], j1["type"])
        p1 += mod1
        p2 += mod2
        if note1:
            lines.append(note1)
        if note2:
            lines.append(note2)

        e1 = TYPE_EMOJI.get(j1["type"], "✨")
        e2 = TYPE_EMOJI.get(j2["type"], "✨")
        lines.append(
            f"🎴 <b>{name1}</b> {e1} <i>{j1['name']}</i> ({p1}) vs "
            f"<b>{name2}</b> {e2} <i>{j2['name']}</i> ({p2})"
        )

        if p1 > p2:
            raw = max(6, (p1 - p2) // 2 + 4)
            if guard2:
                raw = max(3, int(raw * 0.8))
                ng2 = False
            if dmg_reduce2:
                raw = max(1, raw - int(raw * dmg_reduce2 / 100))
            hp2 = max(0, hp2 - raw)
            lines.append(
                f"💥 <b>{c1['name']}</b> берёт линию! −{raw} HP у <b>{name2}</b>"
            )
        elif p2 > p1:
            raw = max(6, (p2 - p1) // 2 + 4)
            if guard1:
                raw = max(3, int(raw * 0.8))
                ng1 = False
            if dmg_reduce1:
                raw = max(1, raw - int(raw * dmg_reduce1 / 100))
            hp1 = max(0, hp1 - raw)
            lines.append(
                f"💥 <b>{c2['name']}</b> берёт линию! −{raw} HP у <b>{name1}</b>"
            )
        else:
            chip = 5
            hp1 = max(0, hp1 - chip)
            hp2 = max(0, hp2 - chip)
            lines.append(f"⚡ Ничья на линии — оба теряют {chip} HP!")

    lines.append(f"❤️ {name1}: {hp1} | {name2}: {hp2}")
    return hp1, hp2, nb1, nb2, ng1, ng2, "\n".join(lines)
