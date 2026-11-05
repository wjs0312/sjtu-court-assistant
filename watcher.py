"""可中断的长期监控及 SJTU 页面适配器。"""
import logging
import re
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import badminton_bot as bot
from runtime_guard import memory_summary

TZ = ZoneInfo('Asia/Shanghai')
ORDER_URL = 'https://sports.sjtu.edu.cn/pc/#/Order'


def cutoff(day, groups, end_time=''):
    starts = [datetime.fromisoformat(f'{day}T{g[0].split("-")[0]}').replace(tzinfo=TZ) for g in groups]
    if not starts:
        raise ValueError('请选择至少一个时段。')
    if end_time.strip():
        starts.append(datetime.fromisoformat(f'{day}T{end_time.strip()}').replace(tzinfo=TZ))
    return min(starts)


def monitor(attempt, active, stop, wait, notify, interval=5):
    if interval < 2:
        raise ValueError('检查间隔至少为 2 秒。')
    rounds = 0
    errors = 0
    total_errors = 0
    started = time.monotonic()
    next_report = started
    next_warning = started
    while not stop.is_set() and active():
        rounds += 1
        now = time.monotonic()
        if now >= next_report:
            logging.info('蹲守运行 %.1f 分钟 · 第 %s 轮 · 累计网络异常 %s 次 · %s',
                         (now-started)/60, rounds, total_errors, memory_summary())
            next_report = now + 60
        try:
            state = attempt()
            errors = 0
        except bot.PlaywrightError:
            errors += 1
            total_errors += 1
            state = 'unavailable'
            if time.monotonic() >= next_warning:
                logging.warning('页面或网络暂时不可用，延长等待后重试；重复异常每分钟汇总。')
                next_warning = time.monotonic() + 60
        if state in ('confirmed', 'selected', 'unknown'):
            notify(state)
            return state
        wait(min(interval * (2 ** min(errors, 4)), 60))
    state = 'cancelled' if stop.is_set() else 'expired'
    notify(state)
    return state


def select_date(page, rt):
    day = datetime.strptime(rt.variables['target_date'], '%Y-%m-%d')
    # 学校日期页签的完整文字为“11月06日 (周五)”，不能用纯日期作 exact 匹配。
    label = re.compile(rf'^\s*0?{day.month}月0?{day.day}日(?:\s*[（(]周[日一二三四五六天][）)])?\s*$')
    candidates = page.locator('.el-tabs__item').filter(has_text=label)
    if candidates.count() == 0:
        candidates = page.get_by_text(label)
    try:
        candidates.first.wait_for(state='visible', timeout=5000)
    except bot.PlaywrightTimeoutError as exc:
        raise bot.BookingError(f'页面未开放或未显示 {rt.variables["target_date"]} 的日期页签，请选择网站当前可预约的日期后重新读取。') from exc
    visible = [candidates.nth(i) for i in range(candidates.count()) if candidates.nth(i).is_visible()]
    if len(visible) != 1:
        raise bot.BookingError('无法唯一识别目标日期页签，已停止读取以避免选错日期。')
    visible[0].click(timeout=5000)
    page.get_by_text('拼命加载中', exact=False).wait_for(state='hidden', timeout=15000)


def matching_order_cards(page, rt):
    values = rt.variables
    required = [values['target_date'], values['venue'], values['selected_time_slot'], '待支付']
    if values.get('selected_sport'):
        required.append(values['selected_sport'])
    if values.get('selected_court') != '页面首个可用位置':
        required.append(values['selected_court'])
    def compact(s):
        return ''.join(s.split()).replace('：', ':').replace('～', '-').replace('至', '-')
    cards = page.locator('div.card')
    result = []
    for i in range(cards.count()):
        card = cards.nth(i)
        content = compact(card.inner_text())
        if all(compact(v) in content for v in required):
            result.append(card)
    return result


