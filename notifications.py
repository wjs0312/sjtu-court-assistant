"""微信通知；与预约流程独立，发送失败不会导致重新下单。"""
import json
import logging
import os
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def send(title, body, key=None):
    key = (key or os.environ.get('SERVERCHAN_SENDKEY', '')).strip()
    if not key:
        logging.info('未配置微信通知；%s：%s', title, body)
        return False
    if not re.fullmatch(r'SCT[A-Za-z0-9]+', key):
        raise ValueError('请使用 Server酱 Turbo 的 SCT 开头 SendKey。')
    request = Request(f'https://sctapi.ftqq.com/{key}.send',
                      data=urlencode({'title': title[:32], 'desp': body}).encode(), method='POST')
    for attempt in range(3):
        try:
            with urlopen(request, timeout=8) as response:
                result = json.load(response)
            if result.get('code') == 0:
                logging.info('通知服务已接受消息：%s', title)
                return True
        except Exception:
            # 不记录异常文本，其中可能包含带密钥的请求 URL。
            pass
        if attempt < 2:
            time.sleep(1 + attempt)
    logging.warning('微信通知发送失败，请查看本地结果；未再次执行预约。')
    return False
