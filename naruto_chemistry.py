"""Синергия деревень: бонусы за 3–6 ниндзя из одной деревни."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VILLAGE_CANON: dict[str, str] = {
    "konoha": "Коноха",
    "коноха": "Коноха",
    "suna": "Суна",
    "суна": "Суна",
    "kumo": "Кумо",
    "kumi": "Кумо",
    "kiri": "Кири",
    "кири": "Кири",
    "iwa": "Ива",
    "ива": "Ива",
    "amegakure": "Амегакурэ",
    "амегакурэ": "Амегакурэ",
    "akatsuki": "Акацуки",
    "акацуки": "Акацуки",
    "otogakure": "Отогакурэ",
    "отогакурэ": "Отогакурэ",
    "кайнар": "Кайнар",
    "kusa": "Куса",
    "куса": "Куса",
    "taki": "Таки",
    "таки": "Таки",
    "otsutsuki": "Оцуцуки",
    "оцуцуки": "Оцуцуки",
    "kara": "Кара",
    "кара": "Кара",
    "moon": "Луна",
    "луна": "Луна",
}

VILLAGE_FLAVORS: dict[str, str] = {
    "Коноха": "Воля огня и раменная дружба!",
    "Суна": "Песок одной пустыни не предаёт.",
    "Кумо": "Гром и молнии бьют в унисон!",
    "Кири": "Туман скрывает, но команда — нет.",
    "Ива": "Каменная стена крепче вместе.",
    "Амегакурэ": "Дождь смывает слабость отряда.",
    "Акацуки": "Клоуки в плащах — но синхрон идеален.",
    "Отогакурэ": "Змеиная химия: яд усиливается.",
    "Кайнар": "Легенды Кайнара дышат как один.",
    "Куса": "Трава одной долины — одна судьба.",
    "Таки": "Водопад одной деревни не останавливается.",
    "Оцуцуки": "Чакра предков льётся в одно русло.",
    "Кара": "Кьюби-метки резонируют.",
    "Луна": "Лунная гравитация сжимает отряд.",
}

TIER_NAMES = {
    3: "🤝 Деревенская связь",
    4: "⚔️ Отряд одной деревни",
    5: "🏆 Элита деревни",
    6: "👑 Чистая деревня",
}

# count -> (jutsu_power, chakra_start, heal_bonus_pct, damage_reduce_pct, rating_display)
TIER_STATS: dict[int, tuple[int, int, int, int, int]] = {
    3: (2, 3, 0, 0, 2),
    4: (4, 5, 5, 3, 4),
    5: (6, 8, 10, 5, 6),
    6: (10, 12, 15, 8, 10),
}


@dataclass(frozen=True)
class ChemistryBonus:
    village: str
    count: int
    tier_name: str
    jutsu_power: int
    chakra_bonus: int
    heal_bonus_pct: int
    damage_reduce_pct: int
    rating_bonus: int
    flavor: str

    @property
    def perks_short(self) -> str:
        parts = [f"+{self.jutsu_power} к силе джутсу"]
        if self.chakra_bonus:
            parts.append(f"+{self.chakra_bonus}💠 старт")
        if self.heal_bonus_pct:
            parts.append(f"хил +{self.heal_bonus_pct}%")
        if self.damage_reduce_pct:
            parts.append(f"−{self.damage_reduce_pct}% урона")
        return ", ".join(parts)


def normalize_village(raw: str) -> str | None:
    if not raw or raw.strip().lower() in ("none", "null", "—"):
        return None
    primary = raw.split("/")[0].strip()
    key = primary.lower()
    return VILLAGE_CANON.get(key, primary)


def _village_counts(team: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for slot in team:
        village = normalize_village(slot["character"]["village"])
        if village:
            counts[village] = counts.get(village, 0) + 1
    return counts


def get_team_chemistry(team: list[dict[str, Any]]) -> ChemistryBonus | None:
    counts = _village_counts(team)
    if not counts:
        return None
    village, count = max(counts.items(), key=lambda x: x[1])
    if count < 3:
        return None
    tier = min(count, 6)
    jutsu, chakra, heal, dmg_reduce, rating = TIER_STATS[tier]
    flavor = VILLAGE_FLAVORS.get(village, "Команда дышит в унисон!")
    return ChemistryBonus(
        village=village,
        count=count,
        tier_name=TIER_NAMES[tier],
        jutsu_power=jutsu,
        chakra_bonus=chakra,
        heal_bonus_pct=heal,
        damage_reduce_pct=dmg_reduce,
        rating_bonus=rating,
        flavor=flavor,
    )


def format_chemistry_block(chem: ChemistryBonus | None) -> str | None:
    if not chem:
        return None
    return (
        f"🏘️ <b>{chem.tier_name}</b> — {chem.village} ×{chem.count}\n"
        f"<i>{chem.flavor}</i>\n"
        f"⚡ Перки: {chem.perks_short}"
    )


def chemistry_heal_multiplier(chem: ChemistryBonus | None) -> float:
    if not chem or not chem.heal_bonus_pct:
        return 1.0
    return 1.0 + chem.heal_bonus_pct / 100


def apply_damage_reduction(damage: int, chem: ChemistryBonus | None) -> int:
    if not chem or not chem.damage_reduce_pct or damage <= 0:
        return damage
    reduced = int(damage * chem.damage_reduce_pct / 100)
    return max(0, damage - reduced)