class BookingAttempt:
    def __init__(self, page, context, cfg, submit, manual, active):
        self.page, self.context, self.cfg = page, context, cfg
        self.submit, self.manual, self.active = submit, manual, active
        self.rt = bot.Runtime(cfg, bot.build_variables(cfg, datetime.now(TZ)), not submit)
        self.locked = False

    def __call__(self):
        if self.locked:
            return 'unknown'
        page, rt = self.page, self.rt
        if page.url == rt.variables['detail_url']:
            page.reload(wait_until='domcontentloaded', timeout=15000)
        else:
            page.goto(rt.variables['detail_url'], wait_until='domcontentloaded', timeout=15000)
        bot.pause_for_captcha(page, self.cfg)
        session = page.evaluate("async () => (await fetch('/system/user/currentUser', {signal:AbortSignal.timeout(10000)})).json()")
        if session.get('code') != 0 or not session.get('data'):
            page.goto(self.cfg['site']['login_url'], wait_until='domcontentloaded', timeout=15000)
            login = page.get_by_text('校内人员登录', exact=True)
            if login.count() == 1 and login.is_visible(): login.click()
            self.manual('登录已失效，请在浏览器重新登录，完成后点击继续。')
            return 'unavailable'
        bot.wait_for_sjtu_detail(page, 15000)
        bot.select_sjtu_sport(page, rt, 15000)
        select_date(page, rt)
        try:
            bot.select_sjtu_slot(page, rt, 3000)
        except bot.PlaywrightTimeoutError:
            return 'unavailable'
        if int(rt.variables.get('selected_slot_count', '1')) == 2:
            # 学校的限约规则可能在点击第二格后自动取消第一格，必须核对实际选中数。
            if page.locator('#apointmentDetails .inner-seat.selected-seat').count() != 2:
                logging.debug('连续两段尚未同时选中，本轮不提交任何订单。')
                return 'unavailable'
        if not self.active():
            return 'unavailable'
        if not self.submit:
            bot.screenshot(page, 'watch-selected')
            return 'selected'
        # 先核查是否已有相同待支付订单，避免重启后重复提交。
        order_page = self.context.new_page()
        try:
            order_page.goto(ORDER_URL, wait_until='domcontentloaded', timeout=15000)
            order_page.wait_for_timeout(1500)
            existing = matching_order_cards(order_page, rt)
            if existing:
                self.locked = True
                order_page.bring_to_front()
                return 'confirmed' if len(existing) == 1 else 'unknown'
        finally:
            if not self.locked:
                order_page.close()
        seen_selection = False
        try:
            for index, step in enumerate(self.cfg['booking_steps'], 1):
                if step.get('action') == 'sjtu_select_slot':
                    seen_selection = True
                    continue
                if not seen_selection:
                    continue
                if not self.active():
                    return 'unavailable'
                if step.get('final_submit'):
                    # 点击前设锁：点击响应丢失也不能重试提交。
                    self.locked = True
                bot.perform_step(page, step, rt, index)
            if not self.locked:
                raise bot.ConfigError('预约步骤中缺少最终提交步骤。')
        except bot.PlaywrightError:
            if not self.locked:
                raise
        if self.locked:
            try:
                page.goto(ORDER_URL, wait_until='domcontentloaded', timeout=15000)
                for _ in range(5):
                    page.wait_for_timeout(1000)
                    if len(matching_order_cards(page, rt)) == 1:
                        bot.screenshot(page, 'watch-order-confirmed')
                        return 'confirmed'
            except bot.PlaywrightError:
                pass
            try:
                bot.screenshot(page, 'watch-submit-unknown')
            except bot.PlaywrightError:
                logging.warning('提交结果未知，页面无法截图，请人工检查订单。')
            return 'unknown'
        return 'unavailable'


def run_watch(config_path, browser_override=None, dry_run=False):
    import notifications
    cfg = bot.load_config(config_path)
    bot.choose_browser(cfg, browser_override)
    cfg['target']['date'] = input('预约日期 YYYY-MM-DD：').strip()
    datetime.strptime(cfg['target']['date'], '%Y-%m-%d')
    stop = threading.Event()
    with bot.sync_playwright() as p:
        browser, context = bot.open_context(p, cfg, require_auth=True)
        try:
            page, cfg = bot.interactive_targets(context, cfg, 1)[0]
            interval = float(input('检查间隔秒数（默认5，至少2）：').strip() or '5')
            if interval < 2: raise bot.ConfigError('检查间隔至少2秒。')
            end = cutoff(cfg['target']['date'], cfg['target']['time_slot_groups'], input('截止时刻 HH:MM（留空到开场）：'))
            if end <= datetime.now(TZ): raise bot.ConfigError('目标时段或截止时间已过。')
            submit = not dry_run and input('命中后自动提交到待支付？[Y/n]：').lower() != 'n'
            def manual(message):
                notifications.send('蹲场需要人工处理', message)
                print('\a' + message); input('完成后按 Enter 继续…')
            cfg['_manual_action'] = manual
            active = lambda: datetime.now(TZ) < end
            attempt = BookingAttempt(page, context, cfg, submit, manual, active)
            def notify(state):
                title = {'confirmed': '场地蹲到了，订单待支付', 'selected': '已选中场地，尚未提交', 'unknown': '提交结果不明，请检查订单', 'expired': '蹲守截止，未命中', 'cancelled': '蹲守已停止'}[state]
                v = attempt.rt.variables
                body = f"{v['venue']} {v['target_date']} {v.get('selected_court', '')} {v.get('selected_time_slot', '')}\n{ORDER_URL}"
                logging.info('%s：%s', title, body)
                notifications.send(title, body)
                print('\a' + title)
            result = monitor(attempt, active, stop, stop.wait, notify, interval)
            input('浏览器已保留，请检查或支付；处理后按 Enter 关闭…')
            return 0 if result in ('confirmed', 'selected') else 1
        finally:
            context.close(); browser.close()
