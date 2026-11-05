from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from booking_preferences import site_sport, canonical_detail_url
from app_platform import current_paths
from runtime_guard import latest_venue_responses, rotating_handler

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


ROOT, RESOURCE_ROOT = current_paths()


class ConfigError(RuntimeError):
    pass


class BookingError(RuntimeError):
    pass


@dataclass
class Runtime:
    config: dict[str, Any]
    variables: dict[str, str]
    dry_run: bool
    deadline: float | None = None
    submitted: bool = False


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在：{path}。请复制 config.example.toml 为 config.toml 后修改。")
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    for section in ("browser", "schedule", "target", "site", "success"):
        if section not in cfg:
            raise ConfigError(f"配置缺少 [{section}] 段")
    if "example.edu" in cfg["site"].get("booking_url", ""):
        raise ConfigError("请先把 config.toml 中的示例网址替换为学校预约系统网址。")
    detail_url = str(cfg["site"].get("detail_url", ""))
    if detail_url and "/apointmentDetails/" not in detail_url:
        raise ConfigError("site.detail_url 必须是包含 /apointmentDetails/ 的详情页网址。")
    return cfg


BROWSER_CHOICES = {
    "1": ("Edge", "edge", "chromium", "msedge"),
    "2": ("Chrome", "chrome", "chromium", "chrome"),
    "3": ("Chromium", "chromium", "chromium", None),
    "4": ("Firefox", "firefox", "firefox", None),
    "5": ("WebKit", "webkit", "webkit", None),
}


def choose_browser(cfg: dict[str, Any], override: str | None = None) -> None:
    """在启动浏览器前让用户选择引擎；命令行参数可用于无人值守运行。"""
    aliases = {
        "edge": "1", "msedge": "1", "chrome": "2", "chromium": "3",
        "firefox": "4", "webkit": "5",
    }
    choice = aliases.get((override or "").lower())
    if choice is None and sys.stdin.isatty():
        print("\n请选择本次抢场使用的浏览器：")
        for key, (label, _, _, _) in BROWSER_CHOICES.items():
            print(f"  {key}. {label}")
        default = aliases.get(str(cfg["browser"].get("channel", "edge")).lower(), "1")
        choice = input(f"输入编号（默认 {default}）：").strip() or default
    choice = choice or aliases.get(str(cfg["browser"].get("channel", "edge")).lower(), "1")
    if choice not in BROWSER_CHOICES:
        raise ConfigError("浏览器选择无效，请选择 edge/chrome/chromium/firefox/webkit。")
    label, profile, engine, channel = BROWSER_CHOICES[choice]
    cfg["browser"]["profile"] = profile
    cfg["browser"]["engine"] = engine
    if channel:
        cfg["browser"]["channel"] = channel
    else:
        cfg["browser"].pop("channel", None)
    logging.info("本次使用浏览器：%s", label)


def auth_paths(cfg: dict[str, Any]) -> tuple[Path, Path]:
    """按浏览器隔离登录状态，避免把 Edge 会话误用于其他浏览器。"""
    profile = str(cfg["browser"].get("profile") or cfg["browser"].get("channel") or "chromium")
    if profile == "msedge":
        profile = "edge"
    state_base = ROOT / cfg["site"].get("auth_state", ".auth/state.json")
    session_base = ROOT / cfg["site"].get("session_storage", ".auth/session_storage.json")
    return (
        state_base.parent / profile / state_base.name,
        session_base.parent / profile / session_base.name,
    )


def existing_auth_paths(cfg: dict[str, Any]) -> tuple[Path, Path]:
    """Edge 首次升级时兼容旧的 `.auth/state.json`，其他浏览器必须使用自己的会话。"""
    state, session = auth_paths(cfg)
    if state.exists():
        return state, session
    if cfg["browser"].get("profile") == "edge":
        legacy_state = ROOT / cfg["site"].get("auth_state", ".auth/state.json")
        legacy_session = ROOT / cfg["site"].get("session_storage", ".auth/session_storage.json")
        if legacy_state.exists():
            return legacy_state, legacy_session
    return state, session


def parse_multi_choice(raw: str, values: list[str], default_all: bool = False) -> list[str]:
    raw = raw.strip()
    if not raw:
        return list(values) if default_all else ([values[0]] if values else [])
    selected: list[str] = []
    for part in re.split(r"[\s,，;；]+", raw):
        if not part:
            continue
        try:
            value = values[int(part.strip()) - 1]
        except (ValueError, IndexError) as e:
            raise ConfigError(f"无效编号：{part}") from e
        if value not in selected:
            selected.append(value)
    return selected


def discover_grid_options(page: Page) -> tuple[list[str], list[str]]:
    """从当前详情页读取场地列和时段；适用于共享同一网格组件的各运动项目。"""
    data = page.evaluate(
        """() => [...document.querySelectorAll('body *')]
          .filter(e => e.children.length === 0 && e.offsetParent !== null)
          .map(e => (e.textContent || '').trim()).filter(Boolean).slice(0, 3000)"""
    )
    courts: list[str] = []
    explicit_slots: list[str] = []
    time_points: list[str] = []
    for text in data:
        if re.fullmatch(r"(?:场地|球场|区域|器械)\s*\d+[A-Za-z]?", text) and text not in courts:
            courts.append(text)
        if re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", text):
            if text not in time_points:
                time_points.append(text)
        elif re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d\s*[-~至–—]\s*(?:[01]?\d|2[0-3]):[0-5]\d", text):
            normalized = re.sub(r"\s*[-~至–—]\s*", "-", text)
            if normalized not in explicit_slots:
                explicit_slots.append(normalized)
    # 网格通常只显示行边界 07:00、08:00……22:00；相邻边界才是一个预约时段。
    slots = explicit_slots or [
        f"{time_points[i]}-{time_points[i + 1]}" for i in range(len(time_points) - 1)
    ]
    if not slots and time_points:
        slots = list(time_points)
    return courts, slots


def wait_for_grid_options(page: Page, timeout_ms: int = 12000) -> tuple[list[str], list[str]]:
    """等待预约网格完整渲染；场馆接口先返回时，表头可能还没插入 DOM。"""
    deadline = time.monotonic() + timeout_ms / 1000
    latest: tuple[list[str], list[str]] = ([], [])
    while time.monotonic() < deadline:
        latest = discover_grid_options(page)
        if latest[1] and latest[0]:
            return latest
        page.wait_for_timeout(150)
    return latest


