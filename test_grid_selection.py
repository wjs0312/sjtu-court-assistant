from playwright.sync_api import sync_playwright
from unittest.mock import patch
from badminton_bot import (
    Runtime,
    auth_paths,
    choose_browser,
    choose_catalog_entries,
    discover_grid_options,
    load_venue_catalog,
    parse_multi_choice,
    parse_time_preferences,
    select_sjtu_slot,
    wait_for_sjtu_detail,
)

assert parse_multi_choice("1,3,2", ["a", "b", "c"]) == ["a", "c", "b"]
assert parse_multi_choice("1 3 2", ["a", "b", "c"]) == ["a", "c", "b"]
assert parse_multi_choice("1；3，2", ["a", "b", "c"]) == ["a", "c", "b"]
slot_values = ["19:00-20:00", "20:00-21:00", "21:00-22:00"]
assert parse_time_preferences("(1,2),3", slot_values) == [slot_values[:2], [slot_values[2]]]
assert parse_time_preferences("（1，2），3", slot_values) == [slot_values[:2], [slot_values[2]]]
browser_cfg = {
    "browser": {"channel": "msedge"},
    "site": {"auth_state": ".auth/state.json", "session_storage": ".auth/session_storage.json"},
}
choose_browser(browser_cfg, "firefox")
state_path, session_path = auth_paths(browser_cfg)
assert state_path.parts[-2:] == ("firefox", "state.json")
assert session_path.parts[-2:] == ("firefox", "session_storage.json")
assert parse_multi_choice("", ["a", "b"], default_all=True) == ["a", "b"]
assert len(load_venue_catalog()) == 58
sample_catalog = [
    {"sport": "羽毛球", "venue": "场馆A", "venue_id": "a", "campus": "闵行"},
    {"sport": "羽毛球", "venue": "场馆B", "venue_id": "b", "campus": "闵行"},
]
with patch("builtins.input", side_effect=["1,1", "1,2"]):
    chosen = choose_catalog_entries(sample_catalog, set(), 2)
assert [row["venue_id"] for row in chosen] == ["a", "b"]

cfg = {"target": {"court": "场地1", "court_priority": ["场地1", "场地2"]}}
rt = Runtime(cfg, {"start_time": "21:00"}, True)
html = """
<style>
.h { position:absolute; top:20px; width:80px }
.t { position:absolute; left:10px; top:120px }
.c { position:absolute; top:110px; width:80px; height:50px; background:rgb(210,230,255) }
</style>
<div class="h" style="left:100px">场地1</div>
<div class="h" style="left:220px">场地2</div>
<div class="t">21:00</div>
<button id="slot" class="c" style="left:100px" onclick="this.dataset.hit='1'"></button>
"""
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 500, "height": 300})
    page.goto(
        "data:text/html,<div id='apointmentDetails'>ready</div>"
        "#/apointmentDetails/1/test/%25E7%25BE%25BD%25E6%25AF%259B%25E7%2590%2583/0"
    )
    wait_for_sjtu_detail(page, 3000)
    page.set_content(html)
    select_sjtu_slot(page, rt, 3000)
    assert page.locator("#slot").get_attribute("data-hit") == "1"
    page.set_content("<span>07:00</span><span>08:00</span><span>09:00</span><span>10:00</span>")
    _, intervals = discover_grid_options(page)
    assert intervals == ["07:00-08:00", "08:00-09:00", "09:00-10:00"]

    page.set_content("""
    <style>
    .h { position:absolute; top:20px; width:80px }
    .t { position:absolute; left:10px }
    .c { position:absolute; width:80px; height:45px; background:rgb(210,230,255) }
    </style>
    <div class="h" style="left:100px">场地1</div><div class="h" style="left:220px">场地2</div>
    <div class="t" style="top:120px">21:00</div><div class="t" style="top:170px">22:00</div>
    <button class="c" id="a" style="left:220px;top:110px" onclick="this.dataset.hit='1'"></button>
    <button class="c" id="b" style="left:220px;top:160px" onclick="this.dataset.hit='1'"></button>
    """)
    multi_cfg = {"target": {"court_priority": ["场地1", "场地2"],
                             "time_slot_priority": ["21:00-22:00", "22:00-23:00"],
                             "time_slot_groups": [["21:00-22:00", "22:00-23:00"]]}}
    multi_rt = Runtime(multi_cfg, {"start_time": "21:00"}, True)
    select_sjtu_slot(page, multi_rt, 3000)
    assert page.locator("#a").get_attribute("data-hit") == "1"
    assert page.locator("#b").get_attribute("data-hit") == "1"
    assert multi_rt.variables["selected_court"] == "场地2"
    assert multi_rt.variables["selected_time_slot"] == "21:00-23:00"
    browser.close()
print("蓝色场地选择测试通过")
