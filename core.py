"""车牌筛选工具的全部逻辑（不依赖界面，可被 --selftest 单独调用）。

包含四块：

* 规则与打分      default_rules / normalize_rules / score_plate
* 号段展开        expand_segment / expand_segments / build_plates
* 图片识别        load_image / detect_plates / annotate_image / zoom_region
* 文本报告        build_report / write_text / write_csv

识别依赖 tesseract 可执行文件：优先用界面里指定的路径（或环境变量
PLATE_TESSERACT），其次是随程序分发的副本，最后才是系统 PATH。
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import cv2
import numpy as np

try:
    import pytesseract
except Exception:  # pragma: no cover - 依赖缺失时给出友好提示
    pytesseract = None


# --------------------------------------------------------------------------- #
# 规则
# --------------------------------------------------------------------------- #

# 幸运字符（去重后）。原脚本里的列表有重复项，会让同一规则被重复加分。
_LUCKY_CHARS = [
    "6", "8",
    "149", "786", "349", "826", "768", "913", "139",
    "419", "726", "314", "678", "687", "494",
    "393", "627", "278", "134", "286", "413", "628",
    "827", "268", "319", "867", "214", "693", "482", "376",
    "128", "967", "841", "739", "A43", "1D6", "2H6",
    "G86", "34A", "AS9", "F87", "G67", "ED9", "4A3",
    "311", "688", "944",   # 持续来米
    "813", "631", "794",   # 智慧来米
    "768", "413",          # 贵人来米（149 已在前文）
    "786", "268", "872",   # 能力来米
    "219", "213", "691",   # 努力来米
    "968", "231", "172",   # 口才来米
    "927", "749", "168",   # 照顾来米
]

_UNLUCKY_CHARS = [
    "4", "10", "50", "17", "71", "18", "16", "61", "58", "85",
    "19", "59", "99", "57", "75",
    "217", "218", "321", "324", "421", "479", "617", "648",
    "798", "718", "812", "817",
]

_BAD_TAIL = ["0", "05"]

FLAG_KEYS = ("repeat", "sequence", "pair", "lucky", "unlucky", "bad_tail")

# ---- 数字能量规则表 -------------------------------------------------------- #
# 口径取自本机 ~/Documents/perfect-numbers-app 的 core.py（常见数字能量流派）：
# 相邻两位数字 -> 八星磁场，各位数之和 -> 81 数理，数字 -> 河图五行。
# 属于民俗 / 娱乐参考，不是科学结论；不同流派的分值可以在这里直接替换。

STAR_TABLE = {
    "天医": "13 31 68 86 49 94 27 72",
    "延年": "19 91 78 87 34 43 26 62",
    "生气": "14 41 67 76 39 93 28 82",
    "伏位": "11 22 88 99 66 77 33 44",
    "绝命": "12 21 69 96 48 84 37 73",
    "五鬼": "18 81 79 97 36 63 24 42",
    "六煞": "16 61 47 74 38 83 29 92",
    "祸害": "17 71 89 98 46 64 23 32",
}
STAR_LUCK = {
    "天医": 1, "延年": 1, "生气": 1, "伏位": 1,
    "绝命": -1, "五鬼": -1, "六煞": -1, "祸害": -1,
}
STAR_ORDER = ("天医", "延年", "生气", "伏位", "绝命", "五鬼", "六煞", "祸害")
PAIR_STAR = {pair: star for star, pairs in STAR_TABLE.items()
             for pair in pairs.split()}

# 河图数：天一生水、地六成之……
DIGIT_WUXING = {"1": "水", "6": "水", "2": "火", "7": "火", "3": "木",
                "8": "木", "4": "金", "9": "金", "5": "土", "0": "土"}
WUXING_ORDER = ("金", "木", "水", "火", "土")

# 五行生克：SHENG[我] = 我生；KE[我] = 我克
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

# 81 数理吉凶（常见版本，可替换）
LUCK81 = {
    1: "吉", 2: "凶", 3: "吉", 4: "凶", 5: "吉", 6: "吉", 7: "吉", 8: "吉",
    9: "凶", 10: "凶", 11: "吉", 12: "凶", 13: "吉", 14: "凶", 15: "吉",
    16: "吉", 17: "吉", 18: "吉", 19: "凶", 20: "凶", 21: "吉", 22: "凶",
    23: "吉", 24: "吉", 25: "吉", 26: "凶", 27: "半吉", 28: "凶", 29: "吉",
    30: "半吉", 31: "吉", 32: "吉", 33: "吉", 34: "凶", 35: "吉", 36: "凶",
    37: "吉", 38: "半吉", 39: "吉", 40: "凶", 41: "吉", 42: "凶", 43: "凶",
    44: "凶", 45: "吉", 46: "凶", 47: "吉", 48: "吉", 49: "凶", 50: "凶",
    51: "半吉", 52: "吉", 53: "凶", 54: "凶", 55: "半吉", 56: "凶", 57: "吉",
    58: "半吉", 59: "凶", 60: "凶", 61: "吉", 62: "凶", 63: "吉", 64: "凶",
    65: "吉", 66: "凶", 67: "吉", 68: "吉", 69: "凶", 70: "凶", 71: "半吉",
    72: "凶", 73: "吉", 74: "凶", 75: "半吉", 76: "凶", 77: "半吉", 78: "半吉",
    79: "凶", 80: "凶", 81: "吉",
}
LUCK81_SCORE = {"吉": 1, "半吉": 0, "凶": -1}

# 车主生日 -> 日柱天干 / 生肖（只看年份和日期，不排完整八字）
GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
GAN_WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
              "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
ZODIAC_WUXING = {"鼠": "水", "牛": "土", "虎": "木", "兔": "木", "龙": "土",
                 "蛇": "火", "马": "火", "羊": "土", "猴": "金", "鸡": "金",
                 "狗": "土", "猪": "水"}


def _dedup(items: Iterable[str]) -> list[str]:
    """去重并保持原顺序，忽略空项。"""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip().upper()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def default_rules() -> dict:
    """一份全新的默认规则（调用方可以随意修改）。"""
    return {
        "flags": {
            "repeat": True,      # 重复字符，如 88
            "sequence": True,    # 顺子，如 1234
            "pair": True,        # 对子，如 6868
            "lucky": True,       # 幸运字符
            "unlucky": True,     # 忌讳字符
            "bad_tail": True,    # 不建议的尾号
        },
        "weights": {
            "repeat": 100_000_000,
            "sequence": 1_000_000_000,
            "pair": 10_000_000,
            "lucky": 100_000_000,
            "unlucky": -10_000_000,
            "bad_tail": -1_000_000,
        },
        "lucky_chars": _dedup(_LUCKY_CHARS),
        "unlucky_chars": _dedup(_UNLUCKY_CHARS),
        "bad_tail": list(_BAD_TAIL),
        # 识别参数（原来是散落在代码里的魔数）
        "detect": {
            "min_area": 1000,
            "min_aspect": 2.0,
            "psm": 6,
            "whitelist": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "pattern": r"[A-Z0-9]{5,7}",
            "tesseract_cmd": "",
        },
        # 数字能量（八星磁场 / 81 数理 / 河图五行）。
        # 只做参考展示，默认不改变“得分”；需要时把 sort_mode 改成 energy。
        "energy": {
            "enabled": True,
            "use_81": True,
            "wuxing_bonus": True,
            "tie_break_energy": True,   # 得分相同时，能量分高的排前面
            "sort_mode": "score",       # score = 按得分，energy = 按能量分
            "owner_birthday": "",       # 可选，YYYY-MM-DD，用来看与车主的五行匹配
            "stars": {name: {"enabled": True, "weight": STAR_LUCK[name]}
                      for name in STAR_ORDER},
        },
    }


def normalize_rules(raw: dict | None) -> dict:
    """用默认规则补全外部载入的规则，避免缺 key 直接崩。"""
    rules = default_rules()
    if not raw:
        return rules
    for section in ("flags", "weights", "detect"):
        incoming = raw.get(section) or {}
        if isinstance(incoming, dict):
            rules[section].update(incoming)
    incoming_energy = raw.get("energy") or {}
    if isinstance(incoming_energy, dict):
        for key, value in incoming_energy.items():
            if key == "stars" and isinstance(value, dict):
                for star, star_cfg in value.items():
                    if star in rules["energy"]["stars"] and isinstance(star_cfg, dict):
                        rules["energy"]["stars"][star].update(star_cfg)
            elif key in rules["energy"]:
                rules["energy"][key] = value
    if rules["energy"].get("sort_mode") not in ("score", "energy"):
        rules["energy"]["sort_mode"] = "score"
    for key in ("lucky_chars", "unlucky_chars", "bad_tail"):
        if raw.get(key):
            rules[key] = _dedup(raw[key])
    return rules


def load_rules(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return normalize_rules(json.load(handle))


def save_rules(path: str, rules: dict) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rules, handle, ensure_ascii=False, indent=2)
    return path


def parse_weight(text, default: int = 0) -> int:
    """解析分值文本，支持 1亿 / 1000万 / 1_000_000 / 1000000。"""
    if text is None:
        return default
    raw = str(text).strip().replace(",", "").replace("_", "").replace(" ", "")
    if not raw:
        return default
    factor = 1
    if raw.endswith("亿"):
        factor, raw = 100_000_000, raw[:-1]
    elif raw.endswith("万"):
        factor, raw = 10_000, raw[:-1]
    try:
        return int(round(float(raw) * factor))
    except ValueError as exc:
        raise ValueError(f"无法解析数值：{text}") from exc


def format_price(price: int) -> str:
    """把分数写成便于阅读的中文单位。"""
    value = int(price)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 100_000_000:
        text = f"{value / 100_000_000:.2f}".rstrip("0").rstrip(".") + "亿"
    elif value >= 10_000:
        text = f"{value / 10_000:.2f}".rstrip("0").rstrip(".") + "万"
    else:
        text = str(value)
    return sign + text


# --------------------------------------------------------------------------- #
# 号码解析与打分
# --------------------------------------------------------------------------- #


def extract_number_from_plate(plate_text: str) -> tuple[str, str]:
    """拆出车牌里的数字和字母。"""
    digits = "".join(ch for ch in str(plate_text) if ch.isdigit())
    letters = "".join(ch for ch in str(plate_text) if not ch.isdigit())
    return digits, letters


@dataclass
class Plate:
    """一个待估值的号码。"""

    index: int
    text: str
    digits: str = ""
    letters: str = ""
    price: int = 0
    hits: list[str] = field(default_factory=list)
    box: tuple[int, int, int, int] | None = None
    energy: dict | None = None

    @property
    def source(self) -> str:
        return "image" if self.box else "segment"


def score_plate(plate_text: str, rules: dict | None = None) -> tuple[int, list[str]]:
    """给号码打分，返回 (总分, 命中说明)。

    重复 / 顺子 / 对子 只看数字部分；幸运、忌讳、尾号匹配完整车牌字符，
    这样 ``A43`` / ``G86`` / ``1D6`` 这类含字母的规则才有意义。
    """
    rules = rules or default_rules()
    flags = rules["flags"]
    weights = rules["weights"]

    digits, letters = extract_number_from_plate(plate_text)
    full = re.sub(r"[^0-9A-Za-z]", "", f"{letters}{digits}").upper()

    price = 0
    hits: list[str] = []

    if flags.get("repeat"):
        for i in range(len(digits) - 1):
            if digits[i] == digits[i + 1]:
                price += weights["repeat"]
                hits.append(f"重复{digits[i]}{digits[i + 1]}")

    if flags.get("sequence"):
        for i in range(len(digits) - 3):
            window = digits[i:i + 4]
            if window.isdigit():
                step = [int(ch) for ch in window]
                if step == list(range(step[0], step[0] + 4)):
                    price += weights["sequence"]
                    hits.append(f"顺子{window}")

    if flags.get("pair"):
        for i in range(len(digits) - 3):
            if digits[i:i + 2] == digits[i + 2:i + 4]:
                price += weights["pair"]
                hits.append(f"对子{digits[i:i + 4]}")

    if flags.get("lucky"):
        for char in rules["lucky_chars"]:
            if char and char in full:
                price += weights["lucky"]
                hits.append(f"幸运{char}")

    if flags.get("unlucky"):
        for char in rules["unlucky_chars"]:
            if char and char in full:
                price += weights["unlucky"]
                hits.append(f"忌讳{char}")

    if flags.get("bad_tail"):
        for char in rules["bad_tail"]:
            if char and full.endswith(char):
                price += weights["bad_tail"]
                hits.append(f"尾号{char}")

    return price, hits


def make_plate(index: int, text: str, rules: dict | None = None,
               box: tuple[int, int, int, int] | None = None) -> Plate:
    rules = rules or default_rules()
    text = str(text).strip().upper()
    digits, letters = extract_number_from_plate(text)
    price, hits = score_plate(text, rules)
    return Plate(index=index, text=text, digits=digits, letters=letters,
                 price=price, hits=hits, box=box,
                 energy=energy_analysis(text, rules))


def sort_plates(plates: Sequence[Plate], mode: str = "score") -> list[Plate]:
    """排序。

    mode="score"：得分降序，同分时能量分高的优先（未启用则按号码）。
    mode="energy"：能量分降序，再看得分。
    """
    if mode == "energy":
        return sorted(plates, key=lambda plate: (
            -(plate.energy or {}).get("score", 0), -plate.price, plate.text))
    return sorted(plates, key=lambda plate: (
        -plate.price, -(plate.energy or {}).get("score", 0), plate.text))


def build_plates(numbers: Iterable[str], rules: dict | None = None) -> list[Plate]:
    """给一批号码编号并估值。"""
    rules = rules or default_rules()
    return sort_plates([make_plate(i + 1, text, rules)
                        for i, text in enumerate(numbers)], sort_mode(rules))


# --------------------------------------------------------------------------- #
# 号段展开
# --------------------------------------------------------------------------- #


def parse_segment_line(line: str) -> tuple[str, str] | None:
    """把 "FU5N00-FU5N99" / "FU5N00~FU5N99" / "FU5N00 至 FU5N99" 拆成两端。"""
    text = (line or "").strip()
    if not text or text.startswith("#"):
        return None
    match = re.match(r"^\s*([0-9A-Za-z]+)\s*(?:-|~|～|至|到)\s*([0-9A-Za-z]+)\s*$", text)
    if not match:
        raise ValueError(f"号段格式不正确：{line}（示例：FU5N00-FU5N99）")
    return match.group(1).upper(), match.group(2).upper()


def expand_segment(start: str, end: str) -> list[str]:
    """展开一个号段，含首尾且不重复。"""
    start = str(start).strip().upper()
    end = str(end).strip().upper()
    if not start or not end:
        raise ValueError("号段两端不能为空")

    common = 0
    while common < min(len(start), len(end)) and start[common] == end[common]:
        common += 1

    head = start[:common]
    tail_start = start[common:]
    tail_end = end[common:]

    if not tail_start.isdigit() or not tail_end.isdigit():
        raise ValueError(f"号段 {start}-{end} 的差异部分必须是数字")
    if len(tail_start) != len(tail_end):
        raise ValueError(f"号段 {start}-{end} 两端数字位数不一致")

    low, high = sorted((int(tail_start), int(tail_end)))
    width = len(tail_start)
    return [f"{head}{value:0{width}d}" for value in range(low, high + 1)]


def expand_segments(lines: Iterable[str]) -> list[str]:
    """展开多行号段，保持顺序并去重。"""
    numbers: list[str] = []
    seen: set[str] = set()
    for line in lines:
        pair = parse_segment_line(line)
        if pair is None:
            continue
        for number in expand_segment(*pair):
            if number not in seen:
                seen.add(number)
                numbers.append(number)
    return numbers


# --------------------------------------------------------------------------- #
# 数字能量分析（八星磁场 / 81 数理 / 河图五行 / 车主匹配）
# --------------------------------------------------------------------------- #


def parse_birthday(text: str):
    """接受 1990-05-20 / 1990/5/20 / 19900520，非法返回 None。"""
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    if len(digits) != 8:
        return None
    year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day


def day_pillar(year: int, month: int, day: int) -> tuple[str, str]:
    """公历 -> 日柱天干地支。锚点：1949-10-01 为甲子日。"""
    a = (14 - month) // 12
    yy = year + 4800 - a
    mm = month + 12 * a - 3
    jdn = day + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    index = (jdn + 49) % 60
    return GAN[index % 10], ZHI[index % 12]


def zodiac_of(year: int) -> str:
    return ZODIAC[(year - 4) % 12]


def energy_analysis(plate_text: str, rules: dict | None = None):
    """算一块车牌的数字能量，返回 dict；未启用时返回 None。

    只分析数字部分（字母不参与八星组合），与「数字能量学」常见口径一致。
    """
    rules = rules or default_rules()
    config = rules.get("energy") or {}
    if not config.get("enabled", True):
        return None

    digits, _letters = extract_number_from_plate(plate_text)
    if not digits:
        return None

    star_config = config.get("stars") or {}
    pairs: list[tuple[str, str]] = []
    star_score = 0
    counts: dict[str, int] = {}

    for i in range(len(digits) - 1):
        pair = digits[i:i + 2]
        star = PAIR_STAR.get(pair)
        pairs.append((pair, star or ("0" if "0" in pair else "—")))
        if not star:
            continue
        item = star_config.get(star) or {}
        if item.get("enabled", True):
            star_score += int(item.get("weight", STAR_LUCK[star]))
            counts[star] = counts.get(star, 0) + 1

    good = sum(n for star, n in counts.items() if STAR_LUCK[star] > 0)
    bad = sum(n for star, n in counts.items() if STAR_LUCK[star] < 0)

    wuxing = {name: 0 for name in WUXING_ORDER}
    for digit in digits:
        element = DIGIT_WUXING[digit]
        wuxing[element] += 1
    missing = [name for name in WUXING_ORDER if wuxing[name] == 0]

    digit_sum = sum(int(digit) for digit in digits)
    number81 = digit_sum
    while number81 > 81:
        number81 -= 80
    luck81 = LUCK81.get(number81, "—")

    score = 50 + star_score * 4
    if config.get("use_81", True):
        score += LUCK81_SCORE.get(luck81, 0) * 15
    if config.get("wuxing_bonus", True):
        score += (2 - min(len(missing), 2)) * 2

    owner = None
    match_score = 0
    birthday = str(config.get("owner_birthday") or "").strip()
    parsed = parse_birthday(birthday) if birthday else None
    if parsed:
        year, month, day = parsed
        gan, zhi = day_pillar(year, month, day)
        zodiac = zodiac_of(year)
        master = GAN_WUXING[gan]
        sheng_me = next(name for name, child in SHENG.items() if child == master)
        ke_me = next(name for name, target in KE.items() if target == master)
        help_n = wuxing[sheng_me] + wuxing[master]
        harm_n = wuxing[ke_me]
        match_score = max(-15, min(15, (help_n - harm_n) * 3))
        score += match_score
        owner = {
            "birthday": "%04d-%02d-%02d" % (year, month, day),
            "zodiac": zodiac,
            "zodiac_wx": ZODIAC_WUXING[zodiac],
            "day_pillar": gan + zhi,
            "master": master,
            "help": help_n,
            "harm": harm_n,
            "sheng_me": sheng_me,
            "ke_me": ke_me,
            "match_score": match_score,
        }

    score = max(0, min(100, score))
    grade = "偏吉" if score >= 75 else ("中平" if score >= 55 else "偏凶")

    notes: list[str] = []
    if pairs:
        notes.append("相邻组合：" + "、".join(f"{pair}→{star}" for pair, star in pairs))
    if counts:
        good_text = "、".join(f"{star}×{n}" for star, n in counts.items()
                              if STAR_LUCK[star] > 0)
        bad_text = "、".join(f"{star}×{n}" for star, n in counts.items()
                             if STAR_LUCK[star] < 0)
        parts = ([f"吉星 {good_text}"] if good_text else []) + \
                ([f"凶星 {bad_text}"] if bad_text else [])
        notes.append("；".join(parts) + f"（吉 {good} 组 / 凶 {bad} 组）")
        if bad and not good:
            notes.append("只有凶星，按这套口径能量偏消耗。")
        elif bad > good:
            notes.append("凶星多于吉星，按这套口径能量偏消耗。")
        elif good > bad:
            notes.append("吉星多于凶星，按这套口径能量偏助益。")
    notes.append(f"81 数理：各位和 {digit_sum} → {number81}，判为「{luck81}」。")
    present = "、".join(f"{name}{n}" for name, n in wuxing.items() if n)
    notes.append("五行：" + (present or "无")
                 + ("；缺 " + "、".join(missing) if missing else "；五行齐全"))
    if owner:
        notes.append(f"车主：生肖{owner['zodiac']}（{owner['zodiac_wx']}），"
                     f"日柱{owner['day_pillar']}，日主{owner['master']}。")
        if match_score > 0:
            notes.append(f"号码里「{owner['sheng_me']}(生你)+{owner['master']}(同你)」"
                         f"多于「{owner['ke_me']}(克你)」，对日主有助益。")
        elif match_score < 0:
            notes.append(f"号码里「{owner['ke_me']}(克你)」偏多，对日主稍有消耗。")
        else:
            notes.append("号码五行与日主的生克基本持平。")
        if wuxing[owner["zodiac_wx"]] >= 2:
            notes.append(f"生肖属{owner['zodiac_wx']}，号码中{owner['zodiac_wx']}较多，"
                         f"与生肖相合。")

    return {
        "digits": digits,
        "pairs": pairs,
        "star_counts": counts,
        "star_score": star_score,
        "good": good,
        "bad": bad,
        "wuxing": wuxing,
        "missing": missing,
        "digit_sum": digit_sum,
        "n81": number81,
        "luck81": luck81,
        "owner": owner,
        "match_score": match_score,
        "score": score,
        "grade": grade,
        "notes": notes,
    }


def format_energy(energy: dict | None) -> str:
    """表格里用的紧凑写法：62分·吉2凶1。"""
    if not energy:
        return "-"
    return f"{energy['score']}分·吉{energy['good']}凶{energy['bad']}"


def format_energy_detail(energy: dict | None) -> str:
    """详情面板用的完整一行。"""
    if not energy:
        return "数字能量分析未启用"
    pairs = "、".join(f"{pair}→{star}" for pair, star in energy["pairs"]) or "无相邻数字"
    missing = "、".join(energy["missing"]) or "无"
    text = (f"八星 {pairs} ｜ 五行 " +
            "、".join(f"{name}{n}" for name, n in energy["wuxing"].items() if n) +
            f"（缺 {missing}）｜ 81 数理 {energy['digit_sum']}→{energy['n81']}"
            f"{energy['luck81']} ｜ 能量 {energy['score']} 分（{energy['grade']}）")
    if energy.get("owner"):
        text += f" ｜ 车主日主{energy['owner']['master']}"
    return text


def sort_mode(rules: dict | None) -> str:
    return ((rules or {}).get("energy") or {}).get("sort_mode", "score")


def rescore(plates: Sequence[Plate], rules: dict | None = None) -> list[Plate]:
    """规则变了以后，用原有号码重新算分（不需要重新 OCR）。"""
    rules = rules or default_rules()
    return sort_plates([make_plate(plate.index, plate.text, rules, plate.box)
                        for plate in plates], sort_mode(rules))


# --------------------------------------------------------------------------- #
# 图片读写
# --------------------------------------------------------------------------- #

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


def load_image(path: str) -> np.ndarray:
    """读图。用 np.fromfile + imdecode，避免中文/空格路径下 imread 静默失败。"""
    if not path:
        raise ValueError("尚未选择图片")
    if not os.path.exists(path):
        raise ValueError(f"图片不存在：{path}")
    if os.path.getsize(path) == 0:
        raise ValueError(f"图片内容为空：{path}")
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法解码图片（格式不支持？）：{path}")
    return image


def save_image(path: str, image: np.ndarray) -> str:
    ext = os.path.splitext(path)[1].lower() or ".png"
    ok, buffer = cv2.imencode(ext, image)
    if not ok:
        raise ValueError(f"图片编码失败：{path}")
    buffer.tofile(path)
    return path


def bgr_to_rgb(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def zoom_region(image: np.ndarray, box: Sequence[int], scale: float = 1.0,
                margin: int = 12) -> np.ndarray:
    """裁剪并放大一块区域（用于界面里的局部放大）。"""
    if image is None or image.size == 0:
        raise ValueError("没有可放大的图像")
    height, width = image.shape[:2]
    x, y, w, h = (int(v) for v in box)
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(width, x + w + margin), min(height, y + h + margin)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("裁剪区域无效")
    crop = image[y0:y1, x0:x1]
    if abs(scale - 1.0) < 0.01:
        return crop
    return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


# --------------------------------------------------------------------------- #
# tesseract 定位
# --------------------------------------------------------------------------- #

# 随程序分发的相对路径（打包时把可执行文件和 tessdata 放进 tesseract/ ）
_BUNDLED_EXES = ("tesseract/tesseract", "tesseract/bin/tesseract",
                 "tesseract/tesseract.exe")
_BUNDLED_TESSDATA = ("tesseract/tessdata", "tesseract/share/tessdata")
_COMMON_EXES = (
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

_TESSDATA_DIR = ""   # configure_tesseract 里填，OCR 时用


def bundle_roots() -> list[str]:
    """打包后可能存放附带文件的位置（_MEIPASS、可执行文件所在目录等）。"""
    roots: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    roots.extend([exe_dir, os.path.dirname(exe_dir)])
    for base in list(roots):
        roots.extend([os.path.join(base, "Frameworks"),
                      os.path.join(base, "Resources")])
    roots.append(os.path.dirname(os.path.abspath(__file__)))

    unique: list[str] = []
    for root in roots:
        if root and root not in unique:
            unique.append(root)
    return unique


def _first_existing(root: str, subpaths: Sequence[str]) -> str:
    for sub in subpaths:
        candidate = os.path.join(root, *sub.split("/"))
        if os.path.exists(candidate):
            return candidate
    return ""


def find_bundled_tessdata() -> str:
    for root in bundle_roots():
        found = _first_existing(root, _BUNDLED_TESSDATA)
        if found and os.path.isdir(found):
            return found
    return ""


def find_tesseract(explicit: str = "", bundled_only: bool = False) -> tuple[str, str]:
    """定位 tesseract，返回 (路径, 来源说明)。"""
    explicit = (explicit or os.environ.get("PLATE_TESSERACT", "")).strip()
    if explicit and os.path.exists(explicit):
        return explicit, "指定路径"

    for root in bundle_roots():
        found = _first_existing(root, _BUNDLED_EXES)
        if found:
            return found, "随程序分发"

    if bundled_only:
        raise RuntimeError(
            "没有找到随程序分发的 tesseract（应该在程序目录的 tesseract/ 下）"
        )

    found = shutil.which("tesseract")
    if found:
        return found, "系统 PATH"

    for candidate in _COMMON_EXES:
        if os.path.exists(candidate):
            return candidate, "常见安装位置"

    raise RuntimeError(
        "找不到 tesseract。macOS 可执行 brew install tesseract；"
        "Windows 可安装 Tesseract-OCR。也可以在“规则与设置”页签里手动填写路径。"
    )


def configure_tesseract(command: str = "", bundled_only: bool = False) -> tuple[str, str]:
    """配置 pytesseract，返回 (tesseract 路径, 来源说明)。"""
    if pytesseract is None:
        raise RuntimeError("未安装 pytesseract：pip install pytesseract")

    global _TESSDATA_DIR

    exe, source = find_tesseract(command, bundled_only)
    pytesseract.pytesseract.tesseract_cmd = exe

    _TESSDATA_DIR = ""
    if source == "随程序分发":
        tessdata = find_bundled_tessdata()
        if tessdata:
            _TESSDATA_DIR = tessdata
            os.environ["TESSDATA_PREFIX"] = tessdata
            # pytesseract 在 import 时拷贝了一份 environ，subprocess 用的是那份
            environ = getattr(pytesseract.pytesseract, "environ", None)
            if isinstance(environ, dict):
                environ["TESSDATA_PREFIX"] = tessdata
    return exe, source


def tessdata_dir() -> str:
    return _TESSDATA_DIR


def tesseract_version(command: str = "", timeout: int = 20) -> str:
    """跑一次 `tesseract --version`，确认它真的能启动（Windows 上能查出缺 DLL）。"""
    import subprocess

    exe, _source = find_tesseract(command)
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, timeout=timeout,
                              text=True, errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"tesseract 启动超时：{exe}") from exc
    except OSError as exc:
        raise RuntimeError(f"tesseract 无法执行：{exe}（{exc}）") from exc
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract 返回 {proc.returncode}：{output[:200]}")
    return output.splitlines()[0] if output else "（无版本信息）"


# --------------------------------------------------------------------------- #
# 图片识别
# --------------------------------------------------------------------------- #


@dataclass
class DetectParams:
    min_area: int = 1000
    min_aspect: float = 2.0
    psm: int = 6
    whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    pattern: str = r"[A-Z0-9]{5,7}"
    tesseract_cmd: str = ""

    @classmethod
    def from_rules(cls, rules: dict | None) -> "DetectParams":
        detect = (rules or {}).get("detect", {}) or {}
        params = cls()
        for key in ("min_area", "min_aspect", "psm", "whitelist", "pattern",
                    "tesseract_cmd"):
            value = detect.get(key)
            if value not in (None, ""):
                setattr(params, key, value)
        params.min_area = int(params.min_area)
        params.min_aspect = float(params.min_aspect)
        params.psm = int(params.psm)
        return params


def ocr_crop(crop: np.ndarray, params: DetectParams, timeout: int = 60) -> str:
    """对单个候选区域做 OCR，返回只含字母数字的大写结果。"""
    config = f"--oem 3 --psm {int(params.psm)}"
    if params.whitelist:
        config += f" -c tessedit_char_whitelist={params.whitelist}"
    # 路径里没有空格时再补一个 --tessdata-dir，双保险
    if _TESSDATA_DIR and " " not in _TESSDATA_DIR:
        config += f" --tessdata-dir {_TESSDATA_DIR}"
    # 给个超时，免得 tesseract 卡住（缺 DLL、弹窗等）时整个程序跟着挂死
    raw = pytesseract.image_to_string(crop, config=config, timeout=timeout)
    return re.sub(r"[^0-9A-Za-z]", "", raw).upper()


def detect_plates(image: np.ndarray, rules: dict | None = None,
                  params: DetectParams | None = None,
                  log: Callable[[str], None] | None = None) -> tuple[list[Plate], np.ndarray]:
    """在图片里找车牌并估值，返回 (车牌列表, 标注图)。

    标注图画在原始彩色图上（不是中间处理过的灰度图）。
    """
    rules = rules or default_rules()
    params = params or DetectParams.from_rules(rules)
    say = log or (lambda _message: None)

    if image is None or image.size == 0:
        raise ValueError("图像为空")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if gray.dtype != np.uint8:
        gray = cv2.convertScaleAbs(gray)

    say(f"图像尺寸：{gray.shape[1]}x{gray.shape[0]}")

    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
    sharpen = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(blurred, -1, sharpen)
    binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 11, 2)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    say(f"候选轮廓数量：{len(contours)}")

    plates: list[Plate] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h <= 0 or w * h <= params.min_area or w / float(h) <= params.min_aspect:
            continue
        text = ocr_crop(gray[y:y + h, x:x + w], params)
        if not re.fullmatch(params.pattern, text):
            continue
        plate = make_plate(len(plates) + 1, text, rules, box=(x, y, w, h))
        plates.append(plate)
        say(f"识别到：{plate.text}（得分 {plate.price}）")

    return plates, annotate_image(image, plates)


def annotate_image(image: np.ndarray, plates: Sequence[Plate],
                   show_price: bool = True) -> np.ndarray:
    """画出车牌框、序号、号码和得分（OpenCV 画不了中文，标签只用 ASCII）。"""
    canvas = image.copy()
    for plate in plates:
        if not plate.box:
            continue
        x, y, w, h = plate.box
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (0, 220, 0), 2)

        label = f"{plate.index} {plate.text}"
        if show_price:
            label += f"  {plate.price}"
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        top = max(0, y - text_h - 10)
        cv2.rectangle(canvas, (x, top), (x + text_w + 8, y), (0, 220, 0), -1)
        cv2.putText(canvas, label, (x + 4, y - 6), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (20, 20, 20), 2, cv2.LINE_AA)
    return canvas


# --------------------------------------------------------------------------- #
# 文本报告
# --------------------------------------------------------------------------- #

LINE = "=" * 68
THIN = "-" * 68


def _format_hits(hits: Sequence[str], limit: int = 6) -> str:
    if not hits:
        return "-"
    text = "、".join(hits[:limit])
    if len(hits) > limit:
        text += f" 等 {len(hits)} 项"
    return text


def build_report(title: str, source: str, plates: Sequence[Plate],
                 extra_lines: Sequence[str] = (), top_n: int = 10,
                 rules: dict | None = None) -> str:
    """生成文本报告。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ranked = sort_plates(plates, sort_mode(rules))

    lines: list[str] = [LINE, title, LINE]
    lines.append(f"生成时间：{now}")
    lines.append(f"数据来源：{source}")
    lines.extend(extra_lines)
    lines.append(f"号码总数：{len(ranked)}")

    if ranked:
        prices = [plate.price for plate in ranked]
        lines.append(f"最高得分：{format_price(ranked[0].price)}（{ranked[0].text}）")
        lines.append(f"最低得分：{format_price(ranked[-1].price)}（{ranked[-1].text}）")
        lines.append(f"平均得分：{format_price(int(sum(prices) / len(prices)))}")
        lines.append(f"正分号码数：{sum(1 for price in prices if price > 0)}")

    lines.append("")
    order_text = "按能量分降序" if sort_mode(rules) == "energy" else "按得分降序"
    lines.append(f"【全部结果（{order_text}）】")
    lines.append(THIN)
    show_energy = any(plate.energy for plate in ranked)
    header = f"{'排名':>4}  {'车牌号':<10} {'数字':<8} {'得分':>12}"
    if show_energy:
        header += f" {'能量':>8}"
    lines.append(header + "  命中规则")
    lines.append(THIN)
    for rank, plate in enumerate(ranked, start=1):
        row = (f"{rank:>4}  {plate.text:<10} {plate.digits or '-':<8} "
               f"{format_price(plate.price):>12}")
        if show_energy:
            row += f" {format_energy(plate.energy):>8}"
        lines.append(row + f"  {_format_hits(plate.hits)}")

    if top_n and ranked:
        picks = ranked[:top_n]
        lines.append("")
        lines.append(f"【推荐 Top {len(picks)}】")
        lines.append(THIN)
        for rank, plate in enumerate(picks, start=1):
            lines.append(f"{rank:>2}. {plate.text}    得分 {format_price(plate.price)}"
                         f"    命中：{_format_hits(plate.hits)}")

    if show_energy:
        detail = ranked[:max(top_n or 10, 1)]
        lines.append("")
        lines.append(f"【数字能量参考（前 {len(detail)} 个）】")
        lines.append(THIN)
        lines.append("  口径：八星磁场（相邻两位数字）+ 81 数理 + 河图五行，")
        lines.append("        属民俗 / 娱乐参考，不是科学结论；可在「数字能量」页签调整。")
        for rank, plate in enumerate(detail, start=1):
            energy = plate.energy or {}
            lines.append("")
            lines.append(f"  {rank}. {plate.text} ｜ 能量 {energy.get('score', 0)} 分"
                         f"（{energy.get('grade', '-')}）")
            for note in energy.get("notes", []):
                lines.append("     · " + note)

    lines.append("")
    lines.append(LINE)
    lines.append("说明：得分由脚本规则计算，仅供选号参考，不构成任何承诺。")
    lines.append(LINE)
    return "\n".join(lines) + "\n"