def parse_time_preferences(raw: str, slots: list[str]) -> list[list[str]]:
    """解析单时段及连续双时段偏好，如 `(13,14),15`。"""
    raw = raw.strip()
    if not raw:
        return [[slots[0]]] if slots else []
    normalized = raw.translate(str.maketrans({"（": "(", "）": ")", "，": ",", "；": ";"}))
    tokens = re.findall(r"\([^()]+\)|\d+", normalized)
    residue = re.sub(r"\([^()]+\)|\d+|[\s,;]+", "", normalized)
    if residue or not tokens:
        raise ConfigError(f"无效时段偏好格式：{raw}")
    groups: list[list[str]] = []
    for token in tokens:
        numbers = [int(value) for value in re.findall(r"\d+", token)]
        if token.startswith("("):
            if len(numbers) != 2 or numbers[1] != numbers[0] + 1:
                raise ConfigError(f"连续时段必须是相邻的两个编号，例如 (13,14)：{token}")
        elif len(numbers) != 1:
            raise ConfigError(f"无效时段编号：{token}")
        try:
            group = [slots[number - 1] for number in numbers]
        except IndexError as e:
            raise ConfigError(f"时段编号超出范围：{token}") from e
        if group not in groups:
            groups.append(group)
    return groups


def load_venue_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    catalog_path = path or (ROOT / "venue_catalog.json")
    if not catalog_path.exists():
        raise ConfigError("未找到 venue_catalog.json，请先运行：python venue_catalog.py")
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        entries = data["entries"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        raise ConfigError(f"场馆目录损坏，无法读取：{catalog_path}") from e
    valid = [
        row for row in entries
        if isinstance(row, dict) and row.get("sport") and row.get("venue")
        and "/apointmentDetails/" in str(row.get("detail_url", ""))
    ]
    if not valid:
        raise ConfigError("场馆目录为空，请重新运行：python venue_catalog.py")
    return valid


def choose_catalog_entries(
    entries: list[dict[str, Any]],
    used: set[tuple[str, str]],
    max_count: int,
) -> list[dict[str, Any]]:
    sports = list(dict.fromkeys(str(row["sport"]) for row in entries))
    print("\n运动项目：")
    for i, sport in enumerate(sports, 1):
        count = sum(1 for row in entries if row["sport"] == sport)
        print(f"  {i:2}. {sport}（{count} 个场馆）")
    sport_values = parse_multi_choice(
        input("选择运动项目编号（同一项目只输入一次；下一步可多选场馆）："), sports
    )
    if not sport_values:
        raise ConfigError("必须选择运动项目。")
    sport = sport_values[0]
    venues = [row for row in entries if row["sport"] == sport]
    print(f"\n{sport}可预约场馆：")
    for i, row in enumerate(venues, 1):
        marker = "（已选）" if (sport, str(row["venue_id"])) in used else ""
        print(f"  {i:2}. {row.get('campus', '')} · {row['venue']}{marker}")
    raw = input(
        f"选择场馆编号，可多选（用空格或逗号分隔，本轮最多 {max_count} 个）："
    ).strip()
    selected_rows = parse_multi_choice(raw, venues)
    if not selected_rows:
        raise ConfigError("必须至少选择一个场馆。")
    if len(selected_rows) > max_count:
        raise ConfigError(f"本轮最多还能选择 {max_count} 个场馆。")
    for selected in selected_rows:
        key = (sport, str(selected["venue_id"]))
        if key in used:
            raise ConfigError(f"目标重复：{sport} / {selected['venue']}")
    for selected in selected_rows:
        used.add((sport, str(selected["venue_id"])))
    return selected_rows


def interactive_targets(
    context: BrowserContext,
    cfg: dict[str, Any],
    count: int,
) -> list[tuple[Page, dict[str, Any]]]:
    """从本地实时目录选择详情页，用户只需选择项目、场馆、场地和时段。"""
    results: list[tuple[Page, dict[str, Any]]] = []
    entries = load_venue_catalog()
    used: set[tuple[str, str]] = set()
    print(f"\n已加载场馆目录：{len(entries)} 个项目/场馆组合。脚本会直接打开详情页。")
    while len(results) < count:
        remaining = count - len(results)
        print(f"\n========== 选择预约目标（已选 {len(results)}/{count}） ==========")
        selected_batch = choose_catalog_entries(entries, used, remaining)
        for selected in selected_batch:
            index = len(results) + 1
            page = context.new_page()
            target_cfg = copy.deepcopy(cfg)
            target_cfg["site"]["detail_url"] = str(selected["detail_url"])
            target_cfg["target"]["sport"] = str(selected["sport"])
            target_cfg["target"]["venue"] = str(selected["venue"])
            timezone = ZoneInfo(cfg["browser"].get("timezone", "Asia/Shanghai"))
            preview_rt = Runtime(
                target_cfg,
                build_variables(target_cfg, datetime.now(timezone)),
                True,
            )
            open_sjtu_detail(page, preview_rt, 30000)
            if target_cfg['target'].get('date'):
                from watcher import select_date
                select_date(page, preview_rt)
            courts, slots = wait_for_grid_options(page)
            print(
                f"\n目标 {index}/{count}：{selected.get('campus', '')} · "
                f"{selected['venue']} · {selected['sport']}"
            )
            if courts:
                print("可选场地（一个序号对应一个具体场地）：")
                for i, court in enumerate(courts, 1):
                    print(f"  {i:2}. {court}")
                target_cfg["target"]["court_priority"] = parse_multi_choice(
                    input("输入场地编号，可多选（用空格或逗号分隔；留空表示全部）："), courts, default_all=True
                )
            else:
                print("未识别到编号场地，将按页面上第一个可预约单元处理（健身房等项目可能没有场地列）。")
                target_cfg["target"]["court_priority"] = []
            if slots:
                print("可选时段（一个序号对应一个完整时间段）：")
                for i, slot in enumerate(slots, 1):
                    print(f"  {i:2}. {slot}")
                preference_raw = input(
                    "输入时段偏好（单个如 13；连续两小时如 (13,14)；各偏好用逗号分隔）："
                )
                groups = parse_time_preferences(preference_raw, slots)
                target_cfg["target"]["time_slot_groups"] = groups
                target_cfg["target"]["time_slot_priority"] = [slot for group in groups for slot in group]
            results.append((page, target_cfg))
            logging.info("已添加目标 %s：%s / %s", index, selected["sport"], selected["venue"])
    return results


def setup_logging() -> Path:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    path = log_dir / f"run-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[rotating_handler(path), logging.StreamHandler(sys.stdout)],
    )
    return path


