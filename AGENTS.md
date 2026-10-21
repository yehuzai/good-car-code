# AGENTS.md

车牌筛选工具：从图片识别车牌、按号段批量筛选、按规则打分并出报告。使用者通常不懂
代码，改动要保守：规则分值、命中口径、报告的既有格式都不要随手改。

## 文件分工

- `app.py`：Tkinter 界面 + 打包入口；带 `--selftest` 可无界面跑完整流程
- `core.py`：全部可测试的逻辑（不依赖界面）
- `build_macos.sh`、`build_windows.bat`：PyInstaller 打包（会把 tesseract 一起打包）
- `.github/workflows/build.yml`：push 到 main 自动构建 mac / windows 产物，并跑自检

## 硬性约束

- 绝不提交用户数据：`*.xlsx`、`*.csv`、`*报告*.txt` 已在 `.gitignore` 里挡住。
- 不提交构建产物：`*.app/`、`build/`、`dist/`、`.venv/`、`.tesseract-bundle/` 都已忽略。
- PyInstaller 不能跨系统打包：mac 上只能出 `.app`，`.exe` 必须靠 Windows 机器或 CI。
- macOS 产物是 arm64（Apple 芯片）；Intel Mac 需要自行打包。
- 识别依赖外部的 `tesseract`：打包脚本把它和 `tessdata`（只带 eng/osd）放进产物，
  `core.find_tesseract()` 按「指定路径 → 随包分发 → 系统 PATH → 常见安装位置」查找。
  改动这段查找逻辑后，必须用 `--selftest --require-bundled` 验证随包那一路仍然可用。
- `core.score_plate()` 的分值口径有自检基线（`app.py` 里的 `baseline`），改规则要同步改它。
- 数字能量（`core.energy_analysis()`：八星磁场 / 81 数理 / 河图五行）默认**只展示**，
  不参与 `price`；不要偷偷把能量分并进“得分”。它的口径与同作者的
  `~/Documents/perfect-numbers-app` 对齐，改动后要同步 `app.py` 的 `energy_baseline`
  并与那边对数。要参与排序只能通过 `energy.sort_mode = "energy"`。
- 数字能量属于民俗 / 娱乐参考，界面上不能写成确定性结论。

## 改完必须验证

```bash
python app.py --selftest                       # 逻辑 + OCR + 报告
bash build_macos.sh                            # 本地打包
dist/GoodCarCode.app/Contents/MacOS/GoodCarCode --selftest --require-bundled
```

改界面时至少确认窗口能起来，且 `winfo_reqwidth/reqheight` 不超过设定的 geometry，
否则内容会被裁掉。

## 发布

push 到 main 只构建 + 自检，出两个 artifact（需要登录且 90 天过期）。对外发布走 tag：

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
```

tag 触发 `release` job：下载两个产物 → 用 `ditto -c -k --keepParent` 打的 mac zip →
把 SHA-256 追加进 NOTES.md → 创建 Release。别手动上传，本地到 GitHub 的上传带宽很窄。
