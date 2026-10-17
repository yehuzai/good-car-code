"""Pure logic for 车牌筛选工具.

Keep everything testable without a GUI here so `app.py --selftest` and the
build pipeline can exercise it headlessly. Replace `process` with the real
feature; return something JSON-able / printable.
"""


def process(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return {"lines": len(lines), "chars": len(text)}
