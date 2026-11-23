"""Unusual Whales website data, read through the logged-in unusualwhales.com tab of a DICloak profile.

ZZ 2026-11-22: fetch the dark pool price levels (the centroid input) from both DICloak and the UW API, compare them,
and when they agree use DICloak's. The comparison and the choice live in layers.layer_darkpool_levels.

- The site's large-trades page, button "Price Group", loads
  https://phx.unusualwhales.com/api/flow/levels/<T>/volume-price-group: the latest session only (a date parameter is
  ignored). Its stock_price_vol rows {price, dark_pool_volume, regular_volume} are the API's
  /api/darkpool/<T>/price-levels rows: same buckets, equal share for share on 10 names for 2026-11-20.
- The site's stock Dark Pool page (/stock/<T>/darkpool) loads /api/flow/dark/price_levels/<T>?day_range=N: the same
  rows summed over the latest N + 1 sessions (day_range 0 = 1D, 1 = 2D, 2 = 3D, 4 = 1W, 20 = 1M), equal to the API's
  daily tables summed bucket for bucket on 6 names (2026-11-22). It always ends at the latest session (date ignored).
- The tab makes the request itself (Apple Events through workspace-claw-general/dicloak_common/dicloak_browser.py)
  with the headers the site sends: Authorization = "Bearer " + localStorage["app-session"], UW-SH =
  localStorage["uw-sh"], UW-Path = the page path. Without them the site answers with older data. No credential
  leaves the browser and what the tab shows does not change. JavaScript from Apple Events runs in an isolated world,
  whose cross-origin fetch works only without credentials:'include'.
- Needs the DICloak profile with unusualwhales.com open (logged in) and View > Developer > Allow JavaScript from
  Apple Events on in that window. With no unusualwhales.com tab, one is opened in the profile remembered in
  .uwweb_state.json. Any problem raises WebUnavailable; the caller then uses the API alone.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SITE = "https://unusualwhales.com/"
PHX = "https://phx.unusualwhales.com"
OPEN_PATH = "large-trades"
DICLOAK_COMMON = os.environ.get("DICLOAK_COMMON", "/Users/yuwang/.openclaw/workspace-claw-general/dicloak_common")
STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".uwweb_state.json")
CHUNK = 200_000
OPEN_TAB_WAIT = 40.0


class WebUnavailable(RuntimeError):
    """The UW site can't be read through DICloak right now (no profile / tab, logged out, JS blocked, no answer)."""


def _db():
    if DICLOAK_COMMON not in sys.path:
        sys.path.insert(0, DICLOAK_COMMON)
    try:
        import dicloak_browser  # noqa: WPS433
    except ImportError as e:
        raise WebUnavailable(f"dicloak_browser not importable from {DICLOAK_COMMON}: {e}") from None
    return dicloak_browser


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Runs in the tab: fire the requests (at most MAX_PARALLEL at a time, so a batch of 5 goes out at once), park the
# answers in window.__uwweb[slot] (isolated world, shared by our calls). Each answer: {status, text} or {error}.
MAX_PARALLEL = 6
_START = r"""(() => {
  const S = window.__uwweb = window.__uwweb || {};
  const slot = %s, urls = %s, par = %d;
  S[slot] = {done: false};
  const sess = localStorage.getItem('app-session');
  if (!sess) { S[slot] = {done: true, error: 'logged out (no app-session in the tab)'}; return 'started'; }
  const h = {'Accept': 'application/json', 'Content-Type': 'application/json', 'UW-Path': location.pathname,
             'UW-SH': localStorage.getItem('uw-sh') || '', 'Authorization': 'Bearer ' + sess};
  const todo = Object.entries(urls), o = {};
  let next = 0;
  const worker = async () => {
    while (next < todo.length) {
      const [k, u] = todo[next++];
      try { const r = await fetch(u, {headers: h, cache: 'no-store'}); o[k] = {status: r.status, text: await r.text()}; }
      catch (e) { o[k] = {error: String(e && e.message || e)}; }
    }
  };
  Promise.all(Array.from({length: Math.min(par, todo.length)}, worker))
    .then(() => { S[slot] = {done: true, text: JSON.stringify(o)}; });
  return 'started';
})()"""

_STATUS = r"""JSON.stringify((() => { const s = (window.__uwweb || {})[%s];
  return s ? {done: s.done, error: s.error, n: (s.text || '').length} : {gone: true}; })())"""