def build_variables(cfg: dict[str, Any], now: datetime) -> dict[str, str]:
    explicit_date = cfg['target'].get('date')
    target_date = (datetime.strptime(explicit_date, '%Y-%m-%d').date() if explicit_date
                   else now.date() + timedelta(days=int(cfg["schedule"]["days_ahead"])))
    target = cfg["target"]
    site = cfg["site"]
    return {
        "target_date": target_date.isoformat(),
        "target_date_cn": f"{target_date.month}月{target_date.day}日",
        "target_date_cn_zero": f"{target_date.month:02d}月{target_date.day:02d}日",
        "target_date_compact": target_date.strftime("%Y%m%d"),
        "venue": str(target.get("venue", "")),
        "court": str(target.get("court", "")),
        "time_slot": str(target.get("time_slot", "")),
        "start_time": str(target.get("time_slot", "")).split("-")[0].strip(),
        "booking_url": str(site["booking_url"]),
        "detail_url": canonical_detail_url(str(site.get("detail_url", site["booking_url"])), target.get('sport', '')),
        "login_url": str(site["login_url"]),
    }


def render(value: Any, variables: dict[str, str]) -> str:
    if value is None:
        return ""
    try:
        return str(value).format_map(variables)
    except KeyError as e:
        raise ConfigError(f"步骤引用了未知变量：{e.args[0]}") from e


def screenshot(page: Page, name: str) -> Path:
    folder = ROOT / "screenshots"
    folder.mkdir(exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    path = folder / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{safe}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def perform_step(page: Page, step: dict[str, Any], rt: Runtime, index: int) -> None:
    action = step.get("action", "").lower()
    selector = render(step.get("selector"), rt.variables)
    value = render(step.get("value"), rt.variables)
    desc = step.get("description") or f"步骤 {index}: {action}"
    timeout = int(step.get("timeout_ms", 5000))
    logging.info("执行：%s", desc)

    pause_for_captcha(page, rt.config)

    if step.get("final_submit") and rt.dry_run:
        logging.warning("dry-run：已到最终提交步骤，未点击。")
        screenshot(page, "dry-run-before-submit")
        return
    if step.get("final_submit") and rt.submitted:
        raise BookingError("提交锁已生效，拒绝再次点击最终提交。")

    if action == "goto":
        page.goto(value, wait_until="domcontentloaded", timeout=max(timeout, 30000))
    elif action == "click":
        page.locator(selector).click(timeout=timeout)
    elif action == "click_if_visible":
        candidate = page.locator(selector)
        try:
            candidate.wait_for(state="visible", timeout=timeout)
            if candidate.count() == 1:
                candidate.click(timeout=timeout)
            else:
                logging.info("可选步骤匹配数量不是 1，跳过：%s", desc)
        except PlaywrightTimeoutError:
            logging.info("可选步骤未出现，跳过：%s", desc)
    elif action == "fill":
        page.locator(selector).fill(value, timeout=timeout)
    elif action == "select":
        page.locator(selector).select_option(value=value, timeout=timeout)
    elif action == "check":
        page.locator(selector).check(timeout=timeout)
    elif action == "press":
        page.locator(selector).press(value, timeout=timeout)
    elif action == "wait":
        page.wait_for_timeout(int(step.get("milliseconds", 500)))
    elif action == "reload":
        page.reload(wait_until="domcontentloaded", timeout=timeout)
    elif action == "expect":
        page.locator(selector).wait_for(state=step.get("state", "visible"), timeout=timeout)
    elif action == "wait_url_contains":
        page.wait_for_url(f"**{value}**", timeout=timeout, wait_until="domcontentloaded")
    elif action == "sjtu_select_slot":
        select_sjtu_slot(page, rt, timeout)
    elif action == "sjtu_open_detail":
        open_sjtu_detail(page, rt, timeout)
    elif action == "sjtu_enter_venue":
        enter_sjtu_venue(page, rt, timeout)
    else:
        raise ConfigError(f"不支持的 action：{action}")

    if step.get("final_submit"):
        rt.submitted = True
        logging.info("最终提交按钮已点击，提交锁已生效。")
        page.wait_for_timeout(250)
        pause_for_captcha(page, rt.config)


def pause_for_captcha(page: Page, cfg: dict[str, Any]) -> None:
    selector = cfg.get("login", {}).get("captcha_selector", "")
    visible = False
    if selector:
        items = page.locator(selector)
        for i in range(items.count()):
            if items.nth(i).is_visible():
                visible = True
                break
    if not visible:
        labels = page.get_by_text("验证码", exact=False)
        for i in range(min(labels.count(), 10)):
            if labels.nth(i).is_visible():
                visible = True
                break
    if visible:
        path = screenshot(page, "captcha-manual-action-required")
        logging.warning("检测到验证码，需要人工填写。截图：%s", path)
        print("\a检测到验证码：请在浏览器中人工完成，然后回到终端。")
        manual = cfg.get('_manual_action')
        if manual:
            manual('检测到验证码，请在浏览器完成后点击“已完成，继续”。')
        else:
            input("完成后按 Enter 继续...")


def wait_for_sjtu_detail(page: Page, timeout: int) -> None:
    """确认详情页路由和主体都已加载，避免在空壳页面上继续。"""
    page.wait_for_url("**/apointmentDetails/**", timeout=timeout, wait_until="domcontentloaded")
    page.locator("#apointmentDetails").wait_for(state="visible", timeout=timeout)


def select_sjtu_sport(page: Page, rt: Runtime, timeout: int = 15000) -> None:
    """每次进入或刷新后核对网站实际项目，不凭详情 URL 判断成功。"""
    requested = rt.config.get('target', {}).get('sport', '')
    if not requested: return
    wanted = site_sport(requested)
    tabs = page.locator('#apointmentDetails .lists > .el-tabs').first.locator('.el-tabs__item')
    try:
        tabs.first.wait_for(state='visible', timeout=timeout)
        match = tabs.filter(has_text=re.compile(r'^\s*' + re.escape(wanted) + r'\s*$'))
        if match.count() != 1:
            raise BookingError(f'场馆中无法唯一找到“{wanted}”项目，已停止读取和预约，避免误选其他项目。')
        tab = match.first
        if 'is-active' not in (tab.get_attribute('class') or '').split():
            with page.expect_response(lambda r: 'queryFieldSituation' in r.url, timeout=timeout) as loaded:
                tab.click(timeout=timeout)
            payload = loaded.value.json()
            if not isinstance(payload, dict) or payload.get('code') != 0:
                raise BookingError(f'“{wanted}”场次接口未成功返回，已停止扫描。')
        active = tabs.filter(has_text=re.compile(r'^\s*' + re.escape(wanted) + r'\s*$')).locator('xpath=self::*[contains(concat(" ",normalize-space(@class)," ")," is-active ")]')
        active.wait_for(state='visible', timeout=timeout)
        page.get_by_text('拼命加载中', exact=False).wait_for(state='hidden', timeout=timeout)
    except PlaywrightTimeoutError as exc:
        raise BookingError(f'未能确认“{wanted}”项目已选中并加载，已停止扫描。请检查网站页面或重新读取。') from exc
    rt.variables['selected_sport'] = wanted
    logging.debug('已确认网站当前项目：%s', wanted)


def open_sjtu_detail(page: Page, rt: Runtime, timeout: int) -> None:
    """使用固定详情页链接直达目标场馆，并在准备阶段处理失效登录。"""
    detail_url = rt.variables.get("detail_url", "")
    if "/apointmentDetails/" not in detail_url:
        raise ConfigError("请在 [site] 中配置目标场馆的 detail_url。")

    attempt_timeout = max(timeout, 30000)
    with latest_venue_responses(page) as venue_payloads:
        for attempt in range(1, 4):
            logging.info("直达目标详情页（第 %s/3 次）。", attempt)
            venue_payloads.clear()
            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=attempt_timeout)
            except PlaywrightError as error:
                logging.warning(
                    "详情页导航失败，将自动重试（第 %s/3 次）：%s",
                    attempt,
                    str(error).splitlines()[0],
                )
                time.sleep(0.3)
                continue
            pause_for_captcha(page, rt.config)
    
            login_button = page.locator(
                ".el-dialog__wrapper:visible button:has-text('校内人员登录')"
            )
            try:
                login_button.wait_for(state="visible", timeout=1200)
                logging.warning("详情页要求重新认证，正在进入校内人员登录。")
                login_button.click(timeout=5000)
                page.wait_for_timeout(2000)
                pause_for_captcha(page, rt.config)
                try:
                    page.wait_for_url("**sports.sjtu.edu.cn/pc/**", timeout=attempt_timeout)
                except PlaywrightTimeoutError:
                    logging.warning("统一认证尚未返回预约系统，将重新打开固定详情页。")
                continue
            except PlaywrightTimeoutError:
                pass
    
            try:
                wait_for_sjtu_detail(page, timeout)
                response_deadline = time.monotonic() + min(timeout / 1000, 15)
                while not venue_payloads and time.monotonic() < response_deadline:
                    page.wait_for_timeout(100)
                if not venue_payloads:
                    logging.warning("详情页主体已出现，但场馆详情接口未返回有效 JSON，将重新加载。")
                    continue
                payload = venue_payloads[-1]
                if payload.get("code") == 401:
                    raise BookingError(
                        "登录会话已过期，场馆接口返回 401。请先运行：python badminton_bot.py login"
                    )
                if payload.get("code") != 0 or not payload.get("data"):
                    logging.warning("场馆详情接口未返回有效数据：%s", payload.get("msg", payload))
                    continue
                logging.info("已确认固定详情页和场馆数据加载完成：%s", page.url)
                select_sjtu_sport(page, rt, timeout)
                return
            except PlaywrightTimeoutError:
                logging.warning("详情页主体尚未加载完成，将重新直达。")
    
        path = screenshot(page, "detail-page-timeout")
        raise BookingError(f"固定详情页连续 3 次未能加载。截图：{path}")


