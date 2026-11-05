"""长时间运行保护：有限缓存、滚动日志与内存诊断。"""
from collections import deque
from contextlib import contextmanager
import logging
from logging.handlers import RotatingFileHandler
import os


@contextmanager
def latest_venue_responses(page):
    cache=deque(maxlen=1)
    def capture(response):
        if 'queryVenueById' not in response.url:return
        try:payload=response.json()
        except Exception:
            logging.warning('场馆接口返回非 JSON 响应（HTTP %s）。',response.status)
            return
        if isinstance(payload,dict):cache.append(payload)
    page.on('response',capture)
    try:yield cache
    finally:
        page.remove_listener('response',capture)
        cache.clear()


def rotating_handler(path,max_bytes=5*1024*1024,backups=3):
    handler=RotatingFileHandler(path,maxBytes=max_bytes,backupCount=backups,encoding='utf-8',errors='replace')
    handler.setLevel(logging.INFO)
    return handler


def append_log(widget,text,max_lines=1000,max_chars=200000):
    follow=widget.yview()[1]>=0.99
    widget.configure(state='normal')
    widget.insert('end',(text+'\n')[-max_chars:])
    lines=int(widget.index('end-1c').split('.')[0])
    if lines>max_lines:widget.delete('1.0',f'{lines-max_lines+1}.0')
    count=widget.count('1.0','end-1c','chars')[0]
    if count>max_chars:widget.delete('1.0',f'1.0 + {count-max_chars} chars')
    if follow:widget.see('end')
    widget.configure(state='disabled')


def memory_summary():
    try:
        import psutil
        parent=psutil.Process(os.getpid())
        own=parent.memory_info().rss
        total=own;count=1
        for child in parent.children(recursive=True):
            try:total+=child.memory_info().rss;count+=1
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        return f'主程序RSS {own/1024**2:.1f} MB；进程树RSS合计 {total/1024**2:.1f} MB（{count}个进程）'
    except Exception:return '内存采样暂不可用'
