把车牌筛选工具打包成 macOS 和 Windows 都能直接双击运行的版本，识别用的
tesseract 已经一起打包，目标机器不用装任何东西。

## 下载哪个

| 系统 | 文件 | 用法 |
| --- | --- | --- |
| macOS（Apple 芯片 / M 系列） | `GoodCarCode-macos.zip` | 解压后得到 `GoodCarCode.app`，双击运行 |
| Windows 64 位 | `GoodCarCode.exe` | 直接双击，免安装 |

Intel 芯片的 Mac 用不了这个 `.app`（只打了 arm64），需要自己 `bash build_macos.sh`。

## 首次打开被系统拦截怎么办

- macOS：未做苹果签名/公证。提示「来自身份不明的开发者」时，右键点 app →「打开」，
  或先在终端跑 `xattr -dr com.apple.quarantine GoodCarCode.app`。
- Windows：SmartScreen 拦截时点「更多信息」→「仍要运行」。

## 怎么用

1. 「图片识别」页签：选一张车牌截图 → 开始识别 → 结果按得分排序，点一行看局部放大。
2. 「号段筛选」页签：每行写一个号段（如 `FU5N00-FU5N99`）→ 开始评估。
3. 「规则与设置」页签：改规则和分值，可存成 JSON；改完点「应用规则」。
4. 任一页签都能「生成文本报告」（可保存为 txt）或「导出 CSV」。

## 校验下载是否完整（SHA-256）

```
<macos zip 的 sha256>  GoodCarCode-macos.zip
<exe 的 sha256>  GoodCarCode.exe
```
