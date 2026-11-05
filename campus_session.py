"""校园预约会话：识别实际登录标签页，验证后保存并复用。"""
import json
import logging
from urllib.parse import urlparse
import badminton_bot as bot

SPORTS_ORIGIN = 'https://sports.sjtu.edu.cn'
SPORTS_HOME = SPORTS_ORIGIN + '/pc/#/'


def session_page(context, preferred=None):
    pages = list(reversed(context.pages))
    if preferred in pages:
        pages.remove(preferred); pages.insert(0, preferred)
    for page in pages:
        if page.is_closed(): continue
        parsed = urlparse(page.url)
        if f'{parsed.scheme}://{parsed.netloc}' != SPORTS_ORIGIN: continue
        try:
            if not page.evaluate("() => !!sessionStorage.getItem('token')"): continue
            result = page.evaluate("async () => (await fetch('/system/user/currentUser', {credentials:'include', signal:AbortSignal.timeout(5000)})).json()")
            if result.get('code') == 0 and result.get('data'):
                return page
        except (bot.PlaywrightError, ValueError):
            continue
    return None


def save_session(page, context, cfg):
    data = page.evaluate('() => ({origin: location.origin, entries: Object.entries(sessionStorage)})')
    if data.get('origin') != SPORTS_ORIGIN or not dict(data.get('entries', [])).get('token'):
        raise bot.BookingError('体育预约登录尚未完成，未覆盖原有会话。请等待返回体育预约系统后再继续。')
    state, session = bot.auth_paths(cfg)
    state.parent.mkdir(parents=True, exist_ok=True)
    session.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(state))
    session.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    # 同一次运行中新建的“我的订单”等标签页也必须带上 sessionStorage。
    payload = json.dumps(data, ensure_ascii=False)
    context.add_init_script(f'''(() => {{ const saved = {payload};
      if(location.origin === saved.origin) {{
        for(const [key,value] of saved.entries) sessionStorage.setItem(key,value);
      }} }})();''')
    logging.info('已验证并保存 %s 浏览器的校园预约会话。', cfg['browser'].get('profile', '当前'))


def ensure_session(page, context, cfg, manual):
    # 从体育系统首页开始，既能复用登录，也让统一认证的回调完成初始化。
    page.goto(SPORTS_HOME, wait_until='domcontentloaded', timeout=30000)
    for _ in range(10):
        valid = session_page(context, page)
        if valid:
            save_session(valid, context, cfg)
            return valid
        page.wait_for_timeout(150)
    button = page.get_by_text('校内人员登录', exact=True)
    try:
        button.wait_for(state='visible', timeout=3000)
        if button.count() == 1: button.click(timeout=5000)
    except bot.PlaywrightTimeoutError:
        pass
    for _ in range(3):
        manual('请在浏览器完成校园认证，等返回体育预约系统后，点击“已完成，继续”。登录成功后会自动读取场地。')
        for _ in range(20):
            valid = session_page(context, page)
            if valid:
                valid.bring_to_front()
                save_session(valid, context, cfg)
                return valid
            if page.is_closed():
                if not context.pages: break
                page = context.pages[-1]
            page.wait_for_timeout(150)
        logging.warning('尚未检测到完整的体育预约会话，请确认认证已返回体育预约系统。')
    raise bot.BookingError('未检测到有效体育预约登录。原有登录文件未覆盖，请在浏览器完成认证后重试。')