def enter_sjtu_venue(page: Page, rt: Runtime, timeout: int) -> None:
    """反复进入气膜体育中心，并以详情页 URL 作为成功确认。"""
    detail_part = "/apointmentDetails/"
    schedule = rt.config.get("schedule", {})
    retry_seconds = int(schedule.get("venue_enter_retry_seconds", 230))
    retry_interval_ms = int(schedule.get("venue_enter_retry_interval_ms", 1500))
    attempt_timeout = min(timeout, 10000)
    retry_deadline = time.monotonic() + retry_seconds
    attempts = 0

    def click_path() -> None:
        badminton = page.get_by_text("羽毛球", exact=True)
        badminton.wait_for(state="visible", timeout=attempt_timeout)
        badminton.click(timeout=attempt_timeout)
        venue = page.get_by_text("气膜体育中心", exact=True)
        venue.wait_for(state="visible", timeout=attempt_timeout)
        venue.click(timeout=attempt_timeout)
        page.wait_for_timeout(500)

    while True:
        attempts += 1
        try:
            if detail_part not in page.url:
                click_path()
            if detail_part in page.url:
                logging.info("已确认进入气膜体育中心详情页（第 %s 次尝试）。", attempts)
                return

            login_button = page.locator(
                ".el-dialog__wrapper:visible button:has-text('校内人员登录')"
            )
            login_button.wait_for(state="visible", timeout=3000)
            login_button.click(timeout=attempt_timeout)
            pause_for_captcha(page, rt.config)
            page.wait_for_url("**sports.sjtu.edu.cn/pc/**", timeout=attempt_timeout)
            page.wait_for_timeout(1000)
        except PlaywrightTimeoutError:
            if detail_part in page.url:
                logging.info("已确认进入气膜体育中心详情页（第 %s 次尝试）。", attempts)
                return

        if time.monotonic() >= retry_deadline:
            path = screenshot(page, "venue-entry-timeout")
            raise BookingError(
                f"连续 {attempts} 次尝试后仍未进入气膜体育中心详情页。截图：{path}"
            )

        logging.warning(
            "第 %s 次未进入气膜体育中心，将刷新预约首页并在 %sms 后重试。",
            attempts,
            retry_interval_ms,
        )
        page.wait_for_timeout(retry_interval_ms)
        try:
            page.goto(
                rt.variables["booking_url"],
                wait_until="domcontentloaded",
                timeout=attempt_timeout,
            )
        except PlaywrightTimeoutError:
            logging.warning("刷新预约首页超时，继续下一次进入尝试。")


