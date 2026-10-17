# 车牌筛选工具

一句话说明这个 app 做什么。

## 直接使用

**macOS**：双击 `GoodCarCode.app`。首次打开若被 Gatekeeper 拦，右键点 app →「打开」，或

```bash
xattr -dr com.apple.quarantine /path/to/GoodCarCode.app
```

**Windows**：双击 `GoodCarCode.exe`（单文件，免安装）。被 SmartScreen 拦时点
「更多信息」→「仍要运行」。

## 从源码运行 / 重新打包

需要 Python 3.9+ 且带 tkinter。

```bash
pip install -r requirements.txt
python app.py                    # 直接运行
python app.py --selftest         # 无界面自检
```

打包：mac 上 `bash build_macos.sh`；Windows 上运行 `build_windows.bat`。
PyInstaller 不能跨系统打包，`.exe` 必须在 Windows 机器或 CI 上生成。

## 说明

- 开发约定见 `AGENTS.md`。
- 发布说明见 `NOTES.md`。
