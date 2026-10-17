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
    text = str(text).strip().upper()
    digits, letters = extract_number_from_plate(text)
    price, hits = score_plate(text, rules)
    return Plate(index=index, text=text, digits=digits, letters=letters,
                 price=price, hits=hits, box=box)


def sort_plates(plates: Sequence[Plate]) -> list[Plate]:
    """按得分降序，同分按号码升序（同分顺序稳定）。"""
    return sorted(plates, key=lambda plate: (-plate.price, plate.text))


def build_plates(numbers: Iterable[str], rules: dict | None = None) -> list[Plate]:
    """给一批号码编号并估值。"""
    return sort_plates([make_plate(i + 1, text, rules)
                        for i, text in enumerate(numbers)])


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


def ocr_crop(crop: np.ndarray, params: DetectParams) -> str:
    """对单个候选区域做 OCR，返回只含字母数字的大写结果。"""
    config = f"--oem 3 --psm {int(params.psm)}"
    if params.whitelist:
        config += f" -c tessedit_char_whitelist={params.whitelist}"
    # 路径里没有空格时再补一个 --tessdata-dir，双保险
    if _TESSDATA_DIR and " " not in _TESSDATA_DIR:
        config += f" --tessdata-dir {_TESSDATA_DIR}"
    raw = pytesseract.image_to_string(crop, config=config)
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
                 extra_lines: Sequence[str] = (), top_n: int = 10) -> str:
    """生成文本报告。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ranked = sort_plates(plates)

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
    lines.append("【全部结果（按得分降序）】")
    lines.append(THIN)
    lines.append(f"{'排名':>4}  {'车牌号':<10} {'数字':<8} {'得分':>12}  命中规则")
    lines.append(THIN)
    for rank, plate in enumerate(ranked, start=1):
        lines.append(f"{rank:>4}  {plate.text:<10} {plate.digits or '-':<8} "
                     f"{format_price(plate.price):>12}  {_format_hits(plate.hits)}")

    if top_n and ranked:
        picks = ranked[:top_n]
        lines.append("")
        lines.append(f"【推荐 Top {len(picks)}】")
        lines.append(THIN)
        for rank, plate in enumerate(picks, start=1):
            lines.append(f"{rank:>2}. {plate.text}    得分 {format_price(plate.price)}"
                         f"    命中：{_format_hits(plate.hits)}")

    lines.append("")
    lines.append(LINE)
    lines.append("说明：得分由脚本规则计算，仅供选号参考，不构成任何承诺。")
    lines.append(LINE)
    return "\n".join(lines) + "\n"


def write_text(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def write_csv(path: str, plates: Sequence[Plate]) -> str:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["排名", "车牌号", "数字部分", "字母部分", "得分", "命中规则"])
        for rank, plate in enumerate(sort_plates(plates), start=1):
            writer.writerow([rank, plate.text, plate.digits, plate.letters,
                             plate.price, "、".join(plate.hits)])
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
