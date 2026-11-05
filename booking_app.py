"""Windows 便携界面；所有 Playwright 操作都在一个工作线程内执行。"""
import copy
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from datetime import datetime, timedelta

import badminton_bot as bot
import notifications
import watcher
from notification_binding import NotificationBinding
from notification_dialog import NotificationDialog
import campus_session
from app_ui import WorkspaceView
from booking_preferences import time_groups, selection_text, site_sport, canonical_detail_url
from app_platform import prepare_data, terminal_command
from runtime_guard import append_log


def create_root():
    # 多窗口回归测试或再次创建界面时，在主线程清理已销毁的 Tk 对象。
    import gc
    gc.collect()
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
    root = tk.Tk()
    if sys.platform == 'darwin':
        # Aqua 使用逻辑坐标，Retina 的设备像素倍数由 Tk 自己处理。
        root._system_dpi = 96
        return root
    dpi = root.winfo_fpixels('1i')
    if sys.platform == 'win32':
        dpi = ctypes.windll.user32.GetDpiForWindow(root.winfo_id()) or dpi
    root._system_dpi = dpi
    root.tk.call('tk', 'scaling', dpi / 72)
    return root


class QueueLog(logging.Handler):
    def __init__(self, events):
        super().__init__(logging.INFO); self.events = events; self.dropped=0

    def emit(self, record):
        message=self.format(record)[:4000]
        if self.dropped:message=f'[已省略 {self.dropped} 条积压日志]\n'+message
        try:
            self.events.put_nowait(('log', message))
            self.dropped=0
        except queue.Full:
            self.dropped+=1