def select_sjtu_slot(page: Page, rt: Runtime, timeout: int) -> None:
    """按偏好组遍历场地；连续双时段仅在同一场地两个格子均可用时选择。"""
    target = rt.config["target"]
    time_slots = target.get("time_slot_priority") or [
        target.get("time_slot") or rt.variables.get("time_slot") or rt.variables["start_time"]
    ]
    time_slots = [str(slot).strip() for slot in time_slots if str(slot).strip()]
    if not time_slots:
        raise ConfigError("请配置至少一个时段。")
    groups = target.get("time_slot_groups") or [[slot] for slot in time_slots]
    groups = [[str(slot) for slot in group] for group in groups if group]
    priorities = list(target.get("court_priority") or [])

    def visible_locator(text: str):
        candidates = page.get_by_text(text, exact=True)
        visible = [candidates.nth(i) for i in range(candidates.count()) if candidates.nth(i).is_visible()]
        return visible[0] if len(visible) == 1 else None

    def available(x: float, y: float) -> bool:
        return bool(page.evaluate(
            """([x,y]) => {
              let e=document.elementFromPoint(x,y);
              for(let i=0;e && i<7;i++,e=e.parentElement){
                const s=getComputedStyle(e), m=(s.backgroundColor||'').match(/\\d+/g);
                const c=String(e.className||'').split(/\\s+/);
                if(c.includes('bought-seat')) return false;
                if(c.includes('inner-seat') && !e.disabled && s.pointerEvents!=='none') return true;
                if(m && m.length>=3){
                  const [r,g,b]=m.map(Number);
                  if(b-r>15 && b>=g && !e.disabled && s.pointerEvents!=='none') return true;
                }
              }
              return false;
            }""", [x, y]))

    # 场地表头只读取一次。旧实现会为每个格子在表头和时间行之间来回滚动，明显拖慢一轮扫描。
    court_columns: list[tuple[str, float]] = []
    for court in priorities:
        header = visible_locator(str(court))
        if header is None:
            logging.warning("跳过无法唯一定位的可见场地列：%s", court)
            continue
        header.scroll_into_view_if_needed(timeout=timeout)
        header_box = header.bounding_box()
        if header_box:
            court_columns.append((str(court), header_box["x"] + header_box["width"] / 2))
    if priorities:
        logging.debug("本轮将按顺序遍历 %s 个场地：%s", len(court_columns), ", ".join(x[0] for x in court_columns))

    for group in groups:
        labels = [visible_locator(slot.split("-")[0].strip()) for slot in group]
        if any(label is None for label in labels):
            logging.warning("跳过无法唯一定位的时段组：%s", " + ".join(group))
            continue
        labels[0].scroll_into_view_if_needed(timeout=timeout)

        boxes = [label.bounding_box() for label in labels]
        if any(box is None for box in boxes):
            continue
        for court, x in court_columns:
            points = [(x, box["y"] + box["height"] / 2) for box in boxes]
            states = [available(px, py) for px, py in points]
            if all(states):
                for px, py in points:
                    page.mouse.click(px, py)
                selected_range = group[0].split("-")[0] + "-" + group[-1].split("-")[-1]
                rt.variables["selected_court"] = str(court)
                rt.variables["selected_time_slot"] = selected_range
                rt.variables['selected_slot_count'] = str(len(group))
                rt.variables["selected_start_time"] = group[0].split("-")[0]
                logging.info("已选择 %s %s", court, selected_range)
                return
            logging.debug("%s %s 蓝色状态：%s", court, " + ".join(group), states)

        if not priorities:
            y_values = [box["y"] + box["height"] / 2 for box in boxes]
            width = int(page.evaluate("() => window.innerWidth"))
            for x in range(160, width - 10, 8):
                if all(available(x, y) for y in y_values):
                    for y in y_values:
                        page.mouse.click(x, y)
                    selected_range = group[0].split("-")[0] + "-" + group[-1].split("-")[-1]
                    rt.variables["selected_court"] = "页面首个可用位置"
                    rt.variables["selected_time_slot"] = selected_range
                    rt.variables['selected_slot_count'] = str(len(group))
                    rt.variables["selected_start_time"] = group[0].split("-")[0]
                    logging.info("已选择首个可用位置 %s", selected_range)
                    return
        logging.debug(
            "已扫描时段偏好 %s 的 %s 个场地，暂未找到全部为蓝色的组合。",
            " + ".join(group),
            len(court_columns) if priorities else "全部可见",
        )
    preference_text = "; ".join(" + ".join(group) for group in groups)
    raise PlaywrightTimeoutError(f"时段偏好 {preference_text} 暂未出现满足条件的蓝色场地")


