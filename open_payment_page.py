from pathlib import Path
from playwright.sync_api import sync_playwright
from badminton_bot import load_config, open_context

cfg = load_config(Path("config.toml").resolve())
with sync_playwright() as p:
    browser, context = open_context(p, cfg, True)
    page = context.new_page()
    page.goto("https://sports.sjtu.edu.cn/pc/#/Order", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1000)
    date = page.get_by_text("2026-07-22", exact=True)
    if date.count() != 1:
        raise RuntimeError("无法唯一定位 2026-07-22 的目标订单")
    card = date.locator("xpath=ancestor::div[contains(@class,'card')][1]")
    candidates = card.get_by_text("立即支付", exact=True)
    visible = [candidates.nth(i) for i in range(candidates.count()) if candidates.nth(i).is_visible()]
    if len(visible) != 1:
        raise RuntimeError(f"目标订单中可见的立即支付按钮数量为 {len(visible)}，已停止")
    visible[0].click()
    page.screenshot(path="screenshots/payment-confirm-dialog.png", full_page=True)
    page.wait_for_timeout(400)
    buttons = page.locator("button:visible")
    button_texts = [buttons.nth(i).inner_text().strip() for i in range(buttons.count())]
    visible_confirm = [
        buttons.nth(i) for i, text in enumerate(button_texts)
        if text.replace(" ", "") == "确定"
    ]
    if len(visible_confirm) != 1:
        raise RuntimeError(f"支付确认弹窗中可见按钮为 {button_texts}，已停止")
    visible_confirm[0].click()
    page.wait_for_timeout(3000)
    page.screenshot(path="screenshots/payment-page.png", full_page=True)
    print("已进入支付页面，不会自动付款。")
    input("按 Enter 后关闭浏览器...")
