#!/usr/bin/env python3
"""车牌筛选工具 - desktop app.

Replace the sample feature in core.py with the real logic; this file is the
Tkinter UI plus a headless entry point. Keeping a `--selftest` mode lets CI and
the build pipeline verify the app with no display.

Headless self-test (no window):
    python app.py --selftest
"""

import os
import queue
import sys
import threading
import traceback

import core

APP_TITLE = "车牌筛选工具"

if sys.platform == "darwin":
    BASE_FONT = ("PingFang SC", 13)
    MONO = ("Menlo", 12)
elif os.name == "nt":
    BASE_FONT = ("Microsoft YaHei UI", 10)
    MONO = ("Consolas", 10)
else:
    BASE_FONT = ("Sans", 10)
    MONO = ("Monospace", 10)


def run_job(text, log):
    """Do the work; log progress via `log(str)`. Replace with the real feature."""
    log("开始")
    result = core.process(text or "")
    log("结果：" + str(result))
    return result


def build_app():
    from tkinter import ttk
    import tkinter as tk

    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(560, 420)

    style = ttk.Style(root)
    style.configure(".", font=BASE_FONT)
    style.configure("Title.TLabel", font=(BASE_FONT[0], BASE_FONT[1] + 5, "bold"))
    style.configure("Hint.TLabel", foreground="#667085")

    app = {"busy": False, "q": queue.Queue()}

    outer = ttk.Frame(root, padding=16)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")

    inp = tk.Text(outer, height=8, font=MONO, relief="solid", borderwidth=1)
    inp.pack(fill="both", expand=True, pady=10)

    act = ttk.Frame(outer)
    act.pack(fill="x")
    run_btn = ttk.Button(act, text="开始")
    run_btn.pack(side="left")
    status = ttk.Label(act, text="就绪", style="Hint.TLabel")
    status.pack(side="left", padx=10)

    logbox = tk.Text(outer, height=6, font=MONO, state="disabled", relief="solid",
                     borderwidth=1, background="#ffffff")
    logbox.pack(fill="both", expand=True, pady=(10, 0))

    def log(line):
        app["q"].put(("log", line))

    def drain():
        try:
            while True:
                kind, payload = app["q"].get_nowait()
                if kind == "log":
                    logbox.configure(state="normal")
                    logbox.insert("end", payload + "\n")
                    logbox.see("end")
                    logbox.configure(state="disabled")
                elif kind == "status":
                    status.configure(text=payload)
                elif kind == "done":
                    run_btn.configure(state="normal")
                    app["busy"] = False
        except queue.Empty:
            pass
        root.after(100, drain)

    def start():
        if app["busy"]:
            return
        app["busy"] = True
        run_btn.configure(state="disabled")
        status.configure(text="处理中...")
        text = inp.get("1.0", "end")

        def worker():
            try:
                run_job(text, log)
                app["q"].put(("status", "完成"))
            except Exception as exc:  # noqa: BLE001
                log("出错：" + str(exc))
                app["q"].put(("status", "失败"))
            app["q"].put(("done", True))

        threading.Thread(target=worker, daemon=True).start()

    run_btn.configure(command=start)

    root.update_idletasks()
    w = min(root.winfo_reqwidth() + 20, root.winfo_screenwidth() - 60)
    h = min(root.winfo_reqheight() + 10, root.winfo_screenheight() - 140)
    root.geometry("%dx%d" % (max(560, w), max(420, h)))

    drain()
    return root


def selftest(argv):
    result = run_job("selftest input", lambda s: print("  " + s))
    assert result is not None
    print("ok")
    return 0


def main():
    if "--selftest" in sys.argv:
        return selftest(sys.argv[2:])
    try:
        build_app().mainloop()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