def open_target_payment(page: Page, rt: Runtime) -> None:
    """验证目标待支付订单，并打开支付渠道新标签；不执行付款。"""
    page.goto("https://sports.sjtu.edu.cn/pc/#/Order", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1200)
    date = page.get_by_text(rt.variables["target_date"], exact=True)
    if date.count() != 1:
        raise BookingError("提交后无法唯一定位目标日期的待支付订单。")
    card = date.locator("xpath=ancestor::div[contains(@class,'card')][1]")
    card_text = card.inner_text()
    selected_time_slot = rt.variables.get("selected_time_slot", rt.variables["time_slot"])
    if selected_time_slot not in card_text or "待支付" not in card_text:
        raise BookingError("目标订单未显示为待支付状态，已停止进入支付。")
    pay = card.get_by_text("立即支付", exact=True)
    visible_pay = [pay.nth(i) for i in range(pay.count()) if pay.nth(i).is_visible()]
    if len(visible_pay) != 1:
        raise BookingError(f"目标订单可见的立即支付按钮数量为 {len(visible_pay)}，已停止。")
    visible_pay[0].click()
    page.wait_for_timeout(350)
    buttons = page.locator("button:visible")
    confirms = []
    for i in range(buttons.count()):
        if buttons.nth(i).inner_text().replace(" ", "").strip() == "确定":
            confirms.append(buttons.nth(i))
    if len(confirms) != 1:
        raise BookingError(f"支付确认弹窗的确定按钮数量为 {len(confirms)}，已停止。")
    payment_page = page
    try:
        with page.context.expect_page(timeout=10000) as popup:
            confirms[0].click()
        payment_page = popup.value
        payment_page.wait_for_load_state("domcontentloaded", timeout=30000)
    except PlaywrightTimeoutError:
        # 某些支付渠道在当前标签跳转；确认只点击一次。
        payment_page.wait_for_timeout(1500)
    path = screenshot(payment_page, "payment-page-ready")
    logging.info("已验证待支付订单并打开支付页面：%s", path)
    print("\a已进入支付页面；脚本不会自动付款。")
    input("请自行支付；完成后按 Enter 关闭浏览器...")


def perform_steps(page: Page, steps: list[dict[str, Any]], rt: Runtime) -> None:
    for i, step in enumerate(steps, 1):
        perform_step(page, step, rt, i)


def is_success(page: Page, cfg: dict[str, Any]) -> bool:
    success = cfg["success"]
    url_part = success.get("url_contains", "")
    selector = success.get("selector", "")
    text = success.get("text", "")
    if url_part and url_part in page.url:
        return True
    if selector and page.locator(selector).count() > 0:
        return True
    if text and page.get_by_text(text, exact=False).count() > 0:
        return True
    return False


def release_datetime(cfg: dict[str, Any], now: datetime) -> datetime:
    raw = cfg["schedule"]["release_time"]
    try:
        h, m, s = map(int, raw.split(":"))
    except ValueError as e:
        raise ConfigError("release_time 必须使用 HH:MM:SS 格式") from e
    return now.replace(hour=h, minute=m, second=s, microsecond=0)


