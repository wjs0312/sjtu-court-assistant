"""真实 Tk 窗口验证绑定引导；不发送网络请求。"""
import json
from pathlib import Path
import tempfile
import unittest
from booking_app import App, create_root
from notification_dialog import NotificationDialog


class BindingUITests(unittest.TestCase):
    def setUp(self):
        self.root = create_root()
        self.app = App(self.root)
        self.temp = tempfile.TemporaryDirectory(prefix='sjtu-binding-test-')
        self.app.settings_path = Path(self.temp.name) / 'settings.json'
        self.dialog = NotificationDialog(self.app)
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.app.worker_thread.join(timeout=5)
        self.temp.cleanup()

    def test_test_request_must_be_confirmed_by_user_before_saving(self):
        d = self.dialog
        d.key.set('SCT123abc')
        d.test_result('SCT123abc', True)
        d.finish()
        self.assertTrue(d.window.winfo_exists())
        self.assertFalse(self.app.settings_path.exists())
        d.confirm()
        d.remember.set(True)
        d.finish()
        saved = json.loads(self.app.settings_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['sendkey'], 'SCT123abc')
        self.assertTrue(self.app.binding.confirmed)

    def test_session_only_binding_never_saves_credential(self):
        d = self.dialog
        d.key.set('SCT123abc'); d.test_result('SCT123abc', True); d.confirm()
        d.remember.set(False); d.finish()
        saved = json.loads(self.app.settings_path.read_text(encoding='utf-8'))
        self.assertNotIn('sendkey', saved)
        self.assertNotIn('notification_receipt', saved)
        self.assertTrue(self.app.binding.confirmed)

    def test_old_response_cannot_enable_confirmation_for_new_key(self):
        d = self.dialog
        d.key.set('SCT123abc'); d.key.set('SCT456def')
        d.test_result('SCT123abc', True)
        self.assertEqual(str(d.received_button['state']), 'disabled')
        d.finish()
        self.assertFalse(self.app.settings_path.exists())

    def test_unbind_removes_persisted_credential(self):
        d = self.dialog
        d.key.set('SCT123abc'); d.test_result('SCT123abc', True); d.confirm()
        d.remember.set(True); d.finish()
        NotificationDialog(self.app).unbind()
        saved = json.loads(self.app.settings_path.read_text(encoding='utf-8'))
        self.assertNotIn('sendkey', saved)
        self.assertEqual(self.app.key.get(), '')
        self.assertFalse(self.app.binding.confirmed)


if __name__ == '__main__': unittest.main()
