"""Джутсу для Naruto Duel — 3 техники на персонажа."""

from __future__ import annotations

import random
from typing import Any

# type: ninjutsu | taijutsu | genjutsu | heal | buff | counter
TYPE_EMOJI = {
    "ninjutsu": "🔥",
    "taijutsu": "👊",
    "genjutsu": "👁",
    "heal": "💚",
    "buff": "⬆️",
    "counter": "🪞",
}

ARCHETYPE_KITS: dict[str, list[dict[str, Any]]] = {
    "striker": [
        {"name": "Огненный шар", "type": "ninjutsu", "power": 22, "chakra": 10, "desc": "Классический урон"},
        {"name": "Динамический вход", "type": "taijutsu", "power": 20, "chakra": 8, "desc": "Рывок в ближний бой"},
        {"name": "Теневой клон", "type": "buff", "power": 14, "chakra": 9, "desc": "След. джутсу +14 силы"},
    ],
    "tank": [
        {"name": "Земляная стена", "type": "counter", "power": 18, "chakra": 11, "desc": "Отражает ниндзюцу"},
        {"name": "Тяжёлый удар", "type": "taijutsu", "power": 16, "chakra": 7, "desc": "Стабильный урон"},
        {"name": "Железная кожа", "type": "buff", "power": 12, "chakra": 8, "desc": "След. раунд −20% урона"},
    ],
    "support": [
        {"name": "Водяной дракон", "type": "ninjutsu", "power": 20, "chakra": 11, "desc": "Давление с дистанции"},
        {"name": "Гендзюцу: Паутина", "type": "genjutsu", "power": 17, "chakra": 10, "desc": "−35% силы врага"},
        {"name": "Сенсорный барьер", "type": "buff", "power": 13, "chakra": 9, "desc": "След. джутсу +13"},
    ],
    "healer": [
        {"name": "Медицинское ниндзюцу", "type": "heal", "power": 18, "chakra": 10, "desc": "Лечит командира"},
        {"name": "Антисептик-удар", "type": "taijutsu", "power": 14, "chakra": 7, "desc": "Слабый урон"},
        {"name": "Чакра-передача", "type": "buff", "power": 16, "chakra": 8, "desc": "+16 к след. джутсу"},
    ],
}

