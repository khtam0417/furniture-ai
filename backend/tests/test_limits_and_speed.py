"""AI allowance settings and messages, bounded parallel page checks, and duplicate-search protection
(FAKE NETWORK with a simulated delay, MOCKED gpt-6-luna search; nothing leaves the machine)."""

import asyncio
import json
import threading
import time

import httpx2
import pytest

from furnishai.app import COOKIE
from furnishai.config import ConfigError, get_settings
from furnishai.db import DB
from furnishai.safe_fetch import RawResponse
from furnishai.usage import Ledger, LimitExceeded, is_limit_message

from test_design_refine import ONE_BED, _search_body, client, setup
from test_resale_trust import ld_page, prod
from test_shopping_flow import HTML, Net


# ------------------------------------------------------------------ settings
def test_limit_defaults_and_validated_overrides(tmp_path):
    s = get_settings(tmp_path, environ={})
    assert (s.max_session_cost_usd, s.max_app_daily_cost_usd, s.max_ai_calls_per_session_per_10min) == (2.0, 3.0, 12)
    s = get_settings(tmp_path, environ={"FURNISHAI_SESSION_AI_BUDGET_USD": "5", "FURNISHAI_DAILY_AI_BUDGET_USD": "10.5",
                                        "FURNISHAI_AI_REQUESTS_PER_10MIN": "20"})
    assert (s.max_session_cost_usd, s.max_app_daily_cost_usd, s.max_ai_calls_per_session_per_10min) == (5.0, 10.5, 20)
    for key, bad in [("FURNISHAI_SESSION_AI_BUDGET_USD", v) for v in ("abc", "0", "-1", "nan", "inf", "25")] + \
                    [("FURNISHAI_DAILY_AI_BUDGET_USD", v) for v in ("0", "101", "1e9")] + \
                    [("FURNISHAI_AI_REQUESTS_PER_10MIN", v) for v in ("0", "121", "2.5", "x")]:
        with pytest.raises(ConfigError) as e:
            get_settings(tmp_path, environ={key: bad})
        assert key in str(e.value)


# ------------------------------------------------------------------ ledger: reserved + actual, atomic, honest messages
def test_reserved_and_settled_costs_count_and_the_boundary_is_atomic(tmp_path):
    db = DB(tmp_path / "t.sqlite3")
    led = Ledger(db, per_session_calls_10min=100, per_session_usd=1.0, app_daily_usd=10.0)
    r1 = led.reserve("s", None, "x", 0.6)
    led.settle(r1, "ok", 0.2, {})  # actual cost replaces the reservation
    led.reserve("s", None, "x", 0.5)  # still unsettled: its full reservation counts (unknown usage is reserved)
    with pytest.raises(LimitExceeded) as e:
        led.reserve("s", None, "x", 0.31)  # 0.2 + 0.5 + 0.31 > 1.00
    msg = str(e.value)
    assert e.value.kind == "session" and "would be exceeded" in msg and "doesn’t reset by waiting" in msg
    assert "app owner can increase it" in msg and "FURNISHAI" not in msg and "settings" not in msg  # no env name, no fake screen
    assert is_limit_message(msg)
    led.reserve("s", None, "x", 0.3)  # exactly at the boundary is allowed
    ok, errs = [], []
    big = Ledger(db, per_session_calls_10min=100, per_session_usd=2.0, app_daily_usd=100.0)

    def w():
        try:
            ok.append(big.reserve("t", None, "x", 0.5))
        except LimitExceeded as x:
            errs.append(x)
    ts = [threading.Thread(target=w) for _ in range(9)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ok) == 4 and len(errs) == 5  # 4 x 0.50 = 2.00; atomic under concurrency
    day = Ledger(db, per_session_calls_10min=100, per_session_usd=100.0, app_daily_usd=3.3)  # $3.00 used today + 0.60
    with pytest.raises(LimitExceeded) as e:
        day.reserve("u", None, "x", 0.6)
    assert e.value.kind == "daily" and "next UTC day" in str(e.value)
    rate = Ledger(db, per_session_calls_10min=1, per_session_usd=100.0, app_daily_usd=100.0)
    rate.reserve("v", None, "x", 0.0)
    with pytest.raises(LimitExceeded) as e:
        rate.reserve("v", None, "x", 0.0)
    assert e.value.kind == "rate" and "rolling ten-minute window" in str(e.value)