def write_text(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def write_csv(path: str, plates: Sequence[Plate], mode: str = "score") -> str:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["排名", "车牌号", "数字部分", "字母部分", "得分", "命中规则",
                         "能量分", "能量等级", "八星组合", "81数理"])
        for rank, plate in enumerate(sort_plates(plates, mode), start=1):
            energy = plate.energy or {}
            pairs = "、".join(f"{pair}→{star}"
                             for pair, star in energy.get("pairs", []))
            luck81 = (f"{energy['n81']}{energy['luck81']}"
                      if energy else "")
            writer.writerow([rank, plate.text, plate.digits, plate.letters,
                             plate.price, "、".join(plate.hits),
                             energy.get("score", ""), energy.get("grade", ""),
                             pairs, luck81])
    return path


def suggest_name(prefix: str, suffix: str = ".txt") -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}{suffix}"


# --------------------------------------------------------------------------- #
# 自检用的合成样本（不提交任何真实数据）
# --------------------------------------------------------------------------- #

def make_sample_plate_image(text: str = "FU5N88") -> np.ndarray:
    """画一张车牌样子的图，用于自检 OCR 链路。"""
    image = np.full((120, 460, 3), 255, np.uint8)
    cv2.rectangle(image, (6, 6), (452, 112), (0, 0, 0), 3)
    cv2.putText(image, text, (34, 84), cv2.FONT_HERSHEY_SIMPLEX, 2.4, (0, 0, 0), 6,
                cv2.LINE_AA)
    return image
