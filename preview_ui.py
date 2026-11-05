"""开发时生成界面预览，不接触校园网络。"""
from pathlib import Path
import sys
import tkinter as tk
from PIL import ImageGrab
import badminton_bot as bot
from booking_app import App, create_root
from notification_dialog import NotificationDialog

root = create_root()
app = App(root)
app.courts=['场地1', '场地2', '场地3', '场地4', '场地5']
app.court_list.insert('end', *app.courts)
app.court_list.selection_set(1)
app.slots=['18:00-19:00', '19:00-20:00', '20:00-21:00', '21:00-22:00']
app.slot_list.insert('end', *app.slots)
app.slot_list.selection_set(2,3)
app.loaded_identity=app.identity()
if '--continuous' in sys.argv:app.time_mode.set('连续两段')
app.update_selection_summary()
root.update()
root.geometry('+0+0')
root.attributes('-topmost', True)
root.lift()
target = root
if '--binding' in sys.argv:
    target = NotificationDialog(app).window
    target.geometry('+20+20')
    target.attributes('-topmost', True)
    target.lift()
    root.update()
root.after(800, root.quit)
root.mainloop()
root.update()
folder = bot.ROOT / 'screenshots'; folder.mkdir(exist_ok=True)
box = (target.winfo_rootx(), target.winfo_rooty(), target.winfo_rootx() + target.winfo_width(), target.winfo_rooty() + target.winfo_height())
filename = 'wechat-binding-preview.png' if '--binding' in sys.argv else 'ui-preview.png'
if '--continuous' in sys.argv:filename='ui-continuous-preview.png'
ImageGrab.grab(bbox=box).save(folder / filename)
print(folder / filename)
app.close()
app.worker_thread.join(timeout=5)
