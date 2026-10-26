"""Runtime settings.

Environment precedence: process environment > repo-root .env > immediate parent .env.
Nothing above the immediate parent is searched. Secret values are never logged or returned
by the API; only their presence is reported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]

# The only runtime model. Deliberately not configurable from the environment: no fallback.
MODEL = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

ENV_KEYS = ("PORTKEY_API_KEY", "FURNISHAI_DISABLE_LIVE", "FURNISHAI_STORAGE_DIR", "FURNISHAI_PUBLIC_READER",
            "FURNISHAI_SESSION_AI_BUDGET_USD", "FURNISHAI_DAILY_AI_BUDGET_USD", "FURNISHAI_AI_REQUESTS_PER_10MIN")
# Validated limit overrides: (default, minimum exclusive/inclusive, maximum). Estimated costs, not invoices.
LIMITS = {
    "FURNISHAI_SESSION_AI_BUDGET_USD": (2.00, 0.0, 20.0),   # lifetime estimated allowance per browser session
    "FURNISHAI_DAILY_AI_BUDGET_USD": (3.00, 0.0, 100.0),    # app-wide estimated allowance per UTC day
    "FURNISHAI_AI_REQUESTS_PER_10MIN": (12, 1, 120),        # AI requests per session per rolling ten minutes
}


class ConfigError(ValueError):
    """An invalid setting (the key is named; its value is never echoed beyond the number check)."""


def _limit(env: dict[str, str], key: str):
    default, lo, hi = LIMITS[key]
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        val = int(raw) if isinstance(default, int) else float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number.") from None
    import math
    if isinstance(val, float) and not math.isfinite(val):
        raise ConfigError(f"{key} must be a finite number.")
    if isinstance(default, int):
        if not lo <= val <= hi:
            raise ConfigError(f"{key} must be a whole number from {lo} to {hi}.")
    elif not lo < val <= hi:
        raise ConfigError(f"{key} must be more than {lo:g} and at most {hi:g} (US dollars).")
    return val


def load_env(repo_root: Path = REPO_ROOT, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Merge settings: process env wins, then <repo>/.env, then <repo>/../.env for missing values."""
    environ = os.environ if environ is None else environ
    merged: dict[str, str] = {}
    for path in (repo_root.parent / ".env", repo_root / ".env"):  # later files override earlier
        if path.is_file():
            for key, value in dotenv_values(path).items():
                if value is not None and value.strip():
                    merged[key] = value.strip()
    for key, value in environ.items():
        if value is not None and value.strip():
            merged[key] = value.strip()
    return merged


def env_source(key: str, repo_root: Path = REPO_ROOT, environ: dict[str, str] | None = None) -> str | None:
    """Where a setting came from ('process', 'repo .env', 'parent .env') without exposing its value."""
    environ = os.environ if environ is None else environ
    if (environ.get(key) or "").strip():
        return "process"
    for label, path in (("repo .env", repo_root / ".env"), ("parent .env", repo_root.parent / ".env")):
        if path.is_file() and (dotenv_values(path).get(key) or "").strip():
            return label
    return None


@dataclass
class Settings:
    storage_dir: Path
    portkey_api_key: str | None = field(repr=False, default=None)
    live_disabled: bool = False
    key_source: str | None = None
    # Spending/abuse limits (reserved before calls; see usage.py).
    max_ai_calls_per_session_per_10min: int = 12
    max_session_cost_usd: float = 2.00  # lifetime estimated allowance per browser session (doesn't reset by waiting)
    max_app_daily_cost_usd: float = 3.00
    max_output_tokens: int = 4000
    request_timeout_s: float = 90.0
    max_photos: int = 8
    max_upload_bytes: int = 15 * 1024 * 1024
    max_pixels: int = 50_000_000
    # Public page reader fallback for property sites that refuse automated reading (Jina Reader's default anonymous
    # route; no key). FURNISHAI_PUBLIC_READER=off turns it off. See reader.py.
    public_reader: bool = True

    @property
    def live_available(self) -> bool:
        return bool(self.portkey_api_key) and not self.live_disabled

    def public_status(self) -> dict:
        return {
            "model": MODEL,
            "live_ai_available": self.live_available,
            "key_present": bool(self.portkey_api_key),
            "key_source": self.key_source,
            "live_disabled_by_setting": self.live_disabled,
            "public_reader": self.public_reader,
        }


def get_settings(repo_root: Path = REPO_ROOT, environ: dict[str, str] | None = None) -> Settings:
    env = load_env(repo_root, environ)
    storage = Path(env.get("FURNISHAI_STORAGE_DIR") or (repo_root / "storage"))
    return Settings(
        storage_dir=storage,
        portkey_api_key=env.get("PORTKEY_API_KEY") or None,
        live_disabled=env.get("FURNISHAI_DISABLE_LIVE", "").lower() in {"1", "true", "yes"},
        key_source=env_source("PORTKEY_API_KEY", repo_root, environ),
        public_reader=env.get("FURNISHAI_PUBLIC_READER", "on").lower() not in {"0", "off", "false", "no"},
        max_session_cost_usd=_limit(env, "FURNISHAI_SESSION_AI_BUDGET_USD"),
        max_app_daily_cost_usd=_limit(env, "FURNISHAI_DAILY_AI_BUDGET_USD"),
        max_ai_calls_per_session_per_10min=_limit(env, "FURNISHAI_AI_REQUESTS_PER_10MIN"),
    )