def test_a_session_allowance_pauses_finding_with_its_own_message(tmp_path):
    def gateway(request):
        return httpx2.Response(200, json=_search_body([]))
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway)
    aid, anchor, s = setup(c)
    prefs = {**s["design"]["data"]["prefs"], "condition": "secondhand"}
    c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs})
    app.state.ledger.per_session_usd = 0.0001  # the allowance is (nearly) used up
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"}).json()
    assert r["limited"] and r["limited"].startswith("This session’s search allowance") and "reset by waiting" in r["limited"]
    assert "few minutes" not in r["limited"] and "FURNISHAI" not in r["limited"]


# ------------------------------------------------------------------ bounded parallel checks (simulated delay)
AD, CH, CL = "https://www.aptdeco.com/products/", "https://www.chairish.com/product/", "https://newhaven.craigslist.org/fuo/d/"
LEADS = [CH + "1/oak-nightstand", CH + "2/teak-nightstand", AD + "pine-nightstand", AD + "ash-nightstand",
         CL + "new-haven-nightstand/7700000001.html", CL + "hamden-nightstand/7700000002.html"]


class SlowNet(Net):
    """The fake network with the SAME simulated delay per page; records the peak number of pages in flight."""

    def __init__(self, pages, delay=0.08):
        super().__init__(pages)
        self.delay, self.lock, self.inflight, self.peak = delay, threading.Lock(), 0, 0

    def opener(self, target, headers, timeout, max_bytes):
        with self.lock:
            self.inflight += 1
            self.peak = max(self.peak, self.inflight)
        try:
            time.sleep(self.delay)
            return super().opener(target, headers, timeout, max_bytes)
        finally:
            with self.lock:
                self.inflight -= 1


def pages():
    out = {}
    for n, u in enumerate(LEADS):
        if "teak" in u:
            out[u] = RawResponse(403, HTML, b"denied")  # one failed fetch, isolated
        else:
            out[u] = RawResponse(200, HTML, ld_page([prod("Nightstand", url=u, price=str(900 + n), cond="UsedCondition",
                                                          width=18, depth=15, avail="InStock")]))
    return out


def run(tmp_path, slots):
    def gateway(request):
        return httpx2.Response(200, json=_search_body(LEADS))
    net = SlowNet(pages())
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gateway, net=net.fetcher())
    aid, anchor, s = setup(c)
    prefs = {**s["design"]["data"]["prefs"], "condition": "secondhand", "budget_cents": 300000}
    c.put(f"/api/apartments/{aid}/design/prefs", json={"expected_version": s["design"]["version"], "prefs": prefs})
    import threading as th
    app.state.page_check_slots["sem"] = th.BoundedSemaphore(slots)
    t0 = time.monotonic()
    r = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"}).json()
    took = time.monotonic() - t0
    checks = [json.loads(x["data"]) for x in app.state.db.all("SELECT data FROM research_results WHERE kind='used_check' ORDER BY rowid")]
    return c, app, net, aid, r, took, checks


def test_page_checks_run_at_most_two_at_once_with_the_same_decisions_and_order(tmp_path):
    c, app, net, aid, r, fast, checks = run(tmp_path / "par", 2)
    _, _, net1, _, r1, slow, checks1 = run(tmp_path / "ser", 1)
    assert net.peak == 2 and app.state.check_stats["max_running"] == 2 and net1.peak == 1
    assert len(net.requested) == len(net1.requested)  # identical number of page requests
    dec = lambda rs: sorted((x["url"], x["outcome"], x.get("price_cents")) for x in rs)  # noqa: E731
    assert dec(checks) == dec(checks1)  # identical decisions
    used = r["branches"]["used"]
    assert used == {**used, "checked": r1["branches"]["used"]["checked"], "reasons": r1["branches"]["used"]["reasons"]}
    assert used["reasons"].get("access_blocked") == 1  # the 403 page didn't stop the others
    # Round-robin order across marketplaces is kept in the results, whatever finished first (DB rows are written in
    # completion order, which may differ).
    assert used["checked_urls"] == r1["branches"]["used"]["checked_urls"]
    assert [u.split("/")[2] for u in used["checked_urls"][:3]] == ["www.chairish.com", "www.aptdeco.com", "newhaven.craigslist.org"]
    assert fast < slow  # simulated equal delays only; not a live measurement
    # The short-lived check cache: the same group again fetches nothing and decides the same.
    n = len(net.requested)
    again = c.post(f"/api/apartments/{aid}/design/find-group", json={"key": "nightstand|"}).json()
    assert len(net.requested) == n and again["options_used"] == r["options_used"]