class App:
    def __init__(self, root):
        self.root = root
        self.commands, self.events = queue.Queue(), queue.Queue(maxsize=2000)
        self.stop, self.resume = threading.Event(), threading.Event()
        self.busy = False
        self.loaded_identity = None
        self.entries = bot.load_venue_catalog()
        self.courts, self.slots = [], []
        self.settings_path = bot.ROOT / '.user-settings.json'
        try:
            self.settings = json.loads(self.settings_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.settings = {}
        self.browser = tk.StringVar(value=self.settings.get('browser', 'chromium'))
        self.day = tk.StringVar(value=(datetime.now(watcher.TZ).date() + timedelta(days=1)).isoformat())
        self.sport = tk.StringVar(value='羽毛球')
        self.venue = tk.StringVar()
        self.time_mode = tk.StringVar(value='任选一段')
        self.selection_summary = tk.StringVar(value='请选择预约方式和目标时段。')
        self.interval = tk.StringVar(value='5')
        self.end = tk.StringVar()
        self.mode = tk.StringVar(value='自动提交到待支付')
        self.key = tk.StringVar(value=self.settings.get('sendkey', ''))
        self.save_key = tk.BooleanVar(value=bool(self.settings.get('sendkey')))
        self.binding = NotificationBinding(self.key.get(), self.settings.get('notification_receipt', ''))
        self.binding_status = tk.StringVar()
        self.status = tk.StringVar(value='准备就绪 · 选择目标后登录，即可读取场地')
        self.ui = WorkspaceView(self)
        handler = QueueLog(self.events); handler.setFormatter(logging.Formatter('%(asctime)s  %(message)s', '%H:%M:%S'))
        logging.getLogger().addHandler(handler)
        self.log_handler = handler
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.worker_thread = threading.Thread(target=self.worker, daemon=True)
        self.worker_thread.start()
        self.poll_timer = root.after(100, self.poll)

    def update_venues(self, event=None):
        self.venue_rows = [e for e in self.entries if e['sport'] == self.sport.get()]
        self.venue_box['values'] = [f"{e.get('campus', '')} · {e['venue']}" for e in self.venue_rows]
        if self.venue_rows: self.venue_box.current(0)

    def identity(self):
        return self.browser.get(), self.day.get(), self.sport.get(), self.venue.get()

    def update_selection_summary(self, *_):
        if not hasattr(self, 'slot_list'): return
        selected = [self.slots[i] for i in self.slot_list.curselection() if i < len(self.slots)]
        court_names = [self.courts[i] for i in self.court_list.curselection() if i < len(self.courts)]
        project = site_sport(self.sport.get())
        prefix = f'目标项目：{project}。'
        if self.loaded_identity != self.identity():
            prefix += '目标尚未读取或已改变，请先读取当前目标。'
        elif self.courts:
            prefix += ('场地：' + ' / '.join(court_names) + '，任选一块。') if court_names else '请先选择可接受的场地。'
        else:
            prefix += '无需指定编号场地，按该项目的可约名额尝试。'
        try:
            self.selection_summary.set(prefix + '\n' + selection_text(self.time_mode.get(), selected))
        except ValueError as exc:
            self.selection_summary.set(prefix + '\n' + str(exc))

    def dispatch(self, action):
        if self.busy: return
        try:
            datetime.strptime(self.day.get(), '%Y-%m-%d')
            cfg = copy.deepcopy(bot.load_config(bot.ROOT / 'config.toml'))
            bot.choose_browser(cfg, self.browser.get())
            row = self.venue_rows[self.venue_box.current()]
            cfg['site']['detail_url'] = canonical_detail_url(row['detail_url'], row['sport'])
            cfg['target'].update(venue=row['venue'], sport=row['sport'], date=self.day.get())
            cfg['_manual_action'] = self.manual
            args = {'cfg': cfg, 'identity': self.identity()}
            if action == 'watch':
                if self.loaded_identity != self.identity():
                    raise ValueError('目标已改变，请先重新读取场地与时段。')
                courts = [self.courts[i] for i in self.court_list.curselection()]
                slots = [self.slots[i] for i in self.slot_list.curselection()]
                if self.courts and not courts: raise ValueError('请选择至少一个可接受的场地。')
                if not slots: raise ValueError('请选择至少一个目标时段。')
                groups = time_groups(self.time_mode.get(), slots)
                end = watcher.cutoff(self.day.get(), groups, self.end.get())
                if end <= datetime.now(watcher.TZ): raise ValueError('截止时间已过，请选择未来的日期与时段。')
                interval = float(self.interval.get())
                if not 2 <= interval <= 3600: raise ValueError('检查间隔应为 2–3600 秒。')
                cfg['target'].update(court_priority=courts, time_slot_groups=groups, time_slot_priority=slots)
                logging.info('本次预约意图：%s / %s / %s', site_sport(row['sport']), cfg['target']['date'], selection_text(self.time_mode.get(), slots))
                args.update(end=end, interval=interval, submit=self.mode.get().startswith('自动'), key=self.key.get().strip())
                if args['key'] and not args['key'].startswith('SCT'): raise ValueError('微信通知需要 SCT 开头的 SendKey。')
            self.save_settings()
            self.busy = True; self.stop.clear(); self.resume.clear()
            self.ui.set_busy(True)
            for b in [self.login_button, self.load_button, self.start_button, self.binding_button]: b.configure(state='disabled')
            self.status.set('正在处理，请查看浏览器与下方日志…')
            self.commands.put((action, args))
        except Exception as exc:
            messagebox.showerror('请检查输入', str(exc))

    def save_settings(self):
        value = {'browser': self.browser.get(), 'ui_zoom': self.ui.zoom.get()}
        if self.save_key.get():
            value['sendkey'] = self.key.get().strip()
            value['notification_receipt'] = self.binding.receipt
        self.settings_path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def manual(self, message):
        self.resume.clear()
        logging.warning('等待人工处理，监控暂时暂停：%s', message)
        self.events.put(('manual', message))
        key = self.current_key
        threading.Thread(target=notifications.send, args=('蹲场需要人工处理', message, key), daemon=True).start()
        while not self.resume.wait(0.2):
            if self.stop.is_set(): raise bot.BookingError('用户停止了操作。')
        if self.stop.is_set(): raise bot.BookingError('用户停止了操作。')
        self.events.put(('resumed', '已继续'))

    def cancel(self):
        self.stop.set(); self.resume.set()
        self.status.set('正在停止；正在执行的页面操作结束后生效。浏览器保留供查看。')

    def refresh_binding_status(self):
        text = '已绑定 · 微信收件已确认' if self.binding.confirmed else ('已导入 · 等待测试确认' if self.binding.key else '未绑定 · 当前使用本地提醒')
        self.binding_status.set(text)
        self.binding_button.configure(text='管理微信通知' if self.binding.key else '绑定微信通知')

    def bind_notice(self):
        if not self.busy:
            NotificationDialog(self)

    def worker(self):
        self.current_key = ''
        browser = context = page = None
        active_browser = None
        with bot.sync_playwright() as p:
            while True:
                action, args = self.commands.get()
                if action == 'close':
                    if browser: browser.close()
                    return
                cfg = args['cfg']; self.current_key = args.get('key', '')
                try:
                    profile = tuple(cfg['browser'].get(k) for k in ('profile', 'engine', 'channel'))
                    if not browser or not browser.is_connected() or active_browser != profile:
                        if browser: browser.close()
                        browser, context = bot.open_context(p, cfg, require_auth=False)
                        active_browser = profile
                        page = context.new_page()
                    if not page or page.is_closed(): page = context.new_page()
                    page = campus_session.ensure_session(page, context, cfg, self.manual)
                    if self.stop.is_set(): raise bot.BookingError('操作已取消。')
                    self.events.put(('log', '校园登录已验证并保存，正在读取所选场馆…'))
                    rt = bot.Runtime(cfg, bot.build_variables(cfg, datetime.now(watcher.TZ)), True)
                    bot.open_sjtu_detail(page, rt, 15000)
                    watcher.select_date(page, rt)
                    if action in ('login', 'load'):
                        courts, slots = bot.wait_for_grid_options(page)
                        if not slots:
                            raise bot.BookingError('该日期尚未读取到预约时段，请确认日期在场馆可预约范围内，或换一个日期后点击读取。')
                        self.events.put(('options', (args['identity'], courts, slots)))
                        logging.info('场地读取成功：%s 个场地、%s 个时段。', len(courts), len(slots))
                    else:
                            active = lambda: not self.stop.is_set() and datetime.now(watcher.TZ) < args['end']
                            attempt = watcher.BookingAttempt(page, context, cfg, args['submit'], self.manual, active)
                            def notify(state):
                                labels = {'confirmed': '场地蹲到了，订单待支付', 'selected': '场地已选中，尚未提交', 'unknown': '提交结果待确认，请检查订单', 'expired': '蹲守已截止，未命中目标', 'cancelled': '蹲守已停止'}
                                v = attempt.rt.variables
                                body = f"{v['venue']} / {v.get('selected_sport', site_sport(cfg['target'].get('sport', '')))}\n{v['target_date']}\n{v.get('selected_court', '')} {v.get('selected_time_slot', '')}\n{watcher.ORDER_URL}\n请以网站订单状态和付款期限为准。"
                                self.events.put(('result', labels[state]))
                                logging.info('%s\n%s', labels[state], body)
                                if state != 'cancelled':
                                    threading.Thread(target=notifications.send, args=(labels[state], body, args['key']), daemon=True).start()
                                try:
                                    import winsound
                                    winsound.MessageBeep()
                                except ImportError:
                                    self.events.put(('bell', ''))
                            logging.info('监控开始，截止时间：%s；正常状态每分钟汇总一次。', args['end'].isoformat())
                            watcher.monitor(attempt, active, self.stop, self.stop.wait, notify, args['interval'])
                except Exception as exc:
                    logging.error('操作 %s 未完成（%s），请查看界面中的具体错误。', action, type(exc).__name__)
                    self.events.put(('error', str(exc)))
                finally:
                    self.events.put(('idle', ''))

    def legacy(self):
        if self.busy:
            messagebox.showinfo('任务运行中', '请先停止当前操作。'); return
        # 新控制台保留原脚本交互，不影响 GUI 工作线程。
        if getattr(sys, 'frozen', False): command = [sys.executable, '--cli']
        else: command = [sys.executable, str(bot.ROOT / 'badminton_bot.py')]
        command += ['check' if messagebox.askyesno('原抢场模式', '是否进行不提交订单的演练？\n选择“否”运行原定时抢场。') else 'run']
        command += ['--browser', self.browser.get()]
        launch, options = terminal_command(command)
        subprocess.Popen(launch, cwd=bot.ROOT, **options)

    def poll(self):
        lines=[]
        for _ in range(100):
            try:kind, value = self.events.get_nowait()
            except queue.Empty:break
            if kind == 'bell':
                self.root.bell()
                continue
            if kind == 'binding_test':
                dialog, key, ok = value
                dialog.test_result(key, ok)
                continue
            if kind == 'options':
                self.loaded_identity, self.courts, self.slots = value
                for box, values in [(self.court_list, self.courts), (self.slot_list, self.slots)]:
                    box.configure(state='normal')
                    box.delete(0, 'end')
                    for item in values: box.insert('end', item)
                if not self.courts:
                    self.court_list.insert('end', '无需选择编号场地', '按该项目可约名额尝试')
                    self.court_list.configure(state='disabled')
                self.update_selection_summary()
                self.status.set(f'已确认项目：{site_sport(self.sport.get())} · 已读取 {len(self.slots)} 个时段')
                continue
            if kind == 'idle':
                self.busy = False
                self.ui.set_busy(False)
                for b in [self.login_button, self.load_button, self.start_button, self.binding_button]: b.configure(state='normal')
                self.continue_button.configure(state='disabled')
                continue
            if kind == 'manual':
                self.continue_button.configure(state='normal'); self.status.set(value)
            elif kind == 'resumed': self.continue_button.configure(state='disabled')
            elif kind in ('result', 'error'): self.status.set(value.splitlines()[0][:240])
            lines.append(value)
        if lines:append_log(self.log,'\n'.join(lines))
        self.poll_timer = self.root.after(100, self.poll)

    def close(self):
        self.stop.set(); self.resume.set()
        self.commands.put(('close', {}))
        self.root.after_cancel(self.poll_timer)
        logging.getLogger().removeHandler(self.log_handler)
        self.root.destroy()


def main():
    if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
        prepare_data(bot.ROOT, bot.RESOURCE_ROOT)
    os.chdir(bot.ROOT)
    bundled = bot.RESOURCE_ROOT / 'browsers'
    if bundled.exists(): os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled)
    if '--cli' in sys.argv:
        sys.argv.remove('--cli'); return bot.main()
    if '--self-test' in sys.argv:
        root = create_root(); app = App(root); root.update()
        assert len(app.entries) > 0 and app.venue_rows
        assert app.log.winfo_height() >= 60
        assert app.court_list.winfo_ismapped() and app.slot_list.winfo_ismapped()
        app.close()
        app.worker_thread.join(timeout=5)
        with bot.sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=p.chromium.executable_path)
            page = browser.new_page()
            page.set_content('<div id="ok">portable browser ready</div>')
            assert page.locator('#ok').inner_text() == 'portable browser ready'
            browser.close()
        print('SELF_TEST_OK: UI, catalog, bundled Chromium')
        return 0
    if sys.platform == 'win32' and getattr(sys, 'frozen', False):
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    bot.setup_logging()
    root = create_root()
    App(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
