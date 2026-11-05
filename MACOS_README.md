# sjtu场地助手 · Mac 版

本工程包含与 Windows 最新版相同的蹲场界面、健身房页签校验、任选一段/连续两段、微信通知功能。
当前交付的是 Mac 构建工程，不是已经生成并验证的 DMG。

## 在 Mac 生成 DMG

1. 将整个 `sjtu场地助手-Mac构建工程` 文件夹解压到 Mac 的可写目录。
2. 构建机需安装 python.org 发行的 Python 3.11 或以上版本（带 Tk，推荐3.12/3.13），并能访问 Python 包与 Playwright 浏览器下载服务。
3. 双击 `一键生成DMG.command`。若解压工具未保留执行权限，可在终端输入 `bash `，把该文件拖入终端，再按回车。
4. 脚本在本工程建立 `.venv-mac`，安装依赖并下载 Mac 版 Chromium，再生成应用、执行启动自检、检查签名，最后生成并校验 DMG。
5. 成品位于 `releases/SJTU-Booking-macOS-arm64.dmg`（Apple芯片）或 `releases/SJTU-Booking-macOS-x86_64.dmg`（Intel）。

Apple芯片和Intel需分别在对应架构的 Mac/Python 环境中构建。不会把 Windows exe 或浏览器放进 DMG。
当前 Windows 环境只能校验代码和打包计划，Mac 的实际构建、安装与浏览器启动仍需在 Mac 验证。

## 安装与使用

打开生成的 DMG，将 `sjtu场地助手.app` 拖到 Applications，再从“应用程序”打开。
成品包含 Python 和 Chromium，使用者无需安装 Python；构建者需要 Python。
首次选择 Chromium，完成校园登录并读取场地，再设置蹲守目标与微信绑定。
应用退出后监控停止；Mac 必须保持唤醒和联网。

个人设置、会话、日志保存在：
`~/Library/Application Support/SJTU-Booking/`
配置与登录信息不会写进只读 DMG 或应用程序包；重新安装应用不会覆盖已有个人配置。
通知绑定窗口和蹲守模式与 Windows 版一致。Command + 加号/减号可调整界面，Command+0恢复默认。
“原定时抢场 / 演练”会通过 Terminal 打开旧版交互入口；系统可能要求允许应用控制 Terminal。

## 签名与分发

默认是本地构建的临时签名版本，未做 Apple Developer ID 公证。发送给其他 Mac 后可能被 Gatekeeper 拦截，不能承诺下载后无提示运行。
需要正式对外分发时，须使用你自己的 Developer ID 证书签名，并完成 Apple 公证；可用环境变量 `SJTU_CODESIGN_IDENTITY` 将证书名称传给构建器。
不要通过关闭系统安全检查来安装来源不明的应用。

本源码包仅包含公开配置和场馆目录，不含校园登录会话、密码或通知凭证。