# ------------------------------------------------------------------ duplicate identical searches pay once
class Gate:
    """A mocked search endpoint that waits until released, so concurrent requests overlap deterministically."""

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail
        self.entered = self.release = None

    async def __call__(self, request):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        if self.fail:
            return httpx2.Response(500, json={"error": "upstream down"})
        return httpx2.Response(200, json=_search_body([]))


def _app_for(tmp_path, gate):
    c, app, calls = client(tmp_path, [ONE_BED], live=True, gateway=gate)
    aid, anchor, s = setup(c)
    ns = next(i for i in s["design"]["data"]["items"] if i["category"] == "nightstand")
    url = f"/api/apartments/{aid}/design/items/{ns['id']}/find-online"
    return app, c.cookies.get(COOKIE), url, s["design"]["version"]


async def _on_one_loop(app, token, gate, work):
    """Requests on ONE event loop through the ASGI app (as in production), never threads with separate loops."""
    gate.entered, gate.release = asyncio.Event(), asyncio.Event()
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://app.test",
                                  cookies={COOKIE: token}) as ac:
        return await asyncio.wait_for(work(ac), timeout=20)


def test_concurrent_identical_searches_share_one_ai_request_and_the_cache_expires(tmp_path, monkeypatch):
    gate = Gate()
    app, token, url, v = _app_for(tmp_path, gate)

    async def work(ac):
        a = asyncio.create_task(ac.post(url, json={"expected_version": v}))
        await gate.entered.wait()
        b = asyncio.create_task(ac.post(url, json={"expected_version": v}))  # arrives while the first is in flight
        await asyncio.sleep(0.05)
        gate.release.set()
        ra, rb = await a, await b
        rc = await ac.post(url, json={"expected_version": v})  # within the cache window
        return ra.status_code, rb.status_code, rc.status_code
    assert asyncio.run(_on_one_loop(app, token, gate, work)) == (200, 200, 200)
    assert gate.calls == 1  # one paid request for two concurrent identical searches, zero for the cached repeat
    import furnishai.app as appmod
    monkeypatch.setattr(appmod, "CACHE_TTL_S", -1)  # the saved result is now "expired"

    async def later(ac):
        gate.release.set()
        return (await ac.post(url, json={"expected_version": v})).status_code
    assert asyncio.run(_on_one_loop(app, token, gate, later)) == 200 and gate.calls == 2


def test_a_failing_shared_search_fails_both_waiters_once_and_is_not_cached(tmp_path):
    gate = Gate(fail=True)
    app, token, url, v = _app_for(tmp_path, gate)
    led = app.state.db

    async def work(ac):
        a = asyncio.create_task(ac.post(url, json={"expected_version": v}))
        await gate.entered.wait()
        b = asyncio.create_task(ac.post(url, json={"expected_version": v}))
        await asyncio.sleep(0.05)
        gate.release.set()
        return (await a).status_code, (await b).status_code
    assert asyncio.run(_on_one_loop(app, token, gate, work)) == (502, 502)
    assert gate.calls == 1  # the second waiter shared the first one's failure: no second paid attempt in that flight
    assert led.one("SELECT COUNT(*) n FROM usage_ledger WHERE purpose LIKE 'web_research%'")["n"] == 1
    assert led.one("SELECT COUNT(*) n FROM research_results WHERE kind='furniture'")["n"] == 0  # failure never cached
    gate.fail = False

    async def retry(ac):
        gate.release.set()
        return (await ac.post(url, json={"expected_version": v})).status_code
    assert asyncio.run(_on_one_loop(app, token, gate, retry)) == 200 and gate.calls == 2  # a later attempt may retry


def test_one_waiter_disconnecting_does_not_cancel_the_shared_search(tmp_path):
    gate = Gate()
    app, token, url, v = _app_for(tmp_path, gate)

    async def work(ac):
        a = asyncio.create_task(ac.post(url, json={"expected_version": v}))
        await gate.entered.wait()
        b = asyncio.create_task(ac.post(url, json={"expected_version": v}))
        await asyncio.sleep(0.05)
        a.cancel()  # the first caller goes away mid-search
        await asyncio.sleep(0.05)
        gate.release.set()
        rb = await b
        try:
            await a
        except asyncio.CancelledError:
            pass
        return rb.status_code
    assert asyncio.run(_on_one_loop(app, token, gate, work)) == 200
    assert gate.calls == 1
    assert app.state.db.one("SELECT COUNT(*) n FROM research_results WHERE kind='furniture'")["n"] == 1  # stored once
