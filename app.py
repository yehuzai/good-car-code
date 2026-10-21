"""车牌筛选工具 - Tkinter 界面（三个页签）与打包入口。

界面里做三件事：从图片识别车牌、按号段批量筛选、编辑打分规则并出文本报告。
所有可测逻辑都在 core.py；本文件只负责界面和 `--selftest` 入口。

无界面自检：
    python app.py --selftest
    python app.py --selftest --require-bundled    # 只认随程序分发的 tesseract
"""

from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import traceback
import unicodedata
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

import core

APP_TITLE = "车牌筛选工具"
APP_VERSION = "1.2.0"

if sys.platform == "darwin":
    BASE_FONT = ("PingFang SC", 13)
    MONO = ("Menlo", 12)
elif os.name == "nt":
    BASE_FONT = ("Microsoft YaHei UI", 10)
    MONO = ("Consolas", 10)
else:
    BASE_FONT = ("Sans", 10)
    MONO = ("Monospace", 10)

DEFAULT_SEGMENTS = """\
FX8X00-FX8X99
FU5N00-FU5N99
FR0H00-FR0H99
FR0J00-FR0J99
FR0G00-FR0G99
FR0F00-FR0F99
FR0D00-FR0D99
FR0E00-FR0E99
"""

DISPLAY_LIMITS = ["全部", "前 50", "前 100", "前 500", "前 1000"]

FLAG_LABELS = {
    "repeat": "重复字符（如 88）",
    "sequence": "顺子（如 1234）",
    "pair": "对子（如 6868）",
    "lucky": "幸运字符",
    "unlucky": "忌讳字符",
    "bad_tail": "不建议尾号",
}

# 内置使用说明。改功能时记得同步这里（以及 README.md）。
HELP_SECTIONS: list[tuple[str, str]] = [
    ("1. 这个工具能做什么", """
把挑车牌的流程收在一起：从截图识别候选号码、按号段批量展开、按规则打分排序，
再按需要导出结果。所有计算都在本机完成，不联网。

· 图片识别：在车牌截图里找号码，识别结果按得分排序。
· 号段筛选：输入号段（如 FU5N00-FU5N99），一次评估上百个号码。
· 打分规则：重复、顺子、对子、幸运字符、忌讳字符、尾号，分值都可改。
· 数字能量：八星磁场、81 数理、河图五行，作为额外参考，可整体关闭。
· 导出：文本报告（.txt）、结果表格（.csv）、带框标注图（.png/.jpg）。
"""),
    ("2. 三步快速上手", """
第一步：在「图片识别」里选择图片，点「开始识别」；或者在「号段筛选」里写好号段，
点「开始评估」。

第二步：在右侧结果表里点某一行，下方会显示该号码的细节（图片页签还会放大车牌局部），
用来核对识别结果和参考意见。

第三步：点「生成文本报告」预览并保存，或者「导出 CSV」拿到完整表格。
"""),
    ("3. 图片识别", """
支持的图片格式：png、jpg/jpeg、bmp、webp、tif/tiff。中文路径、带空格的路径都可以。

识别流程：灰度化 → 对比度增强 → 去噪 → 锐化 → 二值化 → 找轮廓 → 逐个区域 OCR。
只有面积和宽高比像车牌的候选区域才会送去识别，结果还要符合 5-7 位字母数字才会留下。

· 勾选「显示识别框」可以在预览里看标注；「清除」只清空当前图片和结果。
· 点结果行 → 下方放大该车牌，方便肉眼核对 OCR 是否读错。
· 「保存标注图」会把编号、号码、得分画在原图上。

识别不到或识别错时，可以按顺序试：
  · 截图里的车牌要完整、尽量水平，字别太小、别糊；
  · 在「规则与设置」里把 PSM 改成 7（单行文本）；
  · 调小「候选最小面积」、调小「候选最小宽高比」；
  · 车牌正则放宽（比如 [A-Z0-9]{4,8}）；
  · 确认 tesseract 路径正确（页签底部有版本提示）。
"""),
    ("4. 号段筛选", """
每行写一个号段，格式是「起始号码-结束号码」，例如：
    FU5N00-FU5N99

· 分隔符支持 -、~、～、「至」、「到」；以 # 开头的行是注释，会被忽略。
· 两端只有最后一段数字可以不同，位数要一致；程序会把这段数字逐个展开。
· 先点「解析号段」可以看一共会展开多少个号码，避免手误。
· 「显示」下拉框控制表格里显示前多少个（全部 / 前 50 / 前 100 / 前 500 / 前 1000），
  导出报告和 CSV 始终是全部号码。

号段也可以从文件载入（.txt / .csv），一行一个号段。
"""),
    ("5. 数字能量（可选参考）", """
只分析车牌的数字部分，字母不参与组合。口径：

· 八星磁场：相邻两位数字 → 天医 / 延年 / 生气 / 伏位（吉），
  绝命 / 五鬼 / 六煞 / 祸害（凶）。含 0 的组合记为无星。
· 81 数理：各位数字之和，超过 81 就反复减 80，再查吉 / 半吉 / 凶。
· 河图五行：1/6 水、2/7 火、3/8 木、4/9 金、5/0 土，统计分布和缺失。
· 车主匹配（可选）：填生日后按日柱、生肖和号码五行给出相合 / 相克提示。

能量分 = 50 + 八星分×4 + 81 数理±15 + 五行齐全加分（+ 车主匹配最多 ±15），
限制在 0-100：≥75 偏吉、≥55 中平、其余偏凶。

默认只展示、不改变「得分」。想让它影响排序，可以在本页签切换「排序依据」为
「能量分」，或者保留「得分相同时按能量分排序」。

· 逐颗星可以单独关掉、改权重；81 数理和五行加分也能关。
· 「试算一个号码」会立刻给出完整口径，改规则后可以马上验证。
· 这部分属于民俗 / 娱乐参考，不是科学结论。
"""),
    ("6. 规则与设置", """
· 分值可以直接写 1亿、1000万、-100万，也可以写 -1000000。
· 幸运 / 忌讳字符每行一个，支持字母组合（如 A43、G86）。
  幸运 / 忌讳 / 尾号匹配「完整车牌字符」，重复 / 顺子 / 对子只看数字部分。
· 不建议尾号用逗号分隔，例如 0, 05。
· 「应用规则」会立刻用已有号码重算（不需要重新识别图片），并刷新表格和报告。
· 「保存规则…」/「载入规则…」把整套规则存成 JSON，换机器也能带走。
· 「恢复默认」把规则恢复成出厂值。
· 「试算号码…」弹窗输入一个车牌，直接看得分和命中项。

识别参数：
  · PSM 6 = 整块文本，7 = 单行文本（车牌通常 6 或 7）。
  · 候选最小面积 / 最小宽高比：越小越宽松，越大越严格。
  · 车牌正则：识别结果必须完全匹配才会留下，默认 [A-Z0-9]{5,7}。
  · OCR 字符白名单：默认只认大写字母和数字，能明显减少误读。
  · tesseract 路径：留空则自动找；打包版会用随程序分发的那一份。
"""),
    ("7. 导出与报告", """
· 生成文本报告：先弹出预览窗口，可以「保存为文件…」或「复制到剪贴板」。
  内容包含统计摘要、全量排序表、推荐 Top N，以及（开启时）数字能量参考段落。
· 导出 CSV：带 BOM 的 UTF-8，Excel 直接打开不乱码；包含得分和数字能量各列。
· 保存标注图：图片页签专用，把识别框、编号、得分画在原图上。
· 报告和 CSV 都按当前排序依据输出（规则得分或能量分）。
"""),
    ("8. 常见问题", """
问：首次打开被系统拦住？
答：macOS 右键点 app →「打开」，或执行 xattr -dr com.apple.quarantine GoodCarCode.app；
    Windows 点「更多信息」→「仍要运行」。

问：提示找不到 tesseract？
答：打包版自带 tesseract，正常不会出现。源码运行时执行 brew install tesseract
    （macOS），或在「规则与设置」里填写 tesseract 路径。

问：得分和能量分为什么不一样？
答：得分是车牌字符规则算出来的相对分值，能量分是八星 / 81 数理 / 五行的 0-100 参考分。
    两者口径不同，默认只有得分参与排序。

问：同一个号码两次识别结果不同？
答：OCR 受截图清晰度影响。可以放大图片重截、调 PSM 或白名单，或者手动用「试算」核对。

问：改完规则要重新识别吗？
答：不需要。点「应用规则」会用已识别的号码直接重算。

问：换电脑后规则还在吗？
答：规则只在本次运行里有效，除非用「保存规则…」存成 JSON，下次「载入规则…」。
"""),
    ("9. 快捷键", """
F1                          打开本使用说明（Mac 上可能需要按 fn+F1）
Cmd+O（Windows 为 Ctrl+O）   选择图片
回车                        在「试算」输入框里直接分析
"""),
    ("10. 关于与免责", """
车牌筛选工具，用来把候选号码按规则排个序、给点参考。

· 打分规则和数字能量都来自常见民俗口径，属于娱乐 / 参考，不构成任何承诺。
· 识别结果可能受截图质量影响，重要号码请以官方渠道为准。
· 项目地址：https://github.com/yehuzai/good-car-code
"""),
]


