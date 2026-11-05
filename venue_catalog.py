from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from badminton_bot import choose_browser, load_config, open_context
from booking_preferences import site_sport


ROOT = Path(__file__).resolve().parent
HOME = "https://sports.sjtu.edu.cn/pc/#/"
TYPE_API = "https://sports.sjtu.edu.cn/manage/motionType/typeList"
VENUE_API = "https://sports.sjtu.edu.cn/manage/venue/listOrderCount"


def detail_url(venue_id: str, sport: str) -> str:
    # 当前 Vue 路由会再次解码项目参数，因此项目名需要双重 URL 编码。
    encoded_sport = quote(quote(site_sport(sport), safe=""), safe="")
    return f"https://sports.sjtu.edu.cn/pc/#/apointmentDetails/1/{venue_id}/{encoded_sport}/0"


def fetch_catalog(browser_name: str | None = None) -> dict[str, object]:
    cfg = load_config(ROOT / "config.toml")
    choose_browser(cfg, browser_name)
    cfg["browser"]["headless"] = True
    with sync_playwright() as p:
        browser, context = open_context(p, cfg, require_auth=True)
        page = context.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        current_user = page.evaluate(
            "async () => (await fetch('/system/user/currentUser')).json()"
        )
        if current_user.get("code") == 401:
            raise RuntimeError("登录会话已过期，请先运行：python badminton_bot.py login")
        sports = page.evaluate(
            """async (url) => {
              const response = await fetch(url, {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
              });
              return await response.json();
            }""",
            TYPE_API,
        )
        entries: list[dict[str, Any]] = []
        for sport in sports:
            sport_name = str(sport["venueType"])
            payload = page.evaluate(
                """async ([url, sport]) => {
                  const body = new URLSearchParams();
                  body.append('typeIds[0]', sport);
                  body.append('venueName', '');
                  body.append('pageNum', '1');
                  body.append('pageSize', '200');
                  body.append('flag', '0');
                  const response = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
                    body: body.toString()
                  });
                  return await response.json();
                }""",
                [VENUE_API, sport_name],
            )
            if not isinstance(payload, dict) or "rows" not in payload:
                raise RuntimeError(f"项目 {sport_name} 的场馆接口返回异常：{payload}")
            for venue in payload["rows"]:
                venue_id = str(venue["venueId"])
                entries.append(
                    {
                        "sport": sport_name,
                        "sport_en": sport.get("venueTypeEn", ""),
                        "sport_id": sport.get("id", ""),
                        "campus": venue.get("campusName", ""),
                        "venue": venue.get("venueName", ""),
                        "venue_id": venue_id,
                        "venue_state": venue.get("venueState", ""),
                        "is_available": venue.get("isAvailable", ""),
                        "order_type": venue.get("orderType", ""),
                        "detail_url": detail_url(venue_id, sport_name),
                    }
                )
        context.close()
        browser.close()
    entries.sort(key=lambda row: (row["sport"], row["campus"], row["venue"]))
    return {
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "source": {"home": HOME, "type_api": TYPE_API, "venue_api": VENUE_API},
        "sport_count": len(sports),
        "entry_count": len(entries),
        "entries": entries,
    }


def write_catalog(catalog: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 上海交大体育场馆预约详情页目录",
        "",
        f"生成时间：{catalog['generated_at']}（Asia/Shanghai）  ",
        f"项目类型：{catalog['sport_count']}；项目/场馆组合：{catalog['entry_count']}。",
        "",
        "> 本目录由预约网站实时接口生成。场馆上下线后请重新运行 `python venue_catalog.py`。",
        "",
    ]
    current = None
    for row in catalog["entries"]:
        if row["sport"] != current:
            current = row["sport"]
            lines.extend([f"## {current}", ""])
        lines.append(f"- {row['campus']} · [{row['venue']}]({row['detail_url']})")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取上海交大体育场馆预约详情页目录")
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome", "chromium", "firefox", "webkit"],
        help="用于读取目录的浏览器；省略时交互选择",
    )
    args = parser.parse_args()
    catalog = fetch_catalog(args.browser)
    json_path = ROOT / "venue_catalog.json"
    markdown_path = ROOT / "场馆预约详情页目录.md"
    write_catalog(catalog, json_path, markdown_path)
    print(f"已抓取 {catalog['sport_count']} 个项目、{catalog['entry_count']} 个项目/场馆组合。")
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
