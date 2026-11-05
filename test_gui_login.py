"""复现统一认证在新标签页完成时，GUI 保存错标签页的登录状态。"""
import copy
import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import badminton_bot as bot
from booking_app import App, create_root


class GUILoginTests(unittest.TestCase):
    def test_login_in_popup_saves_sports_session_and_loads_grid(self):
        cfg = bot.load_config(bot.ROOT / 'config.portable.toml')
        cfg['target']['date'] = '2026-11-06'
        browsers = []
        contexts = []
        confirmations = []
        original = bot.open_context
        def fixture_context(p, cfg, require_auth, fresh_auth=False):
            fixture_cfg = copy.deepcopy(cfg)
            fixture_cfg['browser'].update(engine='chromium', channel='msedge', headless=True)
            browser, context = original(p, fixture_cfg, require_auth, fresh_auth)
            browsers.append(browser); contexts.append(context)
            def route(r):
                url = r.request.url
                if 'currentUser' in url:
                    logged_in = any(c['name'] == 'fixture-login' for c in context.cookies())
                    r.fulfill(json={'code': 0 if logged_in else 401, 'data': {'id': 'fixture'} if logged_in else None})
                elif 'queryVenueById' in url:
                    r.fulfill(json={'code': 0, 'data': {'venueId': 'fixture'}})
                elif 'school=1' in url:
                    r.fulfill(content_type='text/html; charset=utf-8', body='''<script>
                      sessionStorage.setItem('token','fixture-token');
                      document.cookie='fixture-login=1; path=/';
                      </script><div>已登录体育预约系统</div>''')
                else:
                    r.fulfill(content_type='text/html; charset=utf-8', body='''
                      <button onclick="window.open('/pc/?school=1#/','_blank')">校内人员登录</button>
                      <div id="apointmentDetails"><div class="el-tabs__item" role="tab"><span><p>11月06日 (周五)</p></span></div><span>场地1</span><span>19:00</span><span>20:00</span></div>
                      <script>function render(){if(location.hash.includes('apointmentDetails')){
                        if(!sessionStorage.getItem('token')){location.hash='/';}
                        else fetch('/queryVenueById');
                      }}window.addEventListener('hashchange',render);render();</script>''')
            context.route('**/*', route)
            return browser, context
        def manual(app, message):
            confirmations.append(message)
            ctx = contexts[-1]
            # 模拟用户在新标签页完成认证，再点击 GUI 的“已完成，继续”。
            ctx.pages[0].wait_for_timeout(150)
            target = ctx.pages[-1]
            target.wait_for_load_state('domcontentloaded')
            self.assertIn('school=1', target.url)
        with tempfile.TemporaryDirectory(prefix='sjtu-login-test-') as directory:
            state = Path(directory) / 'state.json'
            session = Path(directory) / 'session.json'
            with patch('badminton_bot.open_context', side_effect=fixture_context), \
                 patch('badminton_bot.auth_paths', return_value=(state, session)), \
                 patch.object(App, 'manual', manual):
                root = create_root(); app = App(root)
                try:
                    app.commands.put(('login', {'cfg': cfg, 'identity': ('edge', '2026-11-06', '羽毛球', '测试馆')}))
                    events = []
                    while True:
                        event = app.events.get(timeout=20)
                        events.append(event)
                        if event[0] == 'idle': break
                    self.assertFalse([v for kind, v in events if kind == 'error'], events)
                    self.assertTrue(session.exists(), '登录确认后必须保存会话')
                    saved = json.loads(session.read_text(encoding='utf-8'))
                    self.assertIn(['token', 'fixture-token'], saved['entries'], '必须保存完成认证的新标签页，而不是原首页')
                    self.assertTrue(any(kind == 'options' for kind, value in events), '登录成功后应自动读取场地时段')
                    # 点击“读取”不能关闭刚登录的浏览器、丢掉 sessionStorage。
                    app.commands.put(('load', {'cfg': cfg, 'identity': ('edge', '2026-11-06', '羽毛球', '测试馆')}))
                    again = []
                    while True:
                        event = app.events.get(timeout=20); again.append(event)
                        if event[0] == 'idle': break
                    self.assertTrue(any(kind == 'options' for kind, value in again), again)
                    self.assertEqual(len(contexts), 1, '同一浏览器应复用刚才的登录上下文')
                    self.assertEqual(len(confirmations), 1)
                finally:
                    app.close()
                    app.worker_thread.join(timeout=5)
                # 模拟程序退出后重新启动，只使用磁盘会话恢复，无需再次人工登录。
                root = create_root(); app = App(root)
                try:
                    app.commands.put(('load', {'cfg': cfg, 'identity': ('edge', '2026-11-06', '羽毛球', '测试馆')}))
                    restored = []
                    while True:
                        event = app.events.get(timeout=20); restored.append(event)
                        if event[0] == 'idle': break
                    self.assertTrue(any(kind == 'options' for kind, value in restored), restored)
                    self.assertEqual(len(confirmations), 1, '重启后必须使用保存的会话，不能要求重新登录')
                finally:
                    app.close(); app.worker_thread.join(timeout=5)


if __name__ == '__main__': unittest.main()
