"""离线网页集成测试：真实 Chromium，所有校园请求由本地夹具响应。"""
import copy
import unittest
from unittest.mock import patch
from threading import Event
from playwright.sync_api import sync_playwright
import badminton_bot as bot
import watcher


class BrowserWatchTests(unittest.TestCase):
    def test_watch_switches_to_gym_before_reading_or_selecting(self):
        cfg = bot.load_config(bot.ROOT / 'config.portable.toml')
        cfg['target'].update(date='2026-11-06', sport='学生中心健身房', court_priority=[],
                             time_slot_groups=[['19:00-20:00']],time_slot_priority=['19:00-20:00'])
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            context=browser.new_context()
            html='''<style>.t{position:absolute;left:5px;top:180px}.inner-seat{position:absolute;left:220px;top:170px;width:70px;height:45px;background:rgb(210,230,255)}</style>
              <div id="apointmentDetails"><div class="lists"><div class="el-tabs">
              <div role="tab" class="el-tabs__item is-active">排练厅</div>
              <div role="tab" class="el-tabs__item" onclick="document.querySelector('.is-active').classList.remove('is-active');this.classList.add('is-active');document.querySelector('#target').classList.remove('bought-seat');document.body.dataset.sport='健身房';fetch('/queryFieldSituation')">健身房</div></div>
              <div class="chart"><div class="el-tabs__item" role="tab">11月06日 (周五)</div><span class="t">19:00</span>
              <button class="inner-seat bought-seat" id="target" onclick="this.dataset.hit=1"></button></div></div></div>'''
            def route(r):
                if 'currentUser' in r.request.url:r.fulfill(json={'code':0,'data':{'id':'fixture'}})
                elif 'queryFieldSituation' in r.request.url:r.fulfill(json={'code':0,'data':[]})
                else:r.fulfill(content_type='text/html; charset=utf-8',body=html)
            context.route('**/*',route)
            page=context.new_page()
            attempt=watcher.BookingAttempt(page,context,cfg,False,lambda x:None,lambda:True)
            with patch('watcher.bot.screenshot'):
                self.assertEqual(attempt(),'selected')
            self.assertEqual(page.locator('body').get_attribute('data-sport'),'健身房')
            self.assertEqual(page.locator('#target').get_attribute('data-hit'),'1')
            page.set_content('<div id="apointmentDetails"><div class="lists"><div class="el-tabs"><div class="el-tabs__item is-active">排练厅</div></div></div></div>')
            with self.assertRaises(bot.BookingError):bot.select_sjtu_sport(page,attempt.rt,1000)
            browser.close()

    def test_select_date_matches_school_label_with_weekday(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page()
            page.set_content('''<div class="el-tabs__item" role="tab" onclick="this.dataset.hit=1"><span><p>11月06日 (周五)</p></span></div>''')
            rt = bot.Runtime({}, {'target_date': '2026-11-06', 'target_date_cn_zero': '11月06日'}, True)
            watcher.select_date(page, rt)
            self.assertEqual(page.locator('[role=tab]').get_attribute('data-hit'), '1')
            browser.close()

    def test_occupied_then_released_selects_only_requested_court_and_stops(self):
        cfg = bot.load_config(bot.ROOT / 'config.portable.toml')
        cfg['target'].update(date='2026-11-06', court_priority=['场地2'],
                             time_slot_priority=['19:00-20:00'], time_slot_groups=[['19:00-20:00']])
        loads = []
        html = '''<style>
        .h{position:absolute;top:70px;width:80px}.t{position:absolute;left:5px;top:150px}
        .inner-seat,.bought-seat{position:absolute;top:140px;width:70px;height:45px;background:rgb(210,230,255)}
        </style><div id="apointmentDetails"><button>11月06日</button>
        <div class="h" style="left:150px">场地1</div><div class="h" style="left:260px">场地2</div>
        <div class="t">19:00</div>
        <button id="other" class="inner-seat" style="left:150px" onclick="this.dataset.hit=1"></button>
        <button id="target" class="STATE" style="left:260px" onclick="this.dataset.hit=1"></button></div>'''
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context()
            def route(request):
                if 'currentUser' in request.request.url:
                    request.fulfill(json={'code': 0, 'data': {'id': 'fixture'}})
                else:
                    loads.append(1)
                    request.fulfill(content_type='text/html; charset=utf-8', body=html.replace('STATE', 'bought-seat' if len(loads) == 1 else 'inner-seat'))
            context.route('**/*', route)
            page = context.new_page()
            attempt = watcher.BookingAttempt(page, context, cfg, False, lambda message: self.fail(message), lambda: True)
            notices = []
            with patch('watcher.bot.screenshot'):
                self.assertEqual(attempt(), 'unavailable')
                result = attempt()
                notices.append(result)
            self.assertEqual(result, 'selected')
            self.assertEqual(len(loads), 2)
            self.assertEqual(page.locator('#target').get_attribute('data-hit'), '1')
            self.assertIsNone(page.locator('#other').get_attribute('data-hit'))
            self.assertEqual(notices, ['selected'])
            # 已有同日其他场地订单不能冒充当前目标。
            page.set_content('''<div class="card">2026-11-06 羽毛球馆 场地1 19:00-20:00 待支付</div>
                              <div class="card">2026-11-06 羽毛球馆 场地2 19:00-20:00 待支付</div>''')
            self.assertEqual(len(watcher.matching_order_cards(page, attempt.rt)), 1)
            page.set_content('<div class="card">2026-11-06 羽毛球馆 场地1 19:00-20:00 待支付</div>')
            self.assertEqual(watcher.matching_order_cards(page, attempt.rt), [])
            browser.close()


if __name__ == '__main__':
    unittest.main()
