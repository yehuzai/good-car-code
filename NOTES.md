把 车牌筛选工具 打包成 macOS 和 Windows 都能直接双击运行的版本，目标机器不用装任何东西。

## 下载哪个

| 系统 | 文件 | 用法 |
| --- | --- | --- |
| macOS（Apple 芯片 / M 系列） | `GoodCarCode-macos.zip` | 解压后得到 `GoodCarCode.app`，双击运行 |
| Windows 64 位 | `GoodCarCode.exe` | 直接双击，免安装 |

## 首次打开被系统拦截怎么办

- macOS：未做苹果签名/公证。提示「来自身份不明的开发者」时，右键点 app →「打开」，
  或先在终端跑 `xattr -dr com.apple.quarantine GoodCarCode.app`。
- Windows：SmartScreen 拦截时点「更多信息」→「仍要运行」。

## 校验下载是否完整（SHA-256）

```
<macos zip 的 sha256>  GoodCarCode-macos.zip
<exe 的 sha256>  GoodCarCode.exe
```