def _fit(image: np.ndarray, max_width: int, max_height: int,
         allow_upscale: bool = False) -> np.ndarray:
    """等比缩放到目标框内。"""
    height, width = image.shape[:2]
    scale = min(max_width / width, max_height / height)
    if not allow_upscale:
        scale = min(scale, 1.0)
    if scale <= 0:
        return image
    if abs(scale - 1.0) < 0.01:
        return image
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST
    return cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))),
                      interpolation=interpolation)


def _display_width(text: str) -> int:
    """按中日韩字符占两列计算宽度，用于文本报告里的分隔线。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


class PlateApp:
    """主窗口。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.rules = core.default_rules()
        self.rules_path: str | None = None

        self.image: np.ndarray | None = None
        self.image_path = ""
        self.annotated: np.ndarray | None = None
        self.image_plates: list[core.Plate] = []
        self._plates_by_index: dict[int, core.Plate] = {}
        self._tree_plate_map: dict[object, dict[str, core.Plate]] = {}

        self.segment_numbers: list[str] = []
        self.segment_plates: list[core.Plate] = []

        self._photo = None
        self._zoom_photo = None
        self._render_job = None
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._pending_logs: list[str] = []
        self._last_dir = os.path.expanduser("~/Downloads")

        self._build_ui()
        self._load_rules_into_ui()
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------------ #
    # 界面搭建
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} {APP_VERSION}")
        self.root.geometry("1240x800")
        self.root.minsize(1100, 700)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=24)
        style.configure(".", font=BASE_FONT)
        style.configure("Treeview.Heading", font=(BASE_FONT[0], BASE_FONT[1], "bold"))
        style.configure("Title.TLabel", font=(BASE_FONT[0], BASE_FONT[1] + 2, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")

        self.status_var = tk.StringVar(value="就绪")
        bar = ttk.Frame(self.root, padding=(10, 4, 10, 8))
        bar.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="left")
        ttk.Label(bar, textvariable=self.status_var, style="Hint.TLabel").pack(
            side="left", padx=12)
        ttk.Button(bar, text="使用说明 F1", command=self.show_help).pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self.tab_image = ttk.Frame(self.notebook)
        self.tab_segment = ttk.Frame(self.notebook)
        self.tab_rules = ttk.Frame(self.notebook)
        self.tab_energy = ttk.Frame(self.notebook)
        self.tab_help = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_image, text="  图片识别  ")
        self.notebook.add(self.tab_segment, text="  号段筛选  ")
        self.notebook.add(self.tab_energy, text="  数字能量  ")
        self.notebook.add(self.tab_rules, text="  规则与设置  ")
        self.notebook.add(self.tab_help, text="  使用说明  ")

        self._build_image_tab()
        self._build_segment_tab()
        self._build_energy_tab()
        self._build_rules_tab()
        self._build_help_tab()
        self._build_menu()
        self.root.bind_all("<F1>", lambda _event: self.show_help())
        mod = "Command" if sys.platform == "darwin" else "Control"
        self.root.bind_all(f"<{mod}-o>", lambda _event: self.choose_image())

    # ------------------------------ 页签 1 ------------------------------ #

    def _build_image_tab(self) -> None:
        parent = self.tab_image

        toolbar = ttk.Frame(parent, padding=(10, 8, 10, 4))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="选择图片…", command=self.choose_image).pack(side="left")
        self.image_var = tk.StringVar(value="尚未选择图片")
        ttk.Label(toolbar, textvariable=self.image_var, style="Hint.TLabel").pack(
            side="left", padx=10)
        self.show_annot = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="显示识别框", variable=self.show_annot,
                        command=self.render_preview).pack(side="right")
        ttk.Button(toolbar, text="清除", command=self.clear_image).pack(side="right", padx=8)

        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        self.preview_canvas = tk.Canvas(left, bg="#1f1f23", highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.bind("<Configure>", self._on_preview_resize)

        box = ttk.LabelFrame(right, text="识别结果", padding=6)
        box.pack(fill="both", expand=True)
        columns = ("rank", "plate", "digits", "score", "energy", "hits")
        self.image_tree = ttk.Treeview(box, columns=columns, show="headings",
                                       selectmode="browse")
        for key, text, width, anchor in (
            ("rank", "序号", 44, "center"),
            ("plate", "车牌号", 84, "center"),
            ("digits", "数字", 60, "center"),
            ("score", "得分", 78, "e"),
            ("energy", "能量", 96, "center"),
            ("hits", "命中规则", 120, "w"),
        ):
            self.image_tree.heading(key, text=text)
            self.image_tree.column(key, width=width, anchor=anchor,
                                   stretch=(key == "hits"))
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.image_tree.yview)
        self.image_tree.configure(yscrollcommand=scroll.set)
        self.image_tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.image_tree.bind("<<TreeviewSelect>>", self.on_image_select)

        zoom_box = ttk.LabelFrame(right, text="局部放大（点击上方结果查看）", padding=6)
        zoom_box.pack(fill="x", pady=(8, 0))
        self.zoom_canvas = tk.Canvas(zoom_box, height=130, bg="#1f1f23",
                                     highlightthickness=0)
        self.zoom_canvas.pack(fill="x")
        self.zoom_canvas.bind("<Configure>", lambda _e: self.on_image_select())

        actions = ttk.Frame(parent, padding=(10, 0, 10, 8))
        actions.pack(fill="x")
        self.detect_button = ttk.Button(actions, text="开始识别", command=self.run_detect)
        self.detect_button.pack(side="left")
        ttk.Button(actions, text="生成文本报告", command=self.report_for_image).pack(
            side="left", padx=6)
        ttk.Button(actions, text="导出 CSV", command=self.csv_for_image).pack(side="left")
        ttk.Button(actions, text="保存标注图", command=self.save_annotated).pack(
            side="left", padx=6)

    # ------------------------------ 页签 2 ------------------------------ #

    def _build_segment_tab(self) -> None:
        parent = self.tab_segment
        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=8)
        left = ttk.Frame(paned, width=360)
        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        entry_box = ttk.LabelFrame(left, text="号段列表（每行一个）", padding=8)
        entry_box.pack(fill="both", expand=True)
        ttk.Label(entry_box, text="格式：FU5N00-FU5N99（末尾数字自动展开）",
                  style="Hint.TLabel").pack(anchor="w", pady=(0, 4))
        text_frame = ttk.Frame(entry_box)
        text_frame.pack(fill="both", expand=True)
        self.segment_text = tk.Text(text_frame, height=16, width=34, wrap="none",
                                    font=MONO)
        seg_scroll = ttk.Scrollbar(text_frame, orient="vertical",
                                   command=self.segment_text.yview)
        self.segment_text.configure(yscrollcommand=seg_scroll.set)
        self.segment_text.grid(row=0, column=0, sticky="nsew")
        seg_scroll.grid(row=0, column=1, sticky="ns")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        self.segment_text.insert("1.0", DEFAULT_SEGMENTS)

        row = ttk.Frame(entry_box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="解析号段", command=self.preview_segment_count).pack(side="left")
        ttk.Button(row, text="载入文件…", command=self.load_segments_file).pack(
            side="left", padx=6)
        ttk.Button(row, text="清空", command=lambda: self.segment_text.delete("1.0", "end")).pack(
            side="left")

        self.segment_count_var = tk.StringVar(value="")
        ttk.Label(entry_box, textvariable=self.segment_count_var,
                  style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

        result_box = ttk.LabelFrame(right, text="评估结果", padding=6)
        result_box.pack(fill="both", expand=True)
        head = ttk.Frame(result_box)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="显示：").pack(side="left")
        self.display_limit = tk.StringVar(value=DISPLAY_LIMITS[2])
        chooser = ttk.Combobox(head, textvariable=self.display_limit, width=8,
                               state="readonly", values=DISPLAY_LIMITS)
        chooser.pack(side="left")
        chooser.bind("<<ComboboxSelected>>", lambda _e: self.refresh_segment_tree())
        self.segment_summary_var = tk.StringVar(value="尚未评估")
        ttk.Label(head, textvariable=self.segment_summary_var,
                  style="Hint.TLabel").pack(side="left", padx=12)

        table = ttk.Frame(result_box)
        table.pack(fill="both", expand=True)
        columns = ("rank", "plate", "digits", "score", "energy", "hits")
        self.segment_tree = ttk.Treeview(table, columns=columns, show="headings")
        for key, text, width, anchor in (
            ("rank", "排名", 50, "center"),
            ("plate", "车牌号", 96, "center"),
            ("digits", "数字", 70, "center"),
            ("score", "得分", 88, "e"),
            ("energy", "能量", 96, "center"),
            ("hits", "命中规则", 240, "w"),
        ):
            self.segment_tree.heading(key, text=text)
            self.segment_tree.column(key, width=width, anchor=anchor,
                                     stretch=(key == "hits"))
        seg_scroll2 = ttk.Scrollbar(table, orient="vertical",
                                    command=self.segment_tree.yview)
        self.segment_tree.configure(yscrollcommand=seg_scroll2.set)
        self.segment_tree.grid(row=0, column=0, sticky="nsew")
        seg_scroll2.grid(row=0, column=1, sticky="ns")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.segment_tree.bind("<<TreeviewSelect>>", self.on_segment_select)

        detail_box = ttk.LabelFrame(result_box, text="所选号码的数字能量", padding=6)
        detail_box.pack(fill="x", pady=(6, 0))
        self.segment_detail_var = tk.StringVar(
            value="选中一行查看八星 / 五行 / 81 数理详情（在“数字能量”页签可关闭）")
        ttk.Label(detail_box, textvariable=self.segment_detail_var,
                  style="Hint.TLabel", wraplength=640, justify="left").pack(anchor="w")

        actions = ttk.Frame(parent, padding=(10, 0, 10, 8))
        actions.pack(fill="x")
        self.segment_button = ttk.Button(actions, text="开始评估", command=self.run_segments)
        self.segment_button.pack(side="left")
        ttk.Button(actions, text="生成文本报告", command=self.report_for_segments).pack(
            side="left", padx=6)
        ttk.Button(actions, text="导出 CSV", command=self.csv_for_segments).pack(side="left")

    # ------------------------------ 页签 3 ------------------------------ #

    def _build_energy_tab(self) -> None:
        parent = self.tab_energy
        body = ttk.Frame(parent, padding=10)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=530)
        right = ttk.Frame(body)
        left.pack(side="left", fill="both", padx=(0, 10))
        left.pack_propagate(False)
        right.pack(side="left", fill="both", expand=True)

        master = ttk.LabelFrame(left, text="开关与排序", padding=8)
        master.pack(fill="x")
        self.energy_enabled = tk.BooleanVar(value=True)
        self.energy_use81 = tk.BooleanVar(value=True)
        self.energy_wuxing = tk.BooleanVar(value=True)
        self.energy_tiebreak = tk.BooleanVar(value=True)
        ttk.Checkbutton(master, text="启用数字能量分析（只作参考，不改变得分）",
                        variable=self.energy_enabled).pack(anchor="w", pady=2)
        ttk.Checkbutton(master, text="81 数理参与能量分",
                        variable=self.energy_use81).pack(anchor="w", pady=2)
        ttk.Checkbutton(master, text="五行齐全加分",
                        variable=self.energy_wuxing).pack(anchor="w", pady=2)
        ttk.Checkbutton(master, text="得分相同时按能量分排序",
                        variable=self.energy_tiebreak).pack(anchor="w", pady=2)
        row = ttk.Frame(master)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="排序依据：").pack(side="left")
        self.energy_sort_mode = tk.StringVar(value="规则得分")
        ttk.Combobox(row, textvariable=self.energy_sort_mode, state="readonly",
                     width=10, values=["规则得分", "能量分"]).pack(side="left")

        stars_box = ttk.LabelFrame(left, text="八星权重（只影响能量分）", padding=8)
        stars_box.pack(fill="x", pady=(10, 0))
        self.energy_star_vars: dict[str, tk.BooleanVar] = {}
        self.energy_star_weights: dict[str, tk.StringVar] = {}
        for index, star in enumerate(core.STAR_ORDER):
            row, column = index % 4, (index // 4) * 2
            variable = tk.BooleanVar(value=True)
            weight = tk.StringVar(value=str(core.STAR_LUCK[star]))
            self.energy_star_vars[star] = variable
            self.energy_star_weights[star] = weight
            ttk.Checkbutton(stars_box, text=star, variable=variable).grid(
                row=row, column=column, sticky="w", pady=2)
            ttk.Entry(stars_box, textvariable=weight, width=5).grid(
                row=row, column=column + 1, sticky="w", padx=(0, 14))

        owner_box = ttk.LabelFrame(left, text="车主信息（可选）", padding=8)
        owner_box.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(owner_box)
        row.pack(fill="x")
        ttk.Label(row, text="生日：").pack(side="left")
        self.owner_birthday = tk.StringVar(value="")
        entry = ttk.Entry(row, textvariable=self.owner_birthday, width=14)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _event: self._update_owner_info())
        ttk.Label(row, text="YYYY-MM-DD（可省略）", style="Hint.TLabel").pack(
            side="left", padx=6)
        self.owner_info_var = tk.StringVar(value="未填写：不计算与车主的五行匹配")
        ttk.Label(owner_box, textvariable=self.owner_info_var,
                  style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

        trial = ttk.LabelFrame(right, text="试算一个号码", padding=8)
        trial.pack(fill="both", expand=True)
        row = ttk.Frame(trial)
        row.pack(fill="x")
        ttk.Label(row, text="车牌 / 号码：").pack(side="left")
        self.trial_var = tk.StringVar(value="FU5N88")
        entry = ttk.Entry(row, textvariable=self.trial_var, width=16)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _event: self.run_trial())
        ttk.Button(row, text="分析", command=self.run_trial).pack(side="left", padx=6)
        self.trial_text = tk.Text(trial, height=14, width=38, wrap="word", font=BASE_FONT,
                                  bg="#fbfbfb", relief="solid", borderwidth=1)
        self.trial_text.pack(fill="both", expand=True, pady=(8, 0))

        note = ttk.LabelFrame(right, text="说明", padding=8)
        note.pack(fill="x", pady=(10, 0))
        ttk.Label(
            note, style="Hint.TLabel", justify="left", wraplength=520,
            text=("口径：八星磁场（相邻两位数字，含 0 视为无星）+ 81 数理（各位数字和）"
                  "+ 河图五行（1/6 水、2/7 火、3/8 木、4/9 金、5/0 土）。"
                  "字母不参与组合。属民俗 / 娱乐参考，不是科学结论；"
                  "开启「按能量分排序」后，列表会优先按能量分排列。"),
        ).pack(anchor="w")

        actions = ttk.Frame(parent, padding=(10, 0, 10, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="应用并重新计算", command=self.apply_rules).pack(side="left")
        self.energy_summary_var = tk.StringVar(value="")
        ttk.Label(actions, textvariable=self.energy_summary_var,
                  style="Hint.TLabel").pack(side="left", padx=10)

    def _update_owner_info(self) -> None:
        text = self.owner_birthday.get().strip()
        if not text:
            self.owner_info_var.set("未填写：不计算与车主的五行匹配")
            return
        parsed = core.parse_birthday(text)
        if not parsed:
            self.owner_info_var.set("生日格式无法识别（用 1990-05-20 或 19900520）")
            return
        year, month, day = parsed
        gan, zhi = core.day_pillar(year, month, day)
        zodiac = core.zodiac_of(year)
        self.owner_info_var.set(
            f"生肖{zodiac}（{core.ZODIAC_WUXING[zodiac]}）· 日柱{gan}{zhi} · "
            f"日主{core.GAN_WUXING[gan]}")

    def run_trial(self) -> None:
        text = self.trial_var.get().strip()
        if not text:
            return
        try:
            self._apply_ui_to_rules()
        except ValueError as exc:
            messagebox.showerror("规则不合法", str(exc))
            return
        self._update_owner_info()
        plate = core.make_plate(1, text, self.rules)
        lines = [f"号码：{plate.text}（数字部分 {plate.digits or '-'}）",
                 f"规则得分：{plate.price}（{core.format_price(plate.price)}）",
                 f"命中：{'、'.join(plate.hits) or '无'}",
                 ""]
        energy = plate.energy
        if energy:
            lines.append(f"数字能量：{energy['score']} 分（{energy['grade']}）")
            lines.append(core.format_energy_detail(energy))
            lines.append("")
            lines.extend("· " + note for note in energy["notes"])
        else:
            lines.append("数字能量分析未启用")
        self.trial_text.delete("1.0", "end")
        self.trial_text.insert("1.0", "\n".join(lines))

    def _energy_summary(self) -> str:
        energy = self.rules["energy"]
        if not energy.get("enabled"):
            return "数字能量：关"
        mode = "按能量分排序" if energy.get("sort_mode") == "energy" else "按规则得分排序"
        owner = "，含车主匹配" if energy.get("owner_birthday") else ""
        return f"数字能量：开（{mode}{owner}）"

    # ------------------------------ 页签 4 ------------------------------ #

    def _build_rules_tab(self) -> None:
        parent = self.tab_rules
        body = ttk.Frame(parent, padding=10)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right.pack(side="left", fill="both", expand=True)

        score_box = ttk.LabelFrame(left, text="命中规则与分值", padding=8)
        score_box.pack(fill="x")
        self.flag_vars: dict[str, tk.BooleanVar] = {}
        self.weight_vars: dict[str, tk.StringVar] = {}
        defaults = core.default_rules()
        for row, key in enumerate(defaults["flags"]):
            var = tk.BooleanVar(value=True)
            self.flag_vars[key] = var
            ttk.Checkbutton(score_box, text=FLAG_LABELS[key], variable=var).grid(
                row=row, column=0, sticky="w", pady=2)
            weight_var = tk.StringVar(value=str(defaults["weights"][key]))
            self.weight_vars[key] = weight_var
            ttk.Entry(score_box, textvariable=weight_var, width=16).grid(
                row=row, column=1, sticky="e", padx=(12, 0))
        score_box.columnconfigure(0, weight=1)

        detect_box = ttk.LabelFrame(left, text="识别参数", padding=8)
        detect_box.pack(fill="x", pady=(10, 0))
        self.psm_var = tk.StringVar(value="6")
        self.min_area_var = tk.StringVar(value="1000")
        self.min_aspect_var = tk.StringVar(value="2.0")
        self.pattern_var = tk.StringVar(value=r"[A-Z0-9]{5,7}")
        self.whitelist_var = tk.StringVar(
            value="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        self.tesseract_var = tk.StringVar(value="")
        fields = (
            ("PSM（6=整块，7=单行）", self.psm_var),
            ("候选最小面积", self.min_area_var),
            ("候选最小宽高比", self.min_aspect_var),
            ("车牌正则", self.pattern_var),
            ("OCR 字符白名单", self.whitelist_var),
            ("tesseract 路径", self.tesseract_var),
        )
        for row, (label, var) in enumerate(fields):
            ttk.Label(detect_box, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(detect_box, textvariable=var, width=26).grid(
                row=row, column=1, sticky="e", padx=(12, 0))
        detect_box.columnconfigure(0, weight=1)

        lucky_box = ttk.LabelFrame(right, text="幸运字符（每行一个，支持字母组合）", padding=8)
        lucky_box.pack(fill="both", expand=True)
        self.lucky_text = tk.Text(lucky_box, height=10, width=44, wrap="none", font=MONO)
        lucky_scroll = ttk.Scrollbar(lucky_box, orient="vertical",
                                     command=self.lucky_text.yview)
        self.lucky_text.configure(yscrollcommand=lucky_scroll.set)
        self.lucky_text.pack(side="left", fill="both", expand=True)
        lucky_scroll.pack(side="right", fill="y")

        unlucky_box = ttk.LabelFrame(right, text="忌讳字符（每行一个）", padding=8)
        unlucky_box.pack(fill="both", expand=True, pady=(10, 0))
        self.unlucky_text = tk.Text(unlucky_box, height=7, width=44, wrap="none", font=MONO)
        unlucky_scroll = ttk.Scrollbar(unlucky_box, orient="vertical",
                                       command=self.unlucky_text.yview)
        self.unlucky_text.configure(yscrollcommand=unlucky_scroll.set)
        self.unlucky_text.pack(side="left", fill="both", expand=True)
        unlucky_scroll.pack(side="right", fill="y")

        tail_row = ttk.Frame(right)
        tail_row.pack(fill="x", pady=(8, 0))
        ttk.Label(tail_row, text="不建议尾号（逗号分隔）：").pack(side="left")
        self.bad_tail_var = tk.StringVar(value="0, 05")
        ttk.Entry(tail_row, textvariable=self.bad_tail_var).pack(
            side="left", fill="x", expand=True)

        actions = ttk.Frame(parent, padding=(10, 0, 10, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="应用规则", command=self.apply_rules).pack(side="left")
        ttk.Button(actions, text="保存规则…", command=self.save_rules_file).pack(
            side="left", padx=6)
        ttk.Button(actions, text="载入规则…", command=self.load_rules_file).pack(side="left")
        ttk.Button(actions, text="恢复默认", command=self.reset_rules).pack(
            side="left", padx=6)
        ttk.Button(actions, text="试算一个号码…", command=self.test_score).pack(side="left")
        self.rules_summary_var = tk.StringVar(value="")
        ttk.Label(actions, textvariable=self.rules_summary_var,
                  style="Hint.TLabel").pack(side="left", padx=12)

    # ------------------------------ 页签 5 ------------------------------ #

    def _build_help_tab(self) -> None:
        parent = self.tab_help
        body = ttk.Frame(parent, padding=(10, 10, 10, 6))
        body.pack(fill="both", expand=True)

        toc_frame = ttk.Frame(body, width=180)
        toc_frame.pack(side="left", fill="y")
        toc_frame.pack_propagate(False)
        ttk.Label(toc_frame, text="目录", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        self.help_toc = tk.Listbox(toc_frame, activestyle="none", exportselection=False,
                                   font=BASE_FONT, highlightthickness=0,
                                   borderwidth=1, relief="solid")
        for title, _body in HELP_SECTIONS:
            self.help_toc.insert("end", title)
        self.help_toc.pack(fill="both", expand=True)
        self.help_toc.bind("<<ListboxSelect>>", self._jump_help)
        self.help_toc.selection_set(0)

        text_frame = ttk.Frame(body)
        text_frame.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.help_text = tk.Text(text_frame, wrap="word", font=BASE_FONT,
                                 padx=14, pady=10, relief="solid", borderwidth=1,
                                 bg="#ffffff")
        scroll = ttk.Scrollbar(text_frame, orient="vertical",
                               command=self.help_text.yview)
        self.help_text.configure(yscrollcommand=scroll.set)
        self.help_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.help_text.tag_configure(
            "h1", font=(BASE_FONT[0], BASE_FONT[1] + 3, "bold"),
            spacing1=10, spacing3=6)
        self.help_text.tag_configure("body", spacing1=2, spacing3=2,
                                     lmargin1=2, lmargin2=2)
        self.help_text.tag_configure("bullet", lmargin1=18, lmargin2=30, spacing1=2)
        self.help_text.tag_configure("code", font=MONO, lmargin1=24, lmargin2=24,
                                     spacing1=2, foreground="#333333")

        for index, (title, body_text) in enumerate(HELP_SECTIONS):
            self.help_text.mark_set(f"sec{index}", "insert")
            self.help_text.mark_gravity(f"sec{index}", "left")
            self.help_text.insert("end", title + "\n", "h1")
            for line in body_text.strip("\n").splitlines():
                stripped = line.strip()
                if not stripped:
                    self.help_text.insert("end", "\n")
                elif stripped.startswith(("·", "-", "*")):
                    self.help_text.insert("end", "  " + stripped + "\n", "bullet")
                elif line.startswith("  "):
                    self.help_text.insert("end", line.rstrip() + "\n", "code")
                else:
                    self.help_text.insert("end", stripped + "\n", "body")
            self.help_text.insert("end", "\n")
        self.help_text.configure(state="disabled")

        actions = ttk.Frame(parent, padding=(10, 0, 10, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="保存使用说明…", command=self.save_help).pack(side="left")
        ttk.Button(actions, text="关于", command=self.show_about).pack(side="left", padx=6)
        ttk.Label(actions, text="任意页签按 F1 都能回到这里",
                  style="Hint.TLabel").pack(side="left", padx=10)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", accelerator="F1", command=self.show_help)
        help_menu.add_command(label="关于", command=self.show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.root.configure(menu=menubar)

    def _jump_help(self, _event=None) -> None:
        selection = self.help_toc.curselection()
        if not selection:
            return
        try:
            self.help_text.see(f"sec{selection[0]}")
        except tk.TclError:
            pass

    def show_help(self) -> None:
        self.notebook.select(self.tab_help)
        self.help_text.focus_set()

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            f"{APP_TITLE} {APP_VERSION}\n\n"
            "从截图识别车牌、按号段批量筛选、按规则打分排序，\n"
            "并提供数字能量参考。\n\n"
            "https://github.com/yehuzai/good-car-code",
            parent=self.root)

    def save_help(self) -> str:
        path = filedialog.asksaveasfilename(
            title="保存使用说明", defaultextension=".txt",
            initialdir=self._last_dir,
            initialfile=f"车牌筛选工具_使用说明_{APP_VERSION}.txt",
            filetypes=[("文本", "*.txt"), ("全部文件", "*.*")])
        if not path:
            return ""
        lines = [f"{APP_TITLE} {APP_VERSION} 使用说明", "=" * 40, ""]
        for title, body_text in HELP_SECTIONS:
            lines.append(title)
            lines.append("-" * max(4, _display_width(title)))
            lines.extend(body_text.strip("\n").splitlines())
            lines.append("")
        try:
            core.write_text(path, "\n".join(lines) + "\n")
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
            return ""
        self._last_dir = os.path.dirname(path) or self._last_dir
        self.set_status(f"使用说明已保存：{path}")
        return path

    # ------------------------------------------------------------------ #
    # 规则 <-> 界面
    # ------------------------------------------------------------------ #

    def _load_rules_into_ui(self) -> None:
        rules = self.rules
        for key, var in self.flag_vars.items():
            var.set(bool(rules["flags"].get(key, True)))
        for key, var in self.weight_vars.items():
            var.set(str(rules["weights"].get(key, 0)))
        self.lucky_text.delete("1.0", "end")
        self.lucky_text.insert("1.0", "\n".join(rules["lucky_chars"]))
        self.unlucky_text.delete("1.0", "end")
        self.unlucky_text.insert("1.0", "\n".join(rules["unlucky_chars"]))
        self.bad_tail_var.set(", ".join(rules["bad_tail"]))
        detect = rules["detect"]
        self.psm_var.set(str(detect.get("psm", 6)))
        self.min_area_var.set(str(detect.get("min_area", 1000)))
        self.min_aspect_var.set(str(detect.get("min_aspect", 2.0)))
        self.pattern_var.set(str(detect.get("pattern", r"[A-Z0-9]{5,7}")))
        self.whitelist_var.set(str(detect.get("whitelist", "")))
        self.tesseract_var.set(str(detect.get("tesseract_cmd", "")))
        energy = rules["energy"]
        self.energy_enabled.set(bool(energy.get("enabled", True)))
        self.energy_use81.set(bool(energy.get("use_81", True)))
        self.energy_wuxing.set(bool(energy.get("wuxing_bonus", True)))
        self.energy_tiebreak.set(bool(energy.get("tie_break_energy", True)))
        self.energy_sort_mode.set(
            "能量分" if energy.get("sort_mode") == "energy" else "规则得分")
        for star, variable in self.energy_star_vars.items():
            config = (energy.get("stars") or {}).get(star) or {}
            variable.set(bool(config.get("enabled", True)))
            self.energy_star_weights[star].set(
                str(config.get("weight", core.STAR_LUCK[star])))
        self.owner_birthday.set(str(energy.get("owner_birthday", "")))
        self._update_owner_info()
        self.rules_summary_var.set(self._rules_summary())
        self.energy_summary_var.set(self._energy_summary())

    def _rules_summary(self) -> str:
        rules = self.rules
        enabled = sum(1 for v in rules["flags"].values() if v)
        energy = "开" if rules["energy"].get("enabled") else "关"
        return (f"{enabled}/6 规则 · 幸运 {len(rules['lucky_chars'])} · "
                f"忌讳 {len(rules['unlucky_chars'])} · 能量{energy}")

    def _text_lines(self, widget: tk.Text) -> list[str]:
        raw = widget.get("1.0", "end").splitlines()
        return [line.strip() for line in raw if line.strip()]

    def _apply_ui_to_rules(self) -> None:
        """把界面上的内容读回 self.rules，非法输入会抛 ValueError。"""
        rules = core.default_rules()
        for key, var in self.flag_vars.items():
            rules["flags"][key] = bool(var.get())
        for key, var in self.weight_vars.items():
            rules["weights"][key] = core.parse_weight(var.get(), rules["weights"][key])
        rules["lucky_chars"] = self._text_lines(self.lucky_text)
        rules["unlucky_chars"] = self._text_lines(self.unlucky_text)
        rules["bad_tail"] = [t.strip() for t in self.bad_tail_var.get().replace("，", ",").split(",")
                             if t.strip()]
        rules["detect"] = {
            "min_area": int(float(self.min_area_var.get())),
            "min_aspect": float(self.min_aspect_var.get()),
            "psm": int(float(self.psm_var.get())),
            "whitelist": self.whitelist_var.get().strip(),
            "pattern": self.pattern_var.get().strip() or r"[A-Z0-9]{5,7}",
            "tesseract_cmd": self.tesseract_var.get().strip(),
        }
        rules["energy"] = {
            "enabled": bool(self.energy_enabled.get()),
            "use_81": bool(self.energy_use81.get()),
            "wuxing_bonus": bool(self.energy_wuxing.get()),
            "tie_break_energy": bool(self.energy_tiebreak.get()),
            "sort_mode": "energy" if self.energy_sort_mode.get() == "能量分" else "score",
            "owner_birthday": self.owner_birthday.get().strip(),
            "stars": {},
        }
        for star, variable in self.energy_star_vars.items():
            weight_text = self.energy_star_weights[star].get().strip()
            rules["energy"]["stars"][star] = {
                "enabled": bool(variable.get()),
                "weight": core.parse_weight(weight_text, core.STAR_LUCK[star]),
            }
        self.rules = core.normalize_rules(rules)

    def apply_rules(self) -> None:
        try:
            self._apply_ui_to_rules()
        except ValueError as exc:
            messagebox.showerror("规则不合法", str(exc))
            return
        self.rules_summary_var.set(self._rules_summary())
        self.energy_summary_var.set(self._energy_summary())
        self._update_owner_info()
        updated = []
        if self.image_plates:
            self.image_plates = core.rescore(self.image_plates, self.rules)
            self.annotated = core.annotate_image(self.image, self.image_plates)
            self._fill_tree(self.image_tree, self.image_plates)
            self.render_preview()
            updated.append("图片结果")
        if self.segment_plates:
            self.segment_plates = core.rescore(self.segment_plates, self.rules)
            self.refresh_segment_tree()
            updated.append("号段结果")
        if updated:
            self.set_status(f"规则已应用，已重新计算：{'、'.join(updated)}")
        else:
            self.set_status("规则已应用（对下一次识别/评估生效）")

    def reset_rules(self) -> None:
        if not messagebox.askyesno("恢复默认", "确定把当前规则恢复成默认值？"):
            return
        self.rules = core.default_rules()
        self._load_rules_into_ui()
        self.set_status("已恢复默认规则")

    def save_rules_file(self) -> None:
        try:
            self._apply_ui_to_rules()
        except ValueError as exc:
            messagebox.showerror("规则不合法", str(exc))
            return
        path = filedialog.asksaveasfilename(
            title="保存规则", defaultextension=".json", initialdir=self._last_dir,
            initialfile="plate_rules.json", filetypes=[("JSON 规则", "*.json")])
        if not path:
            return
        core.save_rules(path, self.rules)
        self.rules_path = path
        self.set_status(f"规则已保存：{path}")

    def load_rules_file(self) -> None:
        path = filedialog.askopenfilename(
            title="载入规则", initialdir=self._last_dir,
            filetypes=[("JSON 规则", "*.json"), ("全部文件", "*.*")])
        if not path:
            return
        try:
            self.rules = core.load_rules(path)
        except Exception as exc:
            messagebox.showerror("载入失败", str(exc))
            return
        self.rules_path = path
        self._load_rules_into_ui()
        self.set_status(f"规则已载入：{path}")

    def test_score(self) -> None:
        value = simpledialog.askstring("试算号码", "输入一个车牌（如 FU5N88）：",
                                       parent=self.root)
        if not value:
            return
        try:
            self._apply_ui_to_rules()
        except ValueError as exc:
            messagebox.showerror("规则不合法", str(exc))
            return
        plate = core.make_plate(1, value, self.rules)
        hits = "、".join(plate.hits) or "无"
        messagebox.showinfo(
            "试算结果",
            f"号码：{plate.text}\n数字部分：{plate.digits or '-'}\n"
            f"得分：{plate.price}（{core.format_price(plate.price)}）\n命中：{hits}")

    def _read_detect_params(self) -> core.DetectParams:
        self._apply_ui_to_rules()
        return core.DetectParams.from_rules(self.rules)

    # ------------------------------------------------------------------ #
    # 页签 1：图片识别
    # ------------------------------------------------------------------ #

    def choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择图片", initialdir=self._last_dir,
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                       ("全部文件", "*.*")])
        if not path:
            return
        try:
            image = core.load_image(path)
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        self._last_dir = os.path.dirname(path) or self._last_dir
        self.image = image
        self.image_path = path
        self.annotated = None
        self.image_plates = []
        self._plates_by_index = {}
        self.image_tree.delete(*self.image_tree.get_children())
        self.image_var.set(f"{path}   ({image.shape[1]}x{image.shape[0]})")
        self.zoom_canvas.delete("all")
        self.render_preview()
        self.set_status("图片已载入，点“开始识别”提取车牌")

    def clear_image(self) -> None:
        self.image = None
        self.image_path = ""
        self.annotated = None
        self.image_plates = []
        self._plates_by_index = {}
        self.image_tree.delete(*self.image_tree.get_children())
        self.zoom_canvas.delete("all")
        self.image_var.set("尚未选择图片")
        self.render_preview()
        self.set_status("已清除图片")

    def run_detect(self) -> None:
        if self.image is None:
            messagebox.showinfo("提示", "请先选择一张图片")
            return
        try:
            params = self._read_detect_params()
        except ValueError as exc:
            messagebox.showerror("识别参数不合法", str(exc))
            return
        image = self.image
        rules = self.rules
        logs: list[str] = []
        self._pending_logs = logs

        def job():
            core.configure_tesseract(params.tesseract_cmd)
            return core.detect_plates(image, rules, params, log=logs.append)

        self._start_work(job, self.on_detect_done, "正在识别车牌…")

    def on_detect_done(self, result) -> None:
        if isinstance(result, Exception):
            messagebox.showerror("识别失败", str(result))
            self.set_status("识别失败")
            return
        plates, annotated = result
        self.image_plates = plates
        self.annotated = annotated
        self._plates_by_index = {plate.index: plate for plate in plates}
        self._fill_tree(self.image_tree, plates, limit=None)
        self.render_preview()
        self.zoom_canvas.delete("all")
        if plates:
            best = core.sort_plates(plates)[0]
            self.set_status(f"识别到 {len(plates)} 个号码，最佳 {best.text}"
                            f"（{core.format_price(best.price)}）")
        else:
            tail = self._pending_logs[-1] if self._pending_logs else ""
            self.set_status(f"没有识别到符合规则的号码。{tail}")

    def on_image_select(self, _event=None) -> None:
        selection = self.image_tree.selection()
        canvas = self.zoom_canvas
        canvas.delete("all")
        if not selection or self.image is None:
            return
        plate = self._tree_plate_map.get(self.image_tree, {}).get(selection[0])
        if plate is None or not plate.box:
            return
        try:
            crop = core.zoom_region(self.image, plate.box, scale=1.0, margin=10)
        except ValueError:
            return
        width = max(canvas.winfo_width() - 8, 60)
        height = max(canvas.winfo_height() - 8, 60)
        fitted = _fit(crop, width, height, allow_upscale=True)
        self._zoom_photo = ImageTk.PhotoImage(
            Image.fromarray(core.bgr_to_rgb(fitted)))
        canvas.create_image(canvas.winfo_width() / 2, canvas.winfo_height() / 2,
                            image=self._zoom_photo)
        canvas.create_text(
            8, 8, anchor="nw", fill="#dddddd",
            text=(f"{plate.text}  得分 {core.format_price(plate.price)}"
                  f"  能量 {core.format_energy(plate.energy)}"))

    def render_preview(self) -> None:
        canvas = self.preview_canvas
        canvas.delete("all")
        image = self.image
        if self.show_annot.get() and self.annotated is not None:
            image = self.annotated
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if image is None:
            canvas.create_text(max(width, 200) / 2, max(height, 200) / 2,
                               text="点击左上角“选择图片…”开始",
                               fill="#8a8a92", font=(BASE_FONT[0], BASE_FONT[1] + 1))
            return
        fitted = _fit(image, max(width - 12, 80), max(height - 12, 80))
        self._photo = ImageTk.PhotoImage(Image.fromarray(core.bgr_to_rgb(fitted)))
        canvas.create_image(width / 2, height / 2, image=self._photo)

    def _on_preview_resize(self, _event=None) -> None:
        if self._render_job is not None:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(80, self._render_preview_now)

    def _render_preview_now(self) -> None:
        self._render_job = None
        self.render_preview()

    def save_annotated(self) -> None:
        if self.annotated is None:
            messagebox.showinfo("提示", "请先识别图片")
            return
        default_name = "标注图.png"
        if self.image_path:
            stem = os.path.splitext(os.path.basename(self.image_path))[0]
            default_name = f"{stem}_标注.png"
        path = filedialog.asksaveasfilename(
            title="保存标注图", defaultextension=".png", initialdir=self._last_dir,
            initialfile=default_name,
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg")])
        if not path:
            return
        try:
            core.save_image(path, self.annotated)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self._last_dir = os.path.dirname(path) or self._last_dir
        self.set_status(f"标注图已保存：{path}")

    def report_for_image(self) -> None:
        if not self.image_plates:
            messagebox.showinfo("提示", "还没有识别结果")
            return
        text = core.build_report(
            "车牌筛选报告（图片识别）",
            self.image_path or "（未记录来源）",
            self.image_plates,
            extra_lines=[f"图片尺寸：{self.image.shape[1]}x{self.image.shape[0]}"]
            if self.image is not None else (),
            top_n=10,
            rules=self.rules,
        )
        self.show_report_window(text, core.suggest_name("车牌报告_识别"))

    def csv_for_image(self) -> None:
        if not self.image_plates:
            messagebox.showinfo("提示", "还没有识别结果")
            return
        self._save_csv(self.image_plates, "车牌结果_识别")

    # ------------------------------------------------------------------ #
    # 页签 2：号段筛选
    # ------------------------------------------------------------------ #

    def preview_segment_count(self) -> None:
        lines = self.segment_text.get("1.0", "end").splitlines()
        try:
            numbers = core.expand_segments(lines)
        except ValueError as exc:
            self.segment_count_var.set(f"解析失败：{exc}")
            return
        self.segment_count_var.set(f"共解析出 {len(numbers)} 个号码")

    def load_segments_file(self) -> None:
        path = filedialog.askopenfilename(
            title="载入号段文件", initialdir=self._last_dir,
            filetypes=[("文本", "*.txt *.csv"), ("全部文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="gbk", errors="ignore") as handle:
                content = handle.read()
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        self._last_dir = os.path.dirname(path) or self._last_dir
        self.segment_text.delete("1.0", "end")
        self.segment_text.insert("1.0", content)
        self.preview_segment_count()

    def run_segments(self) -> None:
        lines = self.segment_text.get("1.0", "end").splitlines()
        rules = self.rules
        try:
            self._apply_ui_to_rules()
            rules = self.rules
        except ValueError as exc:
            messagebox.showerror("规则不合法", str(exc))
            return

        def job():
            numbers = core.expand_segments(lines)
            if not numbers:
                raise ValueError("没有解析到任何号段，请检查输入格式")
            return numbers, core.build_plates(numbers, rules)

        self._start_work(job, self.on_segments_done, "正在评估号段…")

    def on_segments_done(self, result) -> None:
        if isinstance(result, Exception):
            messagebox.showerror("评估失败", str(result))
            self.set_status("评估失败")
            return
        numbers, plates = result
        self.segment_numbers = numbers
        self.segment_plates = plates
        self.refresh_segment_tree()
        self.set_status(f"共 {len(numbers)} 个号码，最佳 {plates[0].text}"
                        f"（{core.format_price(plates[0].price)}）")

    def refresh_segment_tree(self) -> None:
        limit_text = self.display_limit.get()
        limit = None
        if limit_text != "全部":
            try:
                limit = int(limit_text.replace("前", "").strip())
            except ValueError:
                limit = None
        self._fill_tree(self.segment_tree, self.segment_plates, limit)
        if self.segment_plates:
            total = len(self.segment_plates)
            shown = total if limit is None else min(limit, total)
            self.segment_summary_var.set(
                f"共 {total} 个号码，显示前 {shown} 个")
        else:
            self.segment_summary_var.set("尚未评估")

    def on_segment_select(self, _event=None) -> None:
        selection = self.segment_tree.selection()
        if not selection:
            self.segment_detail_var.set(
                "选中一行查看八星 / 五行 / 81 数理详情（在“数字能量”页签可关闭）")
            return
        plate = self._tree_plate_map.get(self.segment_tree, {}).get(selection[0])
        if plate is None:
            return
        if not plate.energy:
            self.segment_detail_var.set(f"{plate.text}：数字能量分析未启用")
            return
        detail = core.format_energy_detail(plate.energy)
        first_note = plate.energy["notes"][0] if plate.energy["notes"] else ""
        self.segment_detail_var.set(f"{plate.text} ｜ {detail}\n{first_note}")

    def report_for_segments(self) -> None:
        if not self.segment_plates:
            messagebox.showinfo("提示", "还没有评估结果")
            return
        lines = [f"号段数：{self._segment_line_count()}，"
                 f"展开号码数：{len(self.segment_numbers)}"]
        text = core.build_report(
            "车牌筛选报告（号段筛选）",
            "号段列表（见下）",
            self.segment_plates,
            extra_lines=lines + ["", "【号段明细】"] +
            [f"  {line.strip()}" for line in
             self.segment_text.get("1.0", "end").splitlines() if line.strip()],
            top_n=20,
            rules=self.rules,
        )
        self.show_report_window(text, core.suggest_name("车牌报告_号段"))

    def csv_for_segments(self) -> None:
        if not self.segment_plates:
            messagebox.showinfo("提示", "还没有评估结果")
            return
        self._save_csv(self.segment_plates, "车牌结果_号段")

    def _segment_line_count(self) -> int:
        count = 0
        for line in self.segment_text.get("1.0", "end").splitlines():
            if line.strip() and not line.strip().startswith("#"):
                count += 1
        return count

    # ------------------------------------------------------------------ #
    # 公共部分
    # ------------------------------------------------------------------ #

    def _fill_tree(self, tree: ttk.Treeview, plates, limit=None) -> None:
        tree.delete(*tree.get_children())
        ordered = core.sort_plates(plates, core.sort_mode(self.rules))
        if limit is not None:
            ordered = ordered[:limit]
        mapping: dict[str, core.Plate] = {}
        for rank, plate in enumerate(ordered, start=1):
            hits = "、".join(plate.hits)
            if len(hits) > 40:
                hits = hits[:40] + "…"
            item = str(plate.index)
            mapping[item] = plate
            tree.insert("", "end", iid=str(plate.index),
                        values=(rank, plate.text, plate.digits or "-",
                                core.format_price(plate.price),
                                core.format_energy(plate.energy), hits or "-"))
        self._tree_plate_map[tree] = mapping

    def _save_csv(self, plates, prefix: str) -> None:
        path = filedialog.asksaveasfilename(
            title="导出 CSV", defaultextension=".csv", initialdir=self._last_dir,
            initialfile=core.suggest_name(prefix, ".csv"),
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            core.write_csv(path, plates, core.sort_mode(self.rules))
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self._last_dir = os.path.dirname(path) or self._last_dir
        self.set_status(f"CSV 已导出：{path}")

    def show_report_window(self, text: str, suggested_name: str) -> None:
        window = tk.Toplevel(self.root)
        window.title("文本报告预览")
        window.geometry("820x600")
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        text_widget = tk.Text(frame, wrap="none", font=MONO)
        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=text_widget.yview)
        scroll_x = ttk.Scrollbar(frame, orient="horizontal", command=text_widget.xview)
        text_widget.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        text_widget.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        text_widget.insert("1.0", text)

        buttons = ttk.Frame(window, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")

        def save() -> None:
            path = filedialog.asksaveasfilename(
                title="保存文本报告", defaultextension=".txt",
                initialdir=self._last_dir, initialfile=suggested_name,
                filetypes=[("文本报告", "*.txt"), ("全部文件", "*.*")])
            if not path:
                return
            try:
                core.write_text(path, text)
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc))
                return
            self._last_dir = os.path.dirname(path) or self._last_dir
            self.set_status(f"报告已保存：{path}")
            window.destroy()

        def copy() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.set_status("报告已复制到剪贴板")

        ttk.Button(buttons, text="保存为文件…", command=save).pack(side="left")
        ttk.Button(buttons, text="复制到剪贴板", command=copy).pack(side="left", padx=6)
        ttk.Button(buttons, text="关闭", command=window.destroy).pack(side="right")

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    # ------------------------------------------------------------------ #
    # 后台任务
    # ------------------------------------------------------------------ #

    def _start_work(self, job, on_done, message: str) -> None:
        if self._busy:
            messagebox.showinfo("请稍候", "还有一个任务在执行中")
            return
        self._busy = True
        self.set_status(message)
        self.progress.start(12)
        self._set_buttons(enabled=False)

        def runner() -> None:
            try:
                result = job()
            except BaseException as exc:  # noqa: BLE001 - 统一回抛到 UI 线程
                result = exc
            self._queue.put((on_done, result))

        threading.Thread(target=runner, daemon=True).start()

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.detect_button, self.segment_button):
            button.configure(state=state)

    def _poll_queue(self) -> None:
        try:
            while True:
                callback, result = self._queue.get_nowait()
                self._busy = False
                self.progress.stop()
                self._set_buttons(enabled=True)
                callback(result)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)


def build_app() -> tk.Tk:
    """建好主窗口，返回 root（--selftest 之外都走这里）。"""
    root = tk.Tk()
    PlateApp(root)
    root.update_idletasks()
    # 默认 1240x800，但不超过屏幕，否则内容会被裁掉
    width = max(1100, min(1240, root.winfo_screenwidth() - 80))
    height = max(700, min(800, root.winfo_screenheight() - 140))
    root.minsize(min(1100, width), min(700, height))
    root.geometry(f"{width}x{height}")
    return root


def selftest(argv: list[str]) -> int:
    """无界面跑一遍：打分 -> 号段 -> tesseract -> OCR -> 报告。

    Windows 的窗口版 exe 没有控制台，所以支持 PLATE_SELFTEST_LOG 把过程写到文件。
    """
    require_bundled = "--require-bundled" in argv
    log_path = os.environ.get("PLATE_SELFTEST_LOG", "")
    buffer: list[str] = []

    def say(message: str = "") -> None:
        buffer.append(message)
        try:
            print(message, flush=True)
        except Exception:
            # Windows 控制台可能是 cp1252，打不出中文；日志文件才是权威输出
            pass

    try:
        return _selftest_body(say, require_bundled)
    except BaseException as exc:  # noqa: BLE001
        # 不能把异常抛出去：窗口版产物弹窗会卡住 CI
        say(f"失败：{type(exc).__name__}: {exc}")
        return 1
    finally:
        if log_path:
            try:
                core.write_text(log_path, "\n".join(buffer) + "\n")
            except OSError:
                pass


def _selftest_body(say, require_bundled: bool) -> int:
    say(f"车牌筛选工具 {APP_VERSION} 自检")

    assert HELP_SECTIONS and all(title and body for title, body in HELP_SECTIONS), \
        "内置使用说明有空章节"
    say(f"      内置使用说明：{len(HELP_SECTIONS)} 个章节")

    say("[1/6] 规则与打分")
    rules = core.default_rules()
    baseline = {"FU5N88": 190_000_000, "FR0H68": 200_000_000,
                "FX8X00": 199_000_000, "FU5N05": -11_000_000}
    for text, expected in baseline.items():
        price, hits = core.score_plate(text, rules)
        assert price == expected, f"{text} 得分 {price}，期望 {expected}"
        say(f"      {text} -> {core.format_price(price)}"
            f"（{'、'.join(hits) if hits else '无命中'}）")

    say("[2/6] 数字能量（八星 / 81 数理 / 五行）")
    # 与 perfect-numbers-app 的 core.py 对过：同口径下分数完全一致
    energy_baseline = {
        "588": (69, "中平", 1, 0, 21, "吉"),
        "1313": (77, "偏吉", 3, 0, 8, "吉"),
        "88888": (51, "偏凶", 4, 0, 40, "凶"),
    }
    for text, (score, grade, good, bad, n81, luck81) in energy_baseline.items():
        energy = core.energy_analysis(text, rules)
        assert energy["score"] == score, f"{text} 能量分 {energy['score']}，期望 {score}"
        assert energy["grade"] == grade, f"{text} 等级 {energy['grade']}，期望 {grade}"
        assert (energy["good"], energy["bad"]) == (good, bad), f"{text} 吉凶组数不符"
        assert (energy["n81"], energy["luck81"]) == (n81, luck81), f"{text} 81 数理不符"
        say(f"      {text} -> {energy['score']} 分（{grade}），"
            f"吉 {good} / 凶 {bad}，81 数理 {n81}{luck81}")
    disabled = core.default_rules()
    disabled["energy"]["enabled"] = False
    assert core.energy_analysis("588", disabled) is None, "关闭后不应返回能量结果"
    say("      关闭开关后不计算：ok")

    say("[3/6] 号段展开")
    numbers = core.expand_segments(["# 注释行", "FU5N00-FU5N03", "FR0H98-FR0H99"])
    assert numbers == ["FU5N00", "FU5N01", "FU5N02", "FU5N03", "FR0H98", "FR0H99"], numbers
    ranked = core.build_plates(numbers, rules)
    assert ranked and ranked[0].price >= ranked[-1].price
    by_energy = core.build_plates(numbers, {**rules,
                                            "energy": {**rules["energy"],
                                                       "sort_mode": "energy"}})
    assert by_energy[0].energy["score"] >= by_energy[-1].energy["score"]
    say(f"      {len(numbers)} 个号码，最佳 {ranked[0].text}"
        f"（{core.format_price(ranked[0].price)}）")
    say(f"      按能量排序最佳 {by_energy[0].text}"
        f"（{by_energy[0].energy['score']} 分）")

    say("[4/6] tesseract")
    exe, source = core.configure_tesseract(bundled_only=require_bundled)
    say(f"      {exe}（来源：{source}）")
    if core.tessdata_dir():
        say(f"      tessdata：{core.tessdata_dir()}")
    say(f"      版本：{core.tesseract_version(exe)}")

    say("[5/6] OCR 识别")
    params = core.DetectParams.from_rules(rules)
    sample = core.make_sample_plate_image("FU5N88")
    text = core.ocr_crop(sample, params)
    say(f"      合成样本 OCR：{text!r}")
    assert len(text) >= 4, f"OCR 没有返回可用结果：{text!r}"
    plates, annotated = core.detect_plates(sample, rules, params)
    say(f"      整图识别到 {len(plates)} 个号码：{[p.text for p in plates]}")
    assert annotated.shape == sample.shape, "标注图尺寸不对"
    assert plates, "合成样本上没识别到任何号码"

    say("[6/6] 文本报告")
    out_dir = tempfile.mkdtemp(prefix="plate_selftest_")
    text_path = os.path.join(out_dir, "report.txt")
    csv_path = os.path.join(out_dir, "plates.csv")
    report_text = core.build_report("自检报告", "合成样本", ranked, rules=rules)
    assert "【数字能量参考" in report_text, "报告里没有数字能量段落"
    core.write_text(text_path, report_text)
    core.write_csv(csv_path, ranked)
    for path in (text_path, csv_path):
        assert os.path.getsize(path) > 0, f"{path} 是空文件"
    say(f"      {text_path}（{os.path.getsize(text_path)} 字节）")
    say(f"      {csv_path}（{os.path.getsize(csv_path)} 字节）")

    say("ok")
    return 0


def main() -> int:
    # Windows 控制台默认不是 UTF-8，先切一下，免得中文输出直接抛异常
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest(args)
    try:
        build_app().mainloop()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
