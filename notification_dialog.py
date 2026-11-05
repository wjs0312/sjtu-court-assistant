"""微信通知绑定引导；只打开官方网页，不抓取用户登录信息。"""
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser
import notifications
from notification_binding import NotificationBinding
from app_ui import ScrollArea


class NotificationDialog:
    def __init__(self, app):
        self.app = app
        self.binding = NotificationBinding(app.key.get(), app.binding.receipt)
        self.testing = False
        self.window = tk.Toplevel(app.root)
        self.window.title('绑定微信通知')
        self.window.geometry(app.ui.window_geometry(760, 750))
        self.window.minsize(app.ui.p(500), min(app.ui.p(450), app.root.winfo_screenheight()-100))
        self.window.configure(background='#F1F5F9')
        self.window.transient(app.root); self.window.grab_set()
        self.scroll_area = ScrollArea(self.window, app.ui, minimum=600)
        self.scroll_area.frame.pack(fill='both', expand=True)
        outer = ttk.Frame(self.scroll_area.content, padding=app.ui.p(24), style='Shell.TFrame'); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='让微信提醒你，场地蹲到了', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='由 Server酱 Turbo 提供通知通道。首次绑定需要完成以下三步。', style='Shell.TLabel').pack(anchor='w', pady=(8, 18))
        first = ttk.LabelFrame(outer, text='01   用微信扫码登录', padding=14); first.pack(fill='x')
        ttk.Label(first, text='打开官方页面，用微信扫码登录，并按页面指引配置微信通知通道。', wraplength=app.ui.p(570)).pack(anchor='w')
        ttk.Button(first, text='打开官方扫码登录页', command=lambda: self.open_url('https://sct.ftqq.com/sendkey/')).pack(anchor='w', pady=(10, 0))
        second = ttk.LabelFrame(outer, text='02   导入通知凭证', padding=14); second.pack(fill='x', pady=12)
        ttk.Label(second, text='在官方页面复制 SendKey，再点击“粘贴凭证”。无需填写微信密码。', wraplength=app.ui.p(570)).pack(anchor='w')
        self.key = tk.StringVar(value=self.binding.key)
        line = ttk.Frame(second); line.pack(fill='x', pady=(10, 8))
        ttk.Entry(line, textvariable=self.key, show='*', width=24,font=app.ui.fonts['body']).pack(side='left', fill='x', expand=True)
        ttk.Button(line, text='粘贴凭证', command=self.paste).pack(side='left', padx=(8, 0))
        self.remember = tk.BooleanVar(value=app.save_key.get())
        ttk.Checkbutton(second, text='在这台电脑记住绑定（仅可信电脑勾选）', variable=self.remember).pack(anchor='w')
        ttk.Label(second, text='勾选后凭证保存在本机设置文件中；不勾选则仅本次运行有效。', foreground='#475569',wraplength=app.ui.p(570)).pack(anchor='w', pady=(4, 0))
        third = ttk.LabelFrame(outer, text='03   确认微信能收到', padding=14); third.pack(fill='x')
        line = ttk.Frame(third); line.pack(fill='x')
        self.test_button = ttk.Button(line, text='发送测试通知', command=self.test)
        self.test_button.pack(side='left')
        self.received_button = ttk.Button(line, text='我已在微信收到', command=self.confirm, state='disabled')
        self.received_button.pack(side='left', padx=8)
        self.message = tk.StringVar(value='发送后请查看手机微信，收到消息后再确认。')
        ttk.Label(third, textvariable=self.message, wraplength=app.ui.p(565)).pack(anchor='w', pady=(10, 0))
        footer = ttk.Frame(outer, style='Shell.TFrame'); footer.pack(fill='x', pady=(16, 0))
        ttk.Button(footer, text='保存并完成', style='Primary.TButton', command=self.finish).pack(side='right')
        ttk.Button(footer, text='解除绑定', command=self.unbind).pack(side='left')
        ttk.Button(footer, text='通道配置帮助', command=lambda: self.open_url('https://sct.ftqq.com/docs/getting-started/sendkey/')).pack(side='left', padx=8)
        self.key.trace_add('write', self.changed)

    def open_url(self, url):
        if not webbrowser.open(url):
            self.message.set('无法打开浏览器，请手动访问 sct.ftqq.com 登录并获取凭证。')

    def paste(self):
        try:
            self.key.set(self.window.clipboard_get().strip())
        except tk.TclError:
            self.message.set('剪贴板中没有文本，请先在官方页面复制凭证。')

    def changed(self, *_):
        self.binding.set_key(self.key.get())
        self.received_button.configure(state='disabled')
        self.message.set('凭证已更新，请重新发送测试通知。')

    def test(self):
        if self.testing: return
        try:
            self.binding.set_key(self.key.get())
            key = self.binding.validate()
        except ValueError as exc:
            self.message.set(str(exc)); return
        self.testing = True
        self.test_button.configure(state='disabled')
        self.received_button.configure(state='disabled')
        self.binding.can_confirm = False
        self.message.set('正在发送测试通知，请稍候…')
        def work():
            ok = notifications.send('交大场地助手绑定测试', '如果你看到了这条消息，请回到场地助手，点击“我已在微信收到”完成绑定。', key)
            self.app.events.put(('binding_test', (self, key, ok)))
        threading.Thread(target=work, daemon=True).start()

    def test_result(self, key, ok):
        if not self.window.winfo_exists(): return
        self.testing = False
        self.test_button.configure(state='normal')
        if not self.binding.test_result(key, ok):
            self.message.set('凭证已改变，请使用当前凭证重新测试。'); return
        if ok:
            self.received_button.configure(state='normal')
            self.message.set('通知服务已接受请求。请检查手机；实际收到后点击“我已在微信收到”。')
        else:
            self.received_button.configure(state='disabled')
            self.message.set('发送失败。请检查凭证、网络、官方通道配置及剩余配额，然后重试。')

    def confirm(self):
        self.binding.confirm_received()
        self.received_button.configure(state='disabled')
        self.message.set('已确认收到微信通知，点击“保存并完成”即可。')

    def finish(self):
        self.binding.set_key(self.key.get())
        try:
            self.binding.validate()
        except ValueError as exc:
            self.message.set(str(exc)); return
        if not self.binding.confirmed:
            self.message.set('请先发送测试通知，并确认手机实际收到后再完成绑定。'); return
        self.apply(self.binding, self.remember.get())

    def unbind(self):
        self.apply(NotificationBinding(), False)

    def apply(self, binding, remember):
        previous = self.app.key.get(), self.app.binding, self.app.save_key.get()
        self.app.key.set(binding.key)
        self.app.binding = binding
        self.app.save_key.set(remember)
        try:
            self.app.save_settings()
        except OSError:
            self.app.key.set(previous[0])
            self.app.binding = previous[1]
            self.app.save_key.set(previous[2])
            self.message.set('无法保存本机设置，请将程序移到可写文件夹后重试。'); return
        self.app.refresh_binding_status()
        self.window.destroy()
