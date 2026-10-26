"""Token accounting and spend limits.

Rate table (USD per 1M tokens) for gpt-6-luna copied from the course's Lecture 11 pricing.py, which
cites OpenAI standard-tier pricing checked 2026-10-06. Re-verify before reporting; these are token-cost
ESTIMATES computed from returned usage, not invoice totals.

OpenAI usage counts cached tokens inside input_tokens and reasoning tokens inside output_tokens, so
each token is priced exactly once. Usage that the API did not return stays None (never filled in).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .db import DB, new_id, now

RATE_TABLE = {
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50},
    "source": "input/cached/output from the course Lecture 11 pricing.py (OpenAI standard tier, checked 2026-10-06); "
              "cache_write $0.125/1M verified on https://developers.openai.com/api/docs/pricing on 2026-10-25 (root session)",
}
# Built-in web search tool fee per call (search content tokens are billed separately at the model's input rate).
# Source: https://developers.openai.com/api/docs/pricing, $10 per 1,000 calls, checked 2026-10-25 (root session).
WEB_SEARCH_FEE_PER_CALL_USD = 0.01
IMAGE_TOKEN_ESTIMATE = 2000  # conservative per-image reservation estimate, not a measurement


class LimitExceeded(Exception):
    """A spending/abuse limit stopped an AI call BEFORE it was made. `kind` is "rate" (rolling ten minutes), "session"
    (this browser session's lifetime allowance; it does not reset by waiting) or "daily" (app-wide, per UTC day)."""

    def __init__(self, kind: str, message: str | None = None):
        if message is None:  # older form: LimitExceeded("Rate limit: ...")
            message, kind = kind, ("rate" if kind.startswith("Rate limit") else "daily" if kind.startswith("Today") else "session")
        super().__init__(message)
        self.kind = kind


# Every limit message starts with one of these, so any layer can recognise a limit (never a generic retryable error).
LIMIT_PREFIXES = ("Rate limit:", "This session’s search allowance", "Today’s search allowance")


def is_limit_message(text: str | None) -> bool:
    return bool(text) and str(text).startswith(LIMIT_PREFIXES)


def limit_message(kind: str, limit: float | int) -> str:
    """Plain-language messages for people using the app (exact settings live in the README / .env.example)."""
    if kind == "rate":
        return (f"Rate limit: at most {limit} AI requests per 10 minutes per session. It clears as the rolling ten-minute "
                "window passes; you can continue then.")
    if kind == "session":
        return (f"This session’s search allowance would be exceeded (an estimated ${limit:.2f} in total for this browser "
                "session). It doesn’t reset by waiting; the app owner can increase it.")
    return (f"Today’s search allowance for the whole app would be exceeded (an estimated ${limit:.2f} per UTC day). It "
            "resets at the start of the next UTC day.")


def normalize_usage(raw: dict | None) -> dict:
    """Map a Responses API usage object to our fields; missing values stay None."""
    if not isinstance(raw, dict):
        return {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None, "reasoning_tokens": None}
    in_details = raw.get("input_tokens_details") or {}
    out_details = raw.get("output_tokens_details") or {}
    return {
        "input_tokens": raw.get("input_tokens"),
        "cached_input_tokens": in_details.get("cached_tokens") if "cached_tokens" in in_details else None,
        "output_tokens": raw.get("output_tokens"),
        "reasoning_tokens": out_details.get("reasoning_tokens") if "reasoning_tokens" in out_details else None,
    }


def cost_usd(usage: dict, model: str = "gpt-6-luna") -> float | None:
    if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
        return None
    r = RATE_TABLE[model]
    cached = usage.get("cached_input_tokens") or 0
    fresh = max(usage["input_tokens"] - cached, 0)
    return (fresh * r["input"] + cached * r["cached_input"] + usage["output_tokens"] * r["output"]) / 1_000_000


def estimate_reservation(text_chars: int, images: int, max_output_tokens: int, model: str = "gpt-6-luna") -> float:
    r = RATE_TABLE[model]
    input_tokens = text_chars // 3 + images * IMAGE_TOKEN_ESTIMATE + 1500
    return (input_tokens * r["input"] + max_output_tokens * r["output"]) / 1_000_000


class Ledger:
    def __init__(self, db: DB, per_session_calls_10min: int, per_session_usd: float, app_daily_usd: float):
        self.db = db
        self.per_session_calls = per_session_calls_10min
        self.per_session_usd = per_session_usd
        self.app_daily_usd = app_daily_usd

    def reserve(self, session_id: str, project_id: str | None, purpose: str, amount: float) -> str:
        """Atomically check limits and hold `amount` before any model call."""
        rid = new_id("use")
        t_now = datetime.now(timezone.utc)
        ten_min = (t_now - timedelta(minutes=10)).isoformat(timespec="seconds")
        day = t_now.date().isoformat()
        with self.db.tx() as c:
            calls = c.execute(
                "SELECT COUNT(*) FROM usage_ledger WHERE session_id=? AND created_at>=?", (session_id, ten_min)
            ).fetchone()[0]
            if calls >= self.per_session_calls:
                raise LimitExceeded("rate", limit_message("rate", self.per_session_calls))
            spent_session = c.execute(
                "SELECT COALESCE(SUM(COALESCE(actual_usd, reserved_usd)),0) FROM usage_ledger WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            if spent_session + amount > self.per_session_usd:
                raise LimitExceeded("session", limit_message("session", self.per_session_usd))
            spent_day = c.execute(
                "SELECT COALESCE(SUM(COALESCE(actual_usd, reserved_usd)),0) FROM usage_ledger WHERE substr(created_at,1,10)=?",
                (day,),
            ).fetchone()[0]
            if spent_day + amount > self.app_daily_usd:
                raise LimitExceeded("daily", limit_message("daily", self.app_daily_usd))
            c.execute(
                "INSERT INTO usage_ledger VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, session_id, project_id, purpose, "reserved", amount, None, None, now(), None),
            )
        return rid

    def settle(self, rid: str, status: str, actual_usd: float | None, data: dict) -> None:
        # actual None (usage missing) keeps the reservation counted against limits.
        self.db.exec(
            "UPDATE usage_ledger SET status=?, actual_usd=?, data=?, settled_at=? WHERE id=?",
            (status, actual_usd, json.dumps(data, default=str), now(), rid),
        )

    def summary(self, project_id: str | None = None, session_id: str | None = None) -> dict:
        where, args = [], []
        if project_id:
            where.append("project_id=?")
            args.append(project_id)
        if session_id:
            where.append("session_id=?")
            args.append(session_id)
        sql = "SELECT * FROM usage_ledger" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at"
        rows = self.db.all(sql, tuple(args))
        calls = []
        for r in rows:
            d = json.loads(r["data"]) if r["data"] else {}
            calls.append({"id": r["id"], "purpose": r["purpose"], "status": r["status"],
                          "reserved_usd": r["reserved_usd"], "estimated_cost_usd": r["actual_usd"],
                          "created_at": r["created_at"], **{k: d.get(k) for k in (
                              "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens",
                              "web_search_calls", "web_search_fee_usd", "token_cost_usd",
                              "latency_s", "response_ids", "finish_reason", "requests", "validation_retries", "error")}})
        return {"rate_table": RATE_TABLE, "web_search_fee_per_call_usd": WEB_SEARCH_FEE_PER_CALL_USD, "calls": calls,
                "estimated_cost_usd_total": round(sum(c["estimated_cost_usd"] or 0 for c in calls), 6),
                "calls_missing_usage": sum(1 for c in calls if c["status"] == "ok" and c["estimated_cost_usd"] is None)}
