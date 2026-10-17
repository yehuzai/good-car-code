# AGENTS.md

车牌筛选工具：一句话项目定位。使用者通常不懂代码，改动要保守。

## 文件分工

- `app.py`：Tkinter 界面 + 打包入口；带 `--selftest` 可无界面跑完整流程
- `core.py`：全部可测试的逻辑（不要依赖界面）
- `build_macos.sh`、`build_windows.bat`：PyInstaller 打包
- `.github/workflows/build.yml`：push 到 main 自动构建 mac / windows 产物

## 硬性约束

- 绝不提交用户数据：`.gitignore` 已挡常见表格/CSV，按项目补充。
- 不提交构建产物：`*.app/`、`build/`、`dist/`、`.venv/` 都已忽略。
- PyInstaller 不能跨系统打包：mac 上只能出 `.app`，`.exe` 必须靠 Windows 机器或 CI。
- macOS 产物是 arm64（Apple 芯片）；Intel Mac 需要自行打包。

## 改完必须验证

```bash
python app.py --selftest
```

改界面时至少确认窗口能起来，且 `winfo_reqwidth/reqheight` 不超过设定的 geometry，
否则内容会被裁掉。

## 发布

push 到 main 后 CI 会自动出两个 artifact，但 artifact 需要登录且 90 天过期。
对外发用 Release（mac 的 zip 用 `ditto -c -k --keepParent GoodCarCode.app out.zip`
打，这样才保得住 app 的可执行权限）：

```bash
gh release create vX.Y.Z --repo <owner>/good-car-code --notes-file NOTES.md \
  GoodCarCode-macos.zip GoodCarCode.exe
```
