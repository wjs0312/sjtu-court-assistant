# 交大场地助手

上海交通大学体育场馆预约辅助工具，基于 Python、Tk 和 Playwright。

支持浏览器选择、项目/场馆/日期/时段选择、定时抢场、退场名额蹲守，以及 Server酱微信通知。
“任选一段”与“连续两段”使用独立模式，后者要求同一场地连续两小时同时满足；不自动付款。
校园账号由用户在学校官方页面手动登录，验证码需要人工处理。

## 在另一台电脑运行源码

需要 Python 3.11 或以上版本（带 Tk）。Windows 推荐 Python 3.12/3.13。

```powershell
git clone https://github.com/wjs0312/sjtu-court-assistant.git
cd sjtu-court-assistant
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
Copy-Item config.portable.toml config.toml
.venv\Scripts\python.exe booking_app.py
```

Mac：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp config.portable.toml config.toml
.venv/bin/python booking_app.py
```

首次选择 Chromium，登录校园账号后读取目标场馆。微信通知通过界面的绑定向导配置。
详见 [使用说明](PORTABLE_README.md)。

## 主要源码

- `booking_app.py`：GUI 与工作线程。
- `app_ui.py`：高 DPI、自适应布局和缩放。
- `badminton_bot.py`：页面操作、项目确认与场地选择。
- `watcher.py`：长期蹲守、提交锁和订单核对。
- `runtime_guard.py`：有限缓存、日志轮换和内存诊断。
- `campus_session.py`：校园认证、会话保存与恢复。
- `booking_preferences.py`：时段意图及项目名称对应。
- `notification_dialog.py`、`notifications.py`：微信绑定引导与推送。

## 打包

Windows：安装 PyInstaller 后运行 `python build_portable.py --tag custom`。
Mac：在 Mac 上执行 `一键生成DMG.command`，详见 [Mac 构建说明](MACOS_README.md)。
Mac DMG 需要原生 Mac 构建和验证；当前未提供已验证的 Mac 二进制发布包。

## 长时间运行

界面保留最近1000行日志，日志事件队列有上限；每次运行日志按5MB轮换并保留3个备份。
蹲守每分钟输出运行状态及内存采样，临时接口监听使用后解绑。保持电脑唤醒并联网。
这些保护不代表完成真实网站24小时稳定性验收；登录过期或验证码会暂停等待人工处理。

## 测试

```bash
python -m unittest test_runtime_guard test_preferences test_preferences_ui test_notification_binding test_binding_ui test_watcher test_app_platform test_mac_build
```

部分浏览器回归测试使用已安装的 Edge，见 `test_watch_browser.py`、`test_gui_login.py` 和 `test_grid_selection.py`。

## 个人信息

本仓库不含校园会话、密码、通知密钥、个人配置、日志、截图或预编译程序。
`.auth/`、`.user-settings.json`、`config.toml`、日志和构建输出均应保留在本机，勿提交。
场馆网址、公开目录和测试中的虚构凭证不是个人认证信息。请遵守学校预约规则。
