import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from booking_app import App, create_root


class DisplayTests(unittest.TestCase):
    def test_tk_respects_windows_display_dpi(self):
        root = create_root(); root.update()
        try:
            if sys.platform == 'win32':
                dpi = ctypes.windll.user32.GetDpiForWindow(root.winfo_id())
                self.assertAlmostEqual(root.winfo_fpixels('1i'), dpi, delta=3)
        finally: root.destroy()

    def test_zoom_enlarges_real_font_and_preserves_selection(self):
        root = create_root(); app = App(root)
        try:
            with tempfile.TemporaryDirectory() as directory:
                app.settings_path = Path(directory) / 'settings.json'
                app.court_list.insert('end', '场地1', '场地2'); app.court_list.selection_set(1)
                root.update()
                before = app.court_list.winfo_reqheight()
                app.ui.set_zoom('150%'); root.update()
                self.assertGreater(app.court_list.winfo_reqheight(), before * 1.3)
                self.assertEqual(app.court_list.curselection(), (1,))
                self.assertIn('150%', app.settings_path.read_text(encoding='utf-8'))
                root.geometry('1500x1160+0+0')
                app.ui.set_zoom('200%'); root.update()
                self.assertLessEqual(app.start_button.winfo_rootx()+app.start_button.winfo_width(),root.winfo_rootx()+root.winfo_width())
                self.assertEqual(app.court_list.curselection(), (1,))
        finally:
            app.close(); app.worker_thread.join(timeout=5)

    def test_layout_reflows_and_lists_grow_on_large_window(self):
        root = create_root(); app = App(root)
        try:
            root.geometry('2400x1500+0+0'); root.update()
            self.assertEqual(app.ui.layout_mode, 'wide')
            wide = app.court_list.winfo_width()
            root.geometry('1500x1160+0+0'); root.update()
            self.assertEqual(app.ui.layout_mode, 'stacked')
            self.assertGreater(app.court_list.winfo_width(), 100)
            self.assertGreater(wide, 100)
            self.assertTrue(app.start_button.winfo_ismapped())
            app.ui.area.canvas.yview_moveto(1);root.update()
            self.assertGreater(app.ui.area.canvas.yview()[0], 0)
        finally:
            app.close(); app.worker_thread.join(timeout=5)


if __name__ == '__main__': unittest.main()
