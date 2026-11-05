"""预约意图与网站项目名；GUI 与执行端使用同一份规则。"""
from urllib.parse import quote, urlsplit, urlunsplit


def site_sport(name):
    return {'学生中心健身房': '健身房'}.get(name, name)


def canonical_detail_url(url, sport):
    if not sport: return url
    parsed = urlsplit(url)
    parts = parsed.fragment.split('/')
    if len(parts) == 6 and parts[1] == 'apointmentDetails':
        parts[4] = quote(quote(site_sport(sport), safe=''), safe='')
        return urlunsplit(parsed._replace(fragment='/'.join(parts)))
    return url


def time_groups(mode, slots):
    if not slots: raise ValueError('请选择至少一个目标时段。')
    if mode == '任选一段': return [[slot] for slot in slots]
    if mode != '连续两段': raise ValueError('请选择预约方式：任选一段或连续两段。')
    if len(slots) != 2 or slots[0].split('-')[-1] != slots[1].split('-')[0]:
        raise ValueError('连续两段模式必须恰好选择两个相邻时段，例如20–21点和21–22点。')
    return [list(slots)]


def selection_text(mode, slots):
    time_groups(mode, slots)
    if mode == '连续两段':
        return f'同一场地连续两小时：{slots[0].split("-")[0]}-{slots[-1].split("-")[-1]}。两段必须同时可约，不会单独预约其中一段。'
    return '任选一小时：' + ' 或 '.join(slots) + '。只预约其中一段，命中后停止。'