def wait_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now(target.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        if remaining > 10:
            logging.info("距离执行还有 %.1f 秒", remaining)
            time.sleep(min(remaining - 5, 30))
        elif remaining > 1:
            time.sleep(0.2)
        else:
            time.sleep(0.01)


def wait_until_with_session_check(pages: list[Page], target: datetime) -> None:
    """等待放场时每 30 秒检查一次登录，避免直到提交时才发现会话过期。"""
    next_check = 0.0
    while True:
        remaining = (target - datetime.now(target.tzinfo)).total_seconds()
        if remaining <= 0:
            return
        now_mono = time.monotonic()
        if now_mono >= next_check:
            for page in pages:
                try:
                    result = page.evaluate(
                        "async () => (await fetch('/system/user/currentUser')).json()"
                    )
                except Exception as e:
                    raise BookingError("放场前登录预检请求失败，请检查网络和预约页面。") from e
                if result.get("code") != 0 or not result.get("data"):
                    raise BookingError(
                        "放场前登录预检失败，会话已失效。请立即重新运行 login，避免到点被登录拦截。"
                    )
            logging.info("放场前登录预检通过（%s 个预约页面）。", len(pages))
            next_check = now_mono + 30
        time.sleep(min(0.2, max(remaining, 0.01)))


def open_context(
    playwright,
    cfg: dict[str, Any],
    require_auth: bool,
    fresh_auth: bool = False,
) -> tuple[Any, BrowserContext]:
    bcfg = cfg["browser"]
    launch_args: dict[str, Any] = {
        "headless": bool(bcfg.get("headless", False)),
        "slow_mo": int(bcfg.get("slow_mo_ms", 0)),
    }
    if bcfg.get("channel"):
        launch_args["channel"] = str(bcfg["channel"])
    engine_name = str(bcfg.get("engine", "chromium"))
    engine = getattr(playwright, engine_name, None)
    if engine is None:
        raise ConfigError(f"Playwright 不支持浏览器引擎：{engine_name}")
    browser = engine.launch(**launch_args)
    state, session_file = existing_auth_paths(cfg)
    kwargs: dict[str, Any] = {"timezone_id": bcfg.get("timezone", "Asia/Shanghai")}
    if state.exists() and not fresh_auth:
        kwargs["storage_state"] = str(state)
    elif require_auth:
        browser.close()
        profile = cfg["browser"].get("profile", engine_name)
        raise BookingError(
            f"未找到 {profile} 浏览器的登录会话，请先运行：python badminton_bot.py login"
        )
    context = browser.new_context(**kwargs)
    if session_file.exists() and not fresh_auth:
        saved = json.loads(session_file.read_text(encoding="utf-8"))
        payload = json.dumps(saved, ensure_ascii=False)
        context.add_init_script(f"""
          (() => {{
            const saved = {payload};
            if (location.origin === saved.origin) {{
              for (const [key, value] of saved.entries) sessionStorage.setItem(key, value);
            }}
          }})();
        """)
    return browser, context


def login(config_path: Path, browser_override: str | None = None) -> int:
    cfg = load_config(config_path)
    choose_browser(cfg, browser_override)
    state, session_file = auth_paths(cfg)
    state.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, context = open_context(p, cfg, require_auth=False, fresh_auth=True)
        page = context.new_page()
        page.goto(cfg["site"]["login_url"], wait_until="domcontentloaded")
        auto_text = cfg.get("login", {}).get("auto_click_text", "")
        if auto_text:
            button = page.get_by_text(auto_text, exact=True)
            if button.count() == 1 and button.is_visible():
                logging.info("自动点击：%s", auto_text)
                button.click()
                page.wait_for_timeout(1500)
        pause_for_captcha(page, cfg)
        print("请在打开的浏览器中手动完成登录和验证码。完成后回到终端按 Enter。")
        input()
        selector = cfg.get("login", {}).get("success_selector", "")
        if selector and page.locator(selector).count() == 0:
            screenshot(page, "login-not-confirmed")
            raise BookingError("未检测到登录成功标志，请检查 login.success_selector。")
        context.storage_state(path=str(state))
        session_file.parent.mkdir(parents=True, exist_ok=True)
        session_data = page.evaluate(
            "() => ({origin: location.origin, entries: Object.entries(sessionStorage)})"
        )
        session_file.write_text(json.dumps(session_data, ensure_ascii=False), encoding="utf-8")
        logging.info("页面会话状态已安全保存到 %s", session_file)
        context.close(); browser.close()
    logging.info("登录会话已保存到 %s", state)
    return 0


def run_selected_targets(cfg: dict[str, Any], dry_run: bool, run_now: bool, count: int) -> int:
    """在同一登录上下文中轮询多个用户选择的详情页，尽量公平地各尝试一次。"""
    tz = ZoneInfo(cfg["browser"].get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)
    release = release_datetime(cfg, now)
    if not run_now and now > release + timedelta(seconds=int(cfg["schedule"]["deadline_seconds"])):
        raise BookingError("今天的放场时间已过。若仅需演练，请增加 --now --dry-run。")
    with sync_playwright() as p:
        browser, context = open_context(p, cfg, require_auth=True)
        selected: list[tuple[Page, dict[str, Any]]] = []
        try:
            selected = interactive_targets(context, cfg, count)
            if not run_now:
                logging.info("%s 个详情页均已预热，等待 %s 放场。", count, release.strftime("%H:%M:%S"))
                wait_until_with_session_check([page for page, _ in selected], release)
            refresh_timeout = int(cfg["schedule"].get("refresh_navigation_timeout_ms", 5000))
            if bool(cfg["schedule"].get("refresh_at_release", True)):
                for page, _ in selected:
                    try:
                        # 多标签先快速发出刷新，只等到请求提交；各页 DOM 由后续步骤分别等待。
                        page.reload(wait_until="commit", timeout=refresh_timeout)
                    except PlaywrightError:
                        logging.warning("某个目标到点刷新遇到导航错误，将直接进入轮询。")

            deadline = time.monotonic() + int(cfg["schedule"]["deadline_seconds"])
            pending = list(selected)
            completed: list[Runtime] = []
            interval = int(cfg["schedule"].get("post_release_refresh_interval_ms", 800))
            max_refreshes = int(cfg["schedule"].get("post_release_max_refreshes", 30))
            refreshes = 0
            while pending and time.monotonic() < deadline:
                next_round: list[tuple[Page, dict[str, Any]]] = []
                for page, target_cfg in pending:
                    rt = Runtime(target_cfg, build_variables(target_cfg, now), dry_run, deadline=deadline)
                    try:
                        perform_steps(page, target_cfg.get("booking_steps", []), rt)
                        if dry_run or rt.submitted or is_success(page, target_cfg):
                            completed.append(rt)
                            logging.info(
                                "目标完成：%s / %s",
                                rt.variables.get("venue"),
                                rt.variables.get(
                                    "selected_time_slot", rt.variables.get("time_slot")
                                ),
                            )
                            screenshot(page, "target-completed")
                            continue
                    except PlaywrightError as e:
                        logging.info("目标本轮暂不可用：%s", e)
                    next_round.append((page, target_cfg))
                pending = next_round
                if pending and time.monotonic() < deadline:
                    if refreshes >= max_refreshes:
                        break
                    context.pages[0].wait_for_timeout(interval)
                    refreshes += 1
                    logging.info(
                        "等待 %sms 后刷新剩余 %s 个目标（第 %s/%s 次刷新）。",
                        interval,
                        len(pending),
                        refreshes,
                        max_refreshes,
                    )
                    for page, _ in pending:
                        try:
                            page.reload(wait_until="commit", timeout=refresh_timeout)
                        except PlaywrightError as error:
                            logging.warning(
                                "轮询刷新遇到临时导航错误，将保留目标继续重试：%s",
                                str(error).splitlines()[0],
                            )
            if pending:
                names = "、".join(x[1]["target"].get("venue", "未知场馆") for x in pending)
                if dry_run:
                    logging.warning(
                        "安全演练完成：页面和扫描流程正常，但当前没有符合条件的蓝色场地。"
                        "未命中目标：%s",
                        names,
                    )
                    return 0
                if refreshes >= max_refreshes and time.monotonic() < deadline:
                    raise BookingError(
                        f"已完成 {max_refreshes} 次刷新，仍有 {len(pending)} 个目标未抢到：{names}"
                    )
                raise BookingError(f"截止时间内仍有 {len(pending)} 个目标未抢到：{names}")
            if dry_run:
                logging.info("多目标 dry-run 完成，共验证 %s 个目标，均未提交。", len(completed))
                return 0
            order_page = selected[0][0]
            order_page.goto(
                "https://sports.sjtu.edu.cn/pc/#/Order",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            path = screenshot(order_page, "multi-target-orders")
            print(f"\a已提交 {len(completed)} 个预约目标。请在浏览器订单页逐项确认并支付；脚本不会自动付款。")
            logging.info("多目标订单页截图：%s", path)
            input("处理完订单后按 Enter 关闭浏览器...")
            return 0
        except Exception:
            if selected:
                screenshot(selected[0][0], "multi-target-failure")
            raise
        finally:
            context.close(); browser.close()


def run(
    config_path: Path,
    dry_run: bool,
    run_now: bool,
    browser_override: str | None = None,
    target_count: int | None = None,
) -> int:
    cfg = load_config(config_path)
    choose_browser(cfg, browser_override)
    if target_count is None and sys.stdin.isatty():
        raw = input("本次要抢几个项目/场馆目标？输入 1-5（直接回车沿用 config.toml 的单目标）：").strip()
        if raw:
            try:
                target_count = int(raw)
            except ValueError as e:
                raise ConfigError("目标数量必须是 1-5 的整数。") from e
            if not 1 <= target_count <= 5:
                raise ConfigError("目标数量必须在 1-5 之间。")
    if target_count:
        return run_selected_targets(cfg, dry_run, run_now, target_count)
    tz = ZoneInfo(cfg["browser"].get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)
    release = release_datetime(cfg, now)
    if not run_now and now > release + timedelta(seconds=int(cfg["schedule"]["deadline_seconds"])):
        raise BookingError("今天的放场时间已过。若仅需演练，请增加 --now --dry-run。")
    rt = Runtime(cfg, build_variables(cfg, now), dry_run)
    logging.info("目标：%s %s %s", rt.variables["target_date"], rt.variables["court"], rt.variables["time_slot"])
    if not run_now:
        prepare_at = release - timedelta(seconds=int(cfg["schedule"].get("open_early_seconds", 90)))
        if datetime.now(tz) < prepare_at:
            logging.info("脚本已启动，将在 %s 打开预约页面。", prepare_at.strftime("%Y-%m-%d %H:%M:%S"))
            wait_until(prepare_at)
    with sync_playwright() as p:
        browser, context = open_context(p, cfg, require_auth=True)
        page = context.new_page()
        try:
            perform_steps(page, cfg.get("prepare_steps", []), rt)
            screenshot(page, "prepared")
            refresh_timeout_ms = int(cfg["schedule"].get("refresh_navigation_timeout_ms", 5000))
            if not run_now:
                logging.info("详情页已预热并保持会话；放场前不再刷新。")
                wait_until_with_session_check([page], release)
            if bool(cfg["schedule"].get("refresh_at_release", True)):
                logging.info("到达放场时间，刷新详情页以获取最新日期和场地状态。")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=refresh_timeout_ms)
                except PlaywrightError:
                    logging.warning("到点刷新遇到导航错误；将继续等待详情页主体和实时数据。")
                detail_timeout_ms = int(cfg["schedule"].get("detail_ready_timeout_ms", 15000))
                try:
                    wait_for_sjtu_detail(page, detail_timeout_ms)
                except PlaywrightTimeoutError:
                    logging.warning("到点刷新后详情页主体未及时出现，将由抢场重试流程继续处理。")
            rt.deadline = time.monotonic() + int(cfg["schedule"]["deadline_seconds"])
            attempts = 0
            max_refreshes = int(cfg["schedule"].get("post_release_max_refreshes", 30))
            post_refresh_ms = int(
                cfg["schedule"].get(
                    "post_release_refresh_interval_ms",
                    cfg["schedule"].get("retry_interval_ms", 800),
                )
            )
            while True:
                attempts += 1
                rt.submitted = False
                try:
                    perform_steps(page, cfg.get("booking_steps", []), rt)
                    if dry_run:
                        logging.info("dry-run 完成，未提交订单。")
                        return 0
                    if rt.submitted and bool(cfg["success"].get("stop_after_submit", False)):
                        path = screenshot(page, "submitted-order")
                        logging.info("订单提交动作完成，开始验证待支付订单。截图：%s", path)
                        if bool(cfg["success"].get("open_payment_after_submit", False)):
                            open_target_payment(page, rt)
                        else:
                            print("\a订单已提交，请在浏览器中确认后续支付状态。")
                            input("按 Enter 后关闭浏览器...")
                        return 0
                    page.wait_for_timeout(500)
                    if is_success(page, cfg):
                        path = screenshot(page, "success-payment-page")
                        logging.info("成功：已进入支付/待支付状态。截图：%s", path)
                        print("\a已抢到场地，请在浏览器中自行完成支付。")
                        input("按 Enter 后关闭浏览器...")
                        return 0
                    # 已点击最终提交但结果不明确，禁止再次下单。
                    if rt.submitted:
                        path = screenshot(page, "submit-result-unknown")
                        raise BookingError(f"订单已提交，但未匹配支付页成功标志。为避免重复下单已停止。截图：{path}")
                except PlaywrightError as e:
                    logging.warning("第 %s 次尝试未找到目标：%s", attempts, e)
                if time.monotonic() >= rt.deadline:
                    if dry_run:
                        logging.warning(
                            "安全演练完成：页面和扫描流程正常，但截止前没有符合条件的蓝色场地。"
                        )
                        return 0
                    raise BookingError("已达到抢场截止时间，未确认成功。")
                if attempts > max_refreshes:
                    if dry_run:
                        logging.warning(
                            "安全演练完成：页面和扫描流程正常，%s 次刷新内没有蓝色场地。",
                            max_refreshes,
                        )
                        return 0
                    raise BookingError(f"12:00 后已完成 {max_refreshes} 次重新刷新，未确认成功。")
                logging.info(
                    "本轮所有备选时段均无蓝色场地；等待 %sms 后进行第 %s/%s 次重新刷新。",
                    post_refresh_ms,
                    attempts,
                    max_refreshes,
                )
                page.wait_for_timeout(post_refresh_ms)
                try:
                    page.reload(wait_until="domcontentloaded", timeout=refresh_timeout_ms)
                except PlaywrightError as error:
                    logging.warning(
                        "12:00 后刷新遇到临时导航错误；将继续重试：%s",
                        str(error).splitlines()[0],
                    )
        except Exception:
            screenshot(page, "failure")
            raise
        finally:
            if not dry_run:
                logging.info("浏览器会话结束。")
            context.close(); browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="上海交大体育场馆定时预约脚本")
    parser.add_argument("command", choices=["login", "run", "check", "watch", "notify-test"], help="登录、运行、演练、蹲场或测试微信通知")
    parser.add_argument("--config", default="config.toml", help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="不点击最终提交")
    parser.add_argument("--now", action="store_true", help="立即运行，不等待 12:00")
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome", "chromium", "firefox", "webkit"],
        help="本次使用的浏览器",
    )
    parser.add_argument("--targets", type=int, choices=range(1, 6), help="交互选择的预约目标数量（1-5）")
    args = parser.parse_args()
    log_path = setup_logging()
    try:
        config_path = (ROOT / args.config).resolve()
        if args.command == 'notify-test':
            import notifications
            return 0 if notifications.send('交大场地助手测试', '请确认微信收到此消息。') else 1
        if args.command == 'watch':
            from watcher import run_watch
            return run_watch(config_path, args.browser, args.dry_run)
        if args.command == "login":
            return login(config_path, args.browser)
        if args.command == "check":
            return run(
                config_path,
                dry_run=True,
                run_now=True,
                browser_override=args.browser,
                target_count=args.targets,
            )
        return run(
            config_path,
            dry_run=args.dry_run,
            run_now=args.now,
            browser_override=args.browser,
            target_count=args.targets,
        )
    except (ConfigError, BookingError, PlaywrightError, ValueError) as e:
        logging.error("%s", e)
        logging.error("日志：%s", log_path)
        return 1
    except KeyboardInterrupt:
        logging.warning("用户已中止。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
