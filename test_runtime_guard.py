import logging
import queue
import tempfile
import unittest
from pathlib import Path
from runtime_guard import latest_venue_responses, rotating_handler, append_log
from booking_app import QueueLog, create_root
from threading import Event
from unittest.mock import patch
import watcher


class PageEvents:
    def __init__(self):self.handlers=[]
    def on(self,event,handler):self.handlers.append(handler)
    def remove_listener(self,event,handler):self.handlers.remove(handler)
    def response(self,value):
        class Response:
            url='https://sports.sjtu.edu.cn/manage/venue/queryVenueById'
            status=200
            def json(self):return {'code':0,'data':value}
        for callback in self.handlers[:]:callback(Response())


class RuntimeTests(unittest.TestCase):
    def test_response_cache_is_bounded_and_listener_removed_on_error(self):
        page=PageEvents()
        with self.assertRaises(RuntimeError):
            with latest_venue_responses(page) as cache:
                for i in range(20000):page.response(i)
                self.assertEqual(len(cache),1)
                self.assertEqual(cache[-1]['data'],19999)
                raise RuntimeError('interrupted')
        self.assertEqual(page.handlers,[])

    def test_log_flood_cannot_block_worker_or_grow_queue(self):
        events=queue.Queue(maxsize=50);handler=QueueLog(events)
        record=logging.LogRecord('test',logging.INFO,'',1,'no slot',(),None)
        for _ in range(10000):handler.emit(record)
        self.assertLessEqual(events.qsize(),50)

    def test_file_logs_rotate_with_fixed_backup_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'run.log'
            handler=rotating_handler(path,max_bytes=512,backups=3)
            for _ in range(500):handler.emit(logging.LogRecord('test',logging.INFO,'',1,'x'*120,(),None))
            handler.close()
            files=list(Path(directory).iterdir())
            self.assertLessEqual(len(files),4)
            self.assertTrue(all(f.stat().st_size<=512 for f in files))

    def test_gui_retains_only_recent_lines_and_characters(self):
        import tkinter as tk
        root=create_root();widget=tk.Text(root)
        try:
            append_log(widget,'\n'.join('line '+str(i) for i in range(20000)))
            self.assertLessEqual(int(widget.index('end-1c').split('.')[0]),1001)
            self.assertIn('line 19999',widget.get('1.0','end'))
            append_log(widget,'x'*300000)
            self.assertLessEqual(len(widget.get('1.0','end-1c')),200000)
        finally:root.destroy()

    def test_twenty_thousand_empty_rounds_do_not_generate_twenty_thousand_logs(self):
        rounds=0
        def attempt():
            nonlocal rounds
            rounds+=1
            return 'unavailable'
        with patch('watcher.logging.info') as heartbeat, patch('watcher.memory_summary',return_value='test memory'):
            result=watcher.monitor(attempt,lambda:rounds<20000,Event(),lambda seconds:None,lambda result:None,5)
            self.assertEqual((result,rounds),('expired',20000))
            self.assertLess(heartbeat.call_count,10)


if __name__=='__main__':unittest.main()