CHARACTER_JUTSU: dict[str, list[dict[str, Any]]] = {
    "Малик Жалмурзин": [
        {"name": "Доминант Кайнара", "type": "ninjutsu", "power": 38, "chakra": 14, "desc": "Абсолютный урон"},
        {"name": "Воля Хокаге", "type": "buff", "power": 22, "chakra": 10, "desc": "След. джутсу +22"},
        {"name": "Контр-стратегия", "type": "counter", "power": 24, "chakra": 12, "desc": "Карает ниндзюцу"},
    ],
    "Наруто Узумаки": [
        {"name": "Расенган", "type": "ninjutsu", "power": 30, "chakra": 13, "desc": "Сфера разрушения"},
        {"name": "Теневое клонирование", "type": "buff", "power": 18, "chakra": 9, "desc": "След. джутсу +18"},
        {"name": "Расенсюрикен", "type": "ninjutsu", "power": 34, "chakra": 16, "desc": "Мощнейший удар"},
    ],
    "Саске Учиха": [
        {"name": "Чидори", "type": "ninjutsu", "power": 28, "chakra": 12, "desc": "Молния в ладони"},
        {"name": "Шаринган", "type": "genjutsu", "power": 22, "chakra": 11, "desc": "Читает и ломает врага"},
        {"name": "Пламя Учиха", "type": "ninjutsu", "power": 26, "chakra": 11, "desc": "Огненный шторм"},
    ],
    "Сакура Харуно": [
        {"name": "Мега-удар", "type": "taijutsu", "power": 26, "chakra": 10, "desc": "Кулак сносит горы"},
        {"name": "Сотня исцелений", "type": "heal", "power": 22, "chakra": 11, "desc": "Сильное лечение"},
        {"name": "Чакра-скальпель", "type": "ninjutsu", "power": 20, "chakra": 9, "desc": "Точный разрез"},
    ],
    "Какаши Хатаке": [
        {"name": "Райкири", "type": "ninjutsu", "power": 30, "chakra": 14, "desc": "Молния резни"},
        {"name": "Копирование", "type": "counter", "power": 22, "chakra": 12, "desc": "Ответ на ниндзюцу"},
        {"name": "Камуи", "type": "genjutsu", "power": 24, "chakra": 13, "desc": "Пространственный сбой"},
    ],
    "Rock Lee": [
        {"name": "Первые врата", "type": "buff", "power": 20, "chakra": 8, "desc": "След. тайдзюцу +20"},
        {"name": "Листовой ураган", "type": "taijutsu", "power": 28, "chakra": 11, "desc": "Ноги быстрее мыслей"},
        {"name": "Вечерний слон", "type": "taijutsu", "power": 32, "chakra": 14, "desc": "Ультимативный удар"},
    ],
    "Gaara": [
        {"name": "Песчаное сжатие", "type": "ninjutsu", "power": 28, "chakra": 12, "desc": "Песок давит"},
        {"name": "Песчаная броня", "type": "counter", "power": 20, "chakra": 10, "desc": "Отражает атаки"},
        {"name": "Песчаная могила", "type": "ninjutsu", "power": 32, "chakra": 15, "desc": "Полное захоронение"},
    ],
    "Itachi Uchiha": [
        {"name": "Аматерасу", "type": "ninjutsu", "power": 34, "chakra": 16, "desc": "Чёрное пламя"},
        {"name": "Цукуёми", "type": "genjutsu", "power": 30, "chakra": 14, "desc": "Ломает разум"},
        {"name": "Сусаноо", "type": "buff", "power": 20, "chakra": 12, "desc": "След. джутсу +20"},
    ],
    "Madara Uchiha": [
        {"name": "Метеорит", "type": "ninjutsu", "power": 40, "chakra": 18, "desc": "Катастрофа"},
        {"name": "Сусаноо Мадары", "type": "buff", "power": 24, "chakra": 13, "desc": "След. джутсу +24"},
        {"name": "Изаанаги", "type": "counter", "power": 26, "chakra": 14, "desc": "Переписывает исход"},
    ],
    "Tsunade": [
        {"name": "Нокдаун-удар", "type": "taijutsu", "power": 30, "chakra": 12, "desc": "Кулак Каге"},
        {"name": "Мед-ниндзюцу Pro", "type": "heal", "power": 26, "chakra": 12, "desc": "Лечит командира"},
        {"name": "Каге-буфф", "type": "buff", "power": 18, "chakra": 9, "desc": "След. джутсу +18"},
    ],
    "Jiraiya": [
        {"name": "Расэнган Сапфира", "type": "ninjutsu", "power": 30, "chakra": 13, "desc": "Усиленный Расенган"},
        {"name": "Жабий песнь", "type": "genjutsu", "power": 22, "chakra": 11, "desc": "Звуковая ловушка"},
        {"name": "Призыв Жаб", "type": "buff", "power": 16, "chakra": 10, "desc": "След. джутсу +16"},
    ],
    "Pain/Nagato": [
        {"name": "Синра Тенсей", "type": "ninjutsu", "power": 34, "chakra": 15, "desc": "Отталкивает всё"},
        {"name": "Поглощение души", "type": "heal", "power": 20, "chakra": 11, "desc": "Высасывает и лечит"},
        {"name": "Баншо Тенин", "type": "genjutsu", "power": 26, "chakra": 12, "desc": "Контроль поля"},
    ],
    "Might Guy": [
        {"name": "Утренний птичий удар", "type": "taijutsu", "power": 26, "chakra": 10, "desc": "Скорость птицы"},
        {"name": "3-й врата", "type": "buff", "power": 22, "chakra": 10, "desc": "След. тайдзюцу +22"},
        {"name": "8-й врата", "type": "taijutsu", "power": 38, "chakra": 16, "desc": "Пламя молодости"},
    ],
    "Shikamaru Nara": [
        {"name": "Теневой захват", "type": "genjutsu", "power": 24, "chakra": 11, "desc": "Фиксирует врага"},
        {"name": "Стратегический план", "type": "buff", "power": 20, "chakra": 9, "desc": "След. джутсу +20"},
        {"name": "Теневые ножницы", "type": "ninjutsu", "power": 22, "chakra": 10, "desc": "Добивание"},
    ],
    "Hashirama Senju": [
        {"name": "Древо-столетие", "type": "ninjutsu", "power": 36, "chakra": 16, "desc": "Лес на арене"},
        {"name": "Регенерация", "type": "heal", "power": 24, "chakra": 12, "desc": "Клеточное лечение"},
        {"name": "Мудрость Хокаге", "type": "buff", "power": 20, "chakra": 10, "desc": "След. джутсу +20"},
    ],
    "Minato Namikaze": [
        {"name": "Расенган Минато", "type": "ninjutsu", "power": 30, "chakra": 12, "desc": "Жёлтая молния"},
        {"name": "Летающий бог грома", "type": "taijutsu", "power": 28, "chakra": 11, "desc": "Телепорт-удар"},
        {"name": "Печать смерти", "type": "counter", "power": 24, "chakra": 13, "desc": "Ответный удар"},
    ],
    "Killer Bee": [
        {"name": "Лариат", "type": "taijutsu", "power": 28, "chakra": 11, "desc": "Удар хвоста"},
        {"name": "8-мечевой стиль", "type": "ninjutsu", "power": 30, "chakra": 13, "desc": "Хвостатый разгром"},
        {"name": "Рэп-бафф", "type": "buff", "power": 16, "chakra": 8, "desc": "След. джутсу +16"},
    ],
    "Neji Hyuga": [
        {"name": "64 Длани", "type": "taijutsu", "power": 28, "chakra": 12, "desc": "Закрывает чакру"},
        {"name": "Кaiten", "type": "counter", "power": 22, "chakra": 11, "desc": "Вращающаяся защита"},
        {"name": "Бьякуган", "type": "genjutsu", "power": 20, "chakra": 10, "desc": "Видит слабости"},
    ],
    "Deidara": [
        {"name": "C1", "type": "ninjutsu", "power": 24, "chakra": 10, "desc": "Взрывная глина"},
        {"name": "C2", "type": "ninjutsu", "power": 30, "chakra": 14, "desc": "Дракон-бомба"},
        {"name": "Искусство — бум!", "type": "buff", "power": 18, "chakra": 9, "desc": "След. ниндзюцу +18"},
    ],
    "Naruto (KCM)": [
        {"name": "Расенган KCM", "type": "ninjutsu", "power": 36, "chakra": 14, "desc": "Золотая чакра"},
        {"name": "Режим Кьюби", "type": "buff", "power": 24, "chakra": 11, "desc": "След. джутсу +24"},
        {"name": "Тайдзюцу Каге", "type": "taijutsu", "power": 30, "chakra": 12, "desc": "Скорость света"},
    ],
    "Sasuke (Rinnegan)": [
        {"name": "Аменотеджикара", "type": "genjutsu", "power": 30, "chakra": 14, "desc": "Меняет позиции"},
        {"name": "Индра-стрела", "type": "ninjutsu", "power": 36, "chakra": 16, "desc": "Чидори 2.0"},
        {"name": "Сусаноо ПС", "type": "buff", "power": 22, "chakra": 12, "desc": "След. джутсу +22"},
    ],
}


