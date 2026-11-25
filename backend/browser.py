"""Browser automation (Playwright), evolved from S.A.G.E's tools/browser.py.

S.A.G.E's lesson (v1.3.0, "say what actually happened"): never report an
action as done without checking. So after filling, we read every field back
FROM THE PAGE and diff it against what we meant to type; the UI shows that
diff, not our intentions.

Playwright's sync API runs on one dedicated thread, which sidesteps the
Windows asyncio subprocess limitations under uvicorn.

Resilience: the person may close the visible Chromium window at any time.
Every operation detects a closed page / context / browser, relaunches, and
re-fills the form from the last values we were asked to fill, so the
consent hash is checked against a real, freshly filled page.
"""
from __future__ import annotations

import concurrent.futures as cf

import config

_pool = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw")
_state: dict = {}
# Last fill request: (base_url, path, fields, values). Used to rebuild a lost page.
_last: dict = {}


class PageLost(RuntimeError):
    """The browser page was closed and could not be rebuilt (nothing filled yet)."""


def _is_closed_error(e: Exception) -> bool:
    s = str(e).lower()
    return any(k in s for k in ("has been closed", "target closed", "browser has disconnected",
                                "connection closed", "not connected", "page closed", "context closed"))


def _reset() -> None:
    for k in ("page", "ctx", "browser"):
        obj = _state.pop(k, None)
        if obj is not None and k != "page":
            try:
                obj.close()
            except Exception:  # noqa: BLE001
                pass


def _ensure_page():
    """Return (page, fresh) where fresh=True means a new page was created."""
    from playwright.sync_api import sync_playwright

    if "pw" not in _state:
        _state["pw"] = sync_playwright().start()
    br = _state.get("browser")
    if br is None or not br.is_connected():
        _reset()
        _state["browser"] = _state["pw"].chromium.launch(headless=not config.HEADED,
                                                         slow_mo=60 if config.HEADED else 0)
    page = _state.get("page")
    if page is not None and not page.is_closed():
        return page, False
    ctx = _state.get("ctx")
    try:
        if ctx is None:
            raise RuntimeError("no context")
        page = ctx.new_page()
    except Exception:  # noqa: BLE001 - context was closed with the window
        try:
            _state["ctx"] = _state["browser"].new_context(viewport={"width": 1100, "height": 900})
        except Exception:  # noqa: BLE001 - browser itself is gone
            _reset()
            _state["browser"] = _state["pw"].chromium.launch(headless=not config.HEADED,
                                                             slow_mo=60 if config.HEADED else 0)
            _state["ctx"] = _state["browser"].new_context(viewport={"width": 1100, "height": 900})
        page = _state["ctx"].new_page()
    _state["page"] = page
    return page, True


def _do_fill(page, base_url: str, path: str, fields: list[dict], values: dict) -> dict:
    page.goto(base_url.rstrip("/") + path)  # fresh form every time
    typed = {}
    for f in fields:
        v = values.get(f["id"])
        if v in (None, ""):
            continue
        sel = f"#{f['id']}"
        if f.get("type") == "select":
            try:
                page.select_option(sel, label=str(v))
            except Exception:  # noqa: BLE001 - value not among options: leave empty, read-back shows it
                continue
        else:
            page.fill(sel, "")
            if config.HEADED:
                page.type(sel, str(v), delay=12)  # visible typing for the demo
            else:
                page.fill(sel, str(v))
        typed[f["id"]] = str(v)
    if page.query_selector("#declaration"):
        page.check("#declaration")
    try:
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass
    return _read_back(page, fields, typed)


def _read_back(page, fields: list[dict], intended: dict | None) -> dict:
    rows = []
    for f in fields:
        el = page.query_selector(f"#{f['id']}")
        actual = el.input_value() if el else None
        want = (intended or {}).get(f["id"], "")
        rows.append({"id": f["id"], "label": f["label"], "intended": want, "on_page": actual,
                     "match": (actual or "") == (want or ""), "required": f.get("required", False)})
    missing = [r["label"] for r in rows if r["required"] and not (r["on_page"] or "").strip()]
    return {"rows": rows, "all_match": all(r["match"] for r in rows), "missing_required": missing,
            "on_page_values": {r["id"]: r["on_page"] for r in rows}}


def _form_page(base_url: str, path: str, fields: list[dict]):
    """A live page showing the filled form. Rebuilds it if the window was closed or navigated away.

    Returns (page, reopened)."""
    page, fresh = _ensure_page()
    url = base_url.rstrip("/") + path
    on_form = False
    if not fresh:
        try:
            on_form = page.url.split("?")[0] == url and page.query_selector("#app-form") is not None \
                and page.is_visible("#app-form")
        except Exception:  # noqa: BLE001
            on_form = False
    if fresh or not on_form:
        if _last:
            _do_fill(page, _last["base_url"], _last["path"], _last["fields"], _last["values"])
        else:
            page.goto(url)
        return page, True
    return page, False


def _with_retry(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        if not _is_closed_error(e):
            raise
        _reset()
        return fn(*a)


def _fill(base_url, path, fields, values):
    _last.update(base_url=base_url, path=path, fields=fields, values=dict(values))

    def run():
        page, _ = _ensure_page()
        return _do_fill(page, base_url, path, fields, values)
    return _with_retry(run)


def _current(base_url, path, fields):
    def run():
        page, reopened = _form_page(base_url, path, fields)
        out = _read_back(page, fields, _last.get("values") if _last else {})
        out["reopened"] = reopened
        return out
    return _with_retry(run)


def _submit(base_url: str, path: str, submit_sel: str, fields: list[dict]) -> dict:
    def run():
        page, _ = _form_page(base_url, path, fields)
        state = _read_back(page, fields, None)
        if state["missing_required"]:
            return {"submitted": False, "application_no": "", "missing": state["missing_required"]}
        if page.query_selector("#declaration") and not page.is_checked("#declaration"):
            page.check("#declaration")
        page.click(submit_sel)
        try:
            page.wait_for_function(
                """() => { const a = document.querySelector('#appno');
                           const v = document.querySelector('#ok-view');
                           return (a && a.textContent.trim().length > 0) ||
                                  (v && getComputedStyle(v).display !== 'none' && a && a.textContent.trim()); }""",
                timeout=15000)
        except Exception as e:  # noqa: BLE001
            if _is_closed_error(e):
                raise
            # Portal refused (HTML5 validation) or did not answer: report which fields are invalid.
            invalid = []
            for f in fields:
                try:
                    if page.eval_on_selector(f"#{f['id']}", "el => !el.checkValidity()"):
                        invalid.append(f["label"])
                except Exception:  # noqa: BLE001
                    pass
            return {"submitted": False, "application_no": "", "missing": invalid}
        appno = page.inner_text("#appno").strip()
        return {"submitted": bool(appno), "application_no": appno, "missing": []}
    return _with_retry(run)


def fill(base_url, path, fields, values):
    return _pool.submit(_fill, base_url, path, fields, values).result(timeout=120)


def submit(base_url, path, submit_sel, fields):
    return _pool.submit(_submit, base_url, path, submit_sel, fields).result(timeout=120)


def current(base_url, path, fields):
    """Full read-back of the live page (rebuilding it if needed)."""
    return _pool.submit(_current, base_url, path, fields).result(timeout=120)


def current_values(base_url, path, fields):
    return current(base_url, path, fields)["on_page_values"]


def last_values() -> dict:
    return dict(_last.get("values", {})) if _last else {}
