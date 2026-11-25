"""Browser automation (Playwright), evolved from S.A.G.E's tools/browser.py.

S.A.G.E's lesson (v1.3.0, "say what actually happened"): never report an
action as done without checking. So after filling, we read every field back
FROM THE PAGE and diff it against what we meant to type; the UI shows that
diff, not our intentions.

Playwright's sync API runs on one dedicated thread, which sidesteps the
Windows asyncio subprocess limitations under uvicorn.
"""
from __future__ import annotations

import concurrent.futures as cf

import config

_pool = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw")
_state: dict = {}


def _page(base_url: str, path: str):
    from playwright.sync_api import sync_playwright

    if "pw" not in _state:
        _state["pw"] = sync_playwright().start()
    if "browser" not in _state or not _state["browser"].is_connected():
        _state["browser"] = _state["pw"].chromium.launch(headless=not config.HEADED, slow_mo=60 if config.HEADED else 0)
        _state["ctx"] = _state["browser"].new_context(viewport={"width": 1100, "height": 900})
    ctx = _state["ctx"]
    page = _state.get("page")
    if page is None or page.is_closed():
        page = ctx.new_page()
        _state["page"] = page
    url = base_url.rstrip("/") + path
    if page.url != url:
        page.goto(url)
    page.bring_to_front()
    return page


def _fill(base_url: str, path: str, fields: list[dict], values: dict) -> dict:
    page = _page(base_url, path)
    page.goto(base_url.rstrip("/") + path)  # fresh form every time
    typed = {}
    for f in fields:
        v = values.get(f["id"])
        if v in (None, ""):
            continue
        sel = f"#{f['id']}"
        if f.get("type") == "select":
            page.select_option(sel, label=str(v))
        else:
            page.fill(sel, "")
            page.type(sel, str(v), delay=12 if config.HEADED else 0)
        typed[f["id"]] = str(v)
    if page.query_selector("#declaration"):
        page.check("#declaration")
    return _read_back(page, fields, typed)


def _read_back(page, fields: list[dict], intended: dict) -> dict:
    rows = []
    for f in fields:
        sel = f"#{f['id']}"
        el = page.query_selector(sel)
        actual = el.input_value() if el else None
        want = intended.get(f["id"], "")
        rows.append({"id": f["id"], "label": f["label"], "intended": want, "on_page": actual,
                     "match": (actual or "") == (want or ""), "required": f.get("required", False)})
    missing = [r["label"] for r in rows if r["required"] and not r["on_page"]]
    return {"rows": rows, "all_match": all(r["match"] for r in rows), "missing_required": missing,
            "on_page_values": {r["id"]: r["on_page"] for r in rows}}


def _submit(base_url: str, path: str, submit_sel: str) -> dict:
    page = _page(base_url, path)
    page.click(submit_sel)
    page.wait_for_selector("#appno", state="visible", timeout=10000)
    appno = page.inner_text("#appno").strip()
    return {"submitted": bool(appno), "application_no": appno}


def _current_values(base_url: str, path: str, fields: list[dict]) -> dict:
    page = _page(base_url, path)
    return _read_back(page, fields, {})["on_page_values"]


def fill(base_url, path, fields, values):
    return _pool.submit(_fill, base_url, path, fields, values).result(timeout=120)


def submit(base_url, path, submit_sel):
    return _pool.submit(_submit, base_url, path, submit_sel).result(timeout=60)


def current_values(base_url, path, fields):
    return _pool.submit(_current_values, base_url, path, fields).result(timeout=30)