def _archetype_for(char: dict) -> str:
    ratings = char["ratings"]
    best = max(ratings, key=ratings.get)
    if best == "healer":
        return "healer"
    if best == "tank":
        return "tank"
    if ratings.get("support", 0) >= ratings.get("captain", 0):
        return "support"
    return "striker"


def _scale_jutsu(jutsu: dict[str, Any], slot_rating: int) -> dict[str, Any]:
    scale = 0.75 + slot_rating / 200
    return {
        **jutsu,
        "power": max(8, int(jutsu["power"] * scale)),
        "chakra": max(5, int(jutsu["chakra"] * (0.9 + slot_rating / 300))),
    }


def get_jutsu_kit(char: dict, slot_rating: int) -> list[dict[str, Any]]:
    base = CHARACTER_JUTSU.get(char["name"])
    if not base:
        arch = _archetype_for(char)
        base = ARCHETYPE_KITS[arch]
    return [_scale_jutsu(j, slot_rating) for j in base]


def jutsu_label(j: dict[str, Any]) -> str:
    emoji = TYPE_EMOJI.get(j["type"], "✨")
    return f"{emoji} {j['name']} ({j['chakra']}💠)"


def jutsu_button_text(j: dict[str, Any]) -> str:
    emoji = TYPE_EMOJI.get(j["type"], "✨")
    return f"{emoji} {j['name']} ·{j['chakra']}💠"
