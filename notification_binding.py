"""记录通知绑定状态；服务接受请求与手机确认收件分别处理。"""
import hashlib
import re


class NotificationBinding:
    def __init__(self, key='', receipt=''):
        self.key = key.strip()
        self.receipt = receipt
        self.can_confirm = False

    def set_key(self, key):
        key = key.strip()
        if key != self.key:
            self.receipt = ''
            self.can_confirm = False
        self.key = key

    def validate(self):
        if not re.fullmatch(r'SCT[A-Za-z0-9]+', self.key):
            raise ValueError('请复制官方页面上以 SCT 开头的完整推送凭证（SendKey）。')
        return self.key

    @property
    def confirmed(self):
        return bool(self.key and self.receipt == hashlib.sha256(self.key.encode()).hexdigest())

    def test_result(self, key, accepted):
        if key != self.key:
            return False
        self.can_confirm = bool(accepted)
        if not accepted:
            self.receipt = ''
        return True

    def confirm_received(self):
        if not self.can_confirm:
            raise ValueError('请先成功发送测试通知，并确认手机实际收到。')
        self.receipt = hashlib.sha256(self.key.encode()).hexdigest()
