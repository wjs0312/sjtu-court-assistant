import tempfile
import unittest
from pathlib import Path
from booking_app import App, create_root


class PreferenceUITests(unittest.TestCase):
    def test_mode_toggle_changes_summary_without_changing_selected_times(self):
        root=create_root();app=App(root)
        try:
            app.slots=['20:00-21:00','21:00-22:00']
            app.slot_list.insert('end',*app.slots);app.slot_list.selection_set(0,1)
            app.loaded_identity=app.identity()
            app.update_selection_summary()
            self.assertIn('任选一小时',app.selection_summary.get())
            app.time_mode.set('连续两段')
            self.assertIn('同一场地连续两小时：20:00-22:00',app.selection_summary.get())
            self.assertEqual(app.slot_list.curselection(),(0,1))
            app.time_mode.set('任选一段')
            self.assertIn('20:00-21:00 或 21:00-22:00',app.selection_summary.get())
            app.slot_list.selection_clear(1);app.time_mode.set('连续两段')
            self.assertIn('恰好选择两个相邻时段',app.selection_summary.get())
            app.ui.set_busy(True)
            self.assertEqual(str(app.slot_list['state']),'disabled')
            app.ui.set_busy(False)
            self.assertEqual(str(app.slot_list['state']),'normal')
        finally:
            app.close();app.worker_thread.join(timeout=5)


if __name__=='__main__':unittest.main()