class UWWeb:
    """One logged-in unusualwhales.com tab; request() / start()+finish() run GETs from it."""

    def __init__(self, open_tab: bool = True, state_file: str = STATE):
        self.open_tab, self.state_file = open_tab, state_file
        self.tab = None
        self.down: Optional[str] = None   # set once DICloak proved unusable: later calls fail fast
        self._lock = threading.RLock()

    # -- the tab ---------------------------------------------------------------
    def _remembered(self) -> Optional[str]:
        try:
            with open(self.state_file) as fh:
                return json.load(fh).get("profile_dir")
        except (OSError, ValueError):
            return None

    def _remember(self, db, pid: int) -> None:
        d = db.profile_dir(pid)
        if d and d != self._remembered():
            with open(self.state_file, "w") as fh:
                json.dump({"profile_dir": d}, fh, indent=1)
                fh.write("\n")

    def _find_tab(self):
        db = _db()
        if not db.browser_pids():
            raise WebUnavailable("no DICloak profile is open")
        try:
            tabs = db.list_tabs(timeout=5)
        except db.BrowserError as e:
            raise WebUnavailable(f"could not list the DICloak tabs: {e}") from None
        uw = [t for t in tabs if t.url.startswith(SITE)]
        if uw:
            uw.sort(key=lambda t: not t.url.startswith(SITE + OPEN_PATH))   # the large-trades tab first
            self._remember(db, uw[0].pid)
            return uw[0]
        want = self._remembered()
        pid = next((p for p in db.browser_pids() if want and db.profile_dir(p) == want), None)
        if pid is None or not self.open_tab:
            raise WebUnavailable("no unusualwhales.com tab in any open DICloak profile")
        try:
            db.open_tab(pid, SITE + OPEN_PATH)
        except db.BrowserError as e:
            raise WebUnavailable(f"could not open an unusualwhales.com tab: {e}") from None
        deadline = time.time() + OPEN_TAB_WAIT
        while time.time() < deadline:
            time.sleep(2)
            for t in db.list_tabs([pid], timeout=5):
                if t.url.startswith(SITE):
                    try:
                        if db.run_js(t, "document.readyState === 'complete' && !!localStorage.getItem('app-session')",
                                     timeout=10):
                            return t
                    except db.BrowserError:
                        pass
        raise WebUnavailable("the new unusualwhales.com tab did not load a logged-in page")

    def _js(self, code: str, timeout: float = 15.0):
        db = _db()
        for _ in range(2):
            if self.tab is None:
                self.tab = self._find_tab()
            try:
                return db.run_js(self.tab, code, timeout=timeout, url_prefix=SITE)
            except db.TabGone:
                self.tab = None   # closed or navigated off the site: look again once
            except (db.NotAuthorized, db.JavaScriptOff, db.NotAnswering) as e:
                raise WebUnavailable(f"{type(e).__name__}: {e}") from None
            except db.BrowserError as e:
                raise WebUnavailable(str(e)) from None
        raise WebUnavailable("the unusualwhales.com tab keeps closing or navigating away")

    # -- requests ----------------------------------------------------------------
    def start(self, paths: Dict[str, str]) -> Dict[str, Any]:
        """Start GET PHX+path for every {label: path} in the tab, all at once; returns a handle for finish().
        The requests are on the wire when this returns."""
        with self._lock:
            if self.down:
                raise WebUnavailable(self.down)
            slot = "s" + uuid.uuid4().hex[:10]
            urls = {k: PHX + p for k, p in paths.items()}
            started = _utcnow()
            try:
                self._js(_START % (json.dumps(slot), json.dumps(urls), MAX_PARALLEL))
            except WebUnavailable as e:
                self.down = str(e)
                raise
            return {"slot": slot, "urls": urls, "started_at": started}

    def finish(self, h: Dict[str, Any], timeout: float = 45.0) -> Dict[str, Dict[str, Any]]:
        """Wait for a started batch; returns {label: {url, status, body, error}} (body = parsed JSON or None).
        Raises WebUnavailable only when the batch as a whole failed (tab gone, logged out, no answer)."""
        slot, ref = h["slot"], "window.__uwweb[%s]" % json.dumps(h["slot"])
        with self._lock:
            try:
                deadline = time.time() + timeout
                while True:
                    st = json.loads(self._js(_STATUS % json.dumps(slot)))
                    if st.get("gone"):
                        raise WebUnavailable("the unusualwhales.com tab reloaded during the request")
                    if st.get("done"):
                        break
                    if time.time() > deadline:
                        raise WebUnavailable(f"the site did not answer within {timeout:.0f}s")
                    time.sleep(0.3)
                if st.get("error"):
                    raise WebUnavailable(st["error"])
                text = "".join(self._js("%s.text.slice(%d, %d)" % (ref, i, i + CHUNK)) or ""
                               for i in range(0, st.get("n") or 0, CHUNK))
            finally:
                try:
                    self._js("(() => { if (window.__uwweb) delete %s; return 'ok'; })()" % ref)
                except WebUnavailable:
                    pass
        out: Dict[str, Dict[str, Any]] = {}
        for k, r in json.loads(text).items():
            res = {"url": h["urls"][k], "status": r.get("status"), "fetched_at": h["started_at"], "body": None,
                   "error": r.get("error")}
            if res["error"] is None and r.get("status") != 200:
                res["error"] = f"HTTP {r.get('status')} from the site: {(r.get('text') or '')[:160]!r}"
            if res["error"] is None:
                try:
                    res["body"] = json.loads(r.get("text") or "")
                except ValueError:
                    res["error"] = f"the site answered non-JSON: {(r.get('text') or '')[:160]!r}"
            out[k] = res
        return out

    def request(self, path: str, timeout: float = 45.0) -> Dict[str, Any]:
        """One GET; raises WebUnavailable on any failure."""
        r = self.finish(self.start({"r": path}), timeout)["r"]
        if r["error"]:
            raise WebUnavailable(r["error"])
        return r


def price_group_path(ticker: str) -> str:
    """The large-trades "Price Group" request: latest session's off-lit / lit volume (and option volume) per price."""
    return f"/api/flow/levels/{ticker}/volume-price-group"


def dark_levels_path(ticker: str, day_range: int) -> str:
    """The stock Dark Pool page's request: off-lit / lit volume per price summed over the latest day_range + 1 sessions."""
    return f"/api/flow/dark/price_levels/{ticker}?day_range={day_range}"


if __name__ == "__main__":   # python3 -m uwsf.uwweb NVDA: print the site's latest session for a ticker
    T = (sys.argv[1] if len(sys.argv) > 1 else "NVDA").upper()
    r = UWWeb(open_tab=False).request(price_group_path(T))
    rows = r["body"].get("stock_price_vol") or []
    print(f"{T} {r['body'].get('date')} · {len(rows)} buckets · dark {sum(float(x['dark_pool_volume']) for x in rows):,.0f}"
          f" · fetched {r['fetched_at']}")
